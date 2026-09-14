# ============================================================
# app/integrations_engine.py
# AI Talent Match Pro — Phase 32A Partner Integrations Engine
# Greenhouse + Lever + Zapier + Make.com
# Turns AITMP into a plug-and-play recruiting intelligence layer
# ============================================================

import hashlib
import hmac
import json
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
import httpx

from app.db import (
    CompanyCandidateORM, CompanyRoleORM,
    PartnerSyncLogORM, UsageLogORM
)

# ============================================================
# SUPPORTED PARTNERS
# ============================================================
PARTNERS = ["greenhouse", "lever", "zapier", "make"]

# ============================================================
# FIELD MAPPING — Greenhouse → AITMP
# ============================================================
GREENHOUSE_FIELD_MAP = {
    "first_name":   "name",           # combined with last_name
    "last_name":    "name",
    "email_addresses": "email",
    "applications": "job_id",
    "recruiter":    "added_by",
    "stage":        "notes",
}

# ============================================================
# FIELD MAPPING — Lever → AITMP
# ============================================================
LEVER_FIELD_MAP = {
    "name":         "name",
    "emails":       "email",
    "opportunity":  "job_id",
    "stage":        "notes",
    "owner":        "added_by",
}

# ============================================================
# STEP 1 — NORMALIZE INBOUND PAYLOADS
# ============================================================

def normalize_greenhouse_candidate(payload: dict) -> dict:
    """
    Normalize a Greenhouse candidate webhook payload
    into AITMP's internal CompanyCandidateORM format.
    """
    candidate = payload.get("payload", {}).get("candidate", payload.get("candidate", {}))
    application = payload.get("payload", {}).get("application", {})

    # Build full name
    first = candidate.get("first_name", "")
    last  = candidate.get("last_name", "")
    name  = f"{first} {last}".strip() or "Unknown Candidate"

    # Get email
    emails    = candidate.get("email_addresses", [])
    email     = emails[0].get("value", "") if emails else ""

    # Get LinkedIn URL
    urls      = candidate.get("website_addresses", [])
    linkedin  = next((u.get("value") for u in urls if "linkedin" in u.get("value", "").lower()), None)

    # Get job title from application
    job_title = application.get("job", {}).get("name", "") if application else ""

    # Get recruiter notes
    notes = candidate.get("recruiter", {}).get("name", "")
    stage = application.get("current_stage", {}).get("name", "") if application else ""

    return {
        "name":                  name,
        "role":                  job_title,
        "linkedin_url":          linkedin,
        "notes":                 f"Stage: {stage}" if stage else "",
        "tier":                  "bronze",          # default — AI will re-score
        "match_score":           0.0,
        "adaptability":          0.0,
        "focus_penalty":         0.0,
        "ai_analysis":           f"Imported from Greenhouse. Stage: {stage}",
        "partner_source":        "greenhouse",
        "partner_candidate_id":  str(candidate.get("id", "")),
        "external_email":        email,
    }


def normalize_lever_candidate(payload: dict) -> dict:
    """
    Normalize a Lever candidate webhook payload
    into AITMP's internal format.
    """
    candidate   = payload.get("data", {}).get("candidate", payload.get("candidate", {}))
    opportunity = payload.get("data", {}).get("opportunity", {})

    name     = candidate.get("name", "Unknown Candidate")
    emails   = candidate.get("emails", [])
    email    = emails[0] if emails else ""
    urls     = candidate.get("links", [])
    linkedin = next((u for u in urls if "linkedin" in u.lower()), None)
    stage    = opportunity.get("stage", {}).get("text", "") if opportunity else ""
    job_title = opportunity.get("posting", {}).get("text", "") if opportunity else ""

    return {
        "name":                  name,
        "role":                  job_title,
        "linkedin_url":          linkedin,
        "notes":                 f"Stage: {stage}" if stage else "",
        "tier":                  "bronze",
        "match_score":           0.0,
        "adaptability":          0.0,
        "focus_penalty":         0.0,
        "ai_analysis":           f"Imported from Lever. Stage: {stage}",
        "partner_source":        "lever",
        "partner_candidate_id":  str(candidate.get("id", "")),
        "external_email":        email,
    }


def normalize_zapier_candidate(payload: dict) -> dict:
    """
    Normalize a Zapier action payload into AITMP format.
    Zapier sends flat key-value pairs.
    """
    return {
        "name":                  payload.get("name", "Unknown"),
        "role":                  payload.get("role", ""),
        "linkedin_url":          payload.get("linkedin_url"),
        "notes":                 payload.get("notes", ""),
        "tier":                  payload.get("tier", "bronze"),
        "match_score":           float(payload.get("match_score", 0)),
        "adaptability":          float(payload.get("adaptability", 0)),
        "focus_penalty":         float(payload.get("focus_penalty", 0)),
        "ai_analysis":           payload.get("ai_analysis", "Imported via Zapier"),
        "partner_source":        "zapier",
        "partner_candidate_id":  payload.get("external_id", ""),
    }


# ============================================================
# STEP 2 — DUPLICATE DETECTION
# ============================================================

def detect_duplicate(
    db: Session,
    company_id: str,
    partner: str,
    partner_candidate_id: str,
    name: str
) -> Optional[CompanyCandidateORM]:
    """
    Check if a candidate already exists.
    First checks by partner_candidate_id, then by name.
    """
    # Check by external ID
    if partner_candidate_id:
        existing = db.query(CompanyCandidateORM).filter(
            CompanyCandidateORM.company_id == company_id,
            CompanyCandidateORM.partner_source == partner,
            CompanyCandidateORM.partner_candidate_id == partner_candidate_id,
            CompanyCandidateORM.is_deleted == False
        ).first()
        if existing:
            return existing

    # Check by name (fuzzy — exact match for now)
    existing = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.name == name,
        CompanyCandidateORM.is_deleted == False
    ).first()

    return existing


# ============================================================
# STEP 3 — INBOUND SYNC (ATS → AITMP)
# ============================================================

def process_inbound_event(
    db: Session,
    company_id: str,
    partner: str,
    event_type: str,
    raw_payload: dict,
    added_by: str = "system"
) -> dict:
    """
    Process an inbound webhook event from a partner ATS.
    Normalizes payload, detects duplicates, saves candidate.

    Returns: sync result dict
    """
    start = time.time()
    log_id = str(uuid.uuid4())

    try:
        # Step 1 — Normalize
        if partner == "greenhouse":
            normalized = normalize_greenhouse_candidate(raw_payload)
        elif partner == "lever":
            normalized = normalize_lever_candidate(raw_payload)
        elif partner == "zapier":
            normalized = normalize_zapier_candidate(raw_payload)
        else:
            normalized = raw_payload  # passthrough for make.com

        # Step 2 — Duplicate check
        existing = detect_duplicate(
            db, company_id, partner,
            normalized.get("partner_candidate_id", ""),
            normalized.get("name", "")
        )

        if existing:
            # Update existing candidate
            existing.notes      = normalized.get("notes", existing.notes)
            existing.ai_analysis = normalized.get("ai_analysis", existing.ai_analysis)
            db.commit()
            action = "updated"
            candidate_id = existing.id
        else:
            # Create new candidate
            candidate_id = str(uuid.uuid4())
            candidate = CompanyCandidateORM(
                id=candidate_id,
                company_id=company_id,
                added_by=added_by,
                name=normalized.get("name", "Unknown"),
                role=normalized.get("role", ""),
                tier=normalized.get("tier", "bronze"),
                match_score=normalized.get("match_score", 0.0),
                adaptability=normalized.get("adaptability", 0.0),
                focus_penalty=normalized.get("focus_penalty", 0.0),
                ai_analysis=normalized.get("ai_analysis", ""),
                silent_skill=normalized.get("silent_skill"),
                linkedin_url=normalized.get("linkedin_url"),
                notes=normalized.get("notes", ""),
                partner_source=partner,
                partner_candidate_id=normalized.get("partner_candidate_id", "")
            )
            db.add(candidate)
            db.commit()
            action = "created"

        latency_ms = round((time.time() - start) * 1000, 2)

        # Log the sync
        _log_sync(
            db=db,
            company_id=company_id,
            partner=partner,
            direction="inbound",
            event_type=event_type,
            payload=json.dumps(raw_payload)[:2000],
            normalized=json.dumps(normalized)[:2000],
            status="success",
            latency_ms=latency_ms,
            candidate_id=candidate_id,
            external_id=normalized.get("partner_candidate_id", "")
        )

        return {
            "ok":           True,
            "action":       action,
            "candidate_id": candidate_id,
            "partner":      partner,
            "event_type":   event_type,
            "latency_ms":   latency_ms
        }

    except Exception as e:
        latency_ms = round((time.time() - start) * 1000, 2)
        _log_sync(
            db=db,
            company_id=company_id,
            partner=partner,
            direction="inbound",
            event_type=event_type,
            payload=json.dumps(raw_payload)[:2000],
            normalized=None,
            status="failed",
            error=str(e),
            latency_ms=latency_ms
        )
        return {"ok": False, "error": str(e), "partner": partner}


# ============================================================
# STEP 4 — OUTBOUND SYNC (AITMP → ATS)
# Push scores, narratives, tier back to partner
# ============================================================

async def push_to_partner(
    db: Session,
    company_id: str,
    candidate_id: str,
    partner: str,
    partner_api_key: str,
    event_type: str = "score.updated"
) -> dict:
    """
    Push AITMP enrichment data back to partner ATS.
    Sends: match_score, tier, narrative, silent_skill.
    """
    start = time.time()

    candidate = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.id == candidate_id,
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.is_deleted == False
    ).first()

    if not candidate:
        return {"ok": False, "error": "Candidate not found"}

    # Build enrichment payload
    enrichment = {
        "aitmp_match_score":   candidate.match_score,
        "aitmp_tier":          candidate.tier,
        "aitmp_adaptability":  candidate.adaptability,
        "aitmp_silent_skill":  candidate.silent_skill,
        "aitmp_ai_analysis":   candidate.ai_analysis,
        "aitmp_shortlisted":   candidate.shortlisted,
        "aitmp_updated_at":    datetime.utcnow().isoformat()
    }

    status    = "failed"
    http_code = None
    error     = None
    result    = {}   # stays {} if the push raises before assignment

    try:
        if partner == "greenhouse":
            result = await _push_to_greenhouse(
                candidate.partner_candidate_id,
                enrichment, partner_api_key
            )
        elif partner == "lever":
            result = await _push_to_lever(
                candidate.partner_candidate_id,
                enrichment, partner_api_key
            )
        else:
            # Zapier/Make outbound push isn't wired to a real webhook send yet —
            # report honestly (501 Not Implemented) instead of logging a fake success.
            result = {
                "ok": False,
                "not_connected": True,
                "http_status": 501,
                "error": f"{partner} outbound push isn't implemented yet — no outbound webhook is configured. "
                         f"Greenhouse and Lever pushes work today.",
            }

        status    = "success" if result.get("ok") else "failed"
        http_code = result.get("http_status", 200)

    except Exception as e:
        error = str(e)

    latency_ms = round((time.time() - start) * 1000, 2)

    _log_sync(
        db=db,
        company_id=company_id,
        partner=partner,
        direction="outbound",
        event_type=event_type,
        payload=json.dumps(enrichment),
        status=status,
        error=error,
        latency_ms=latency_ms,
        candidate_id=candidate_id,
        external_id=candidate.partner_candidate_id
    )

    return {
        "ok":            status == "success",
        "partner":       partner,
        "candidate":     candidate_id,
        "latency_ms":    latency_ms,
        "status":        status,
        # Surfaced so the API layer can answer 501 rather than a misleading 200.
        "not_connected": bool(result.get("not_connected")) if isinstance(result, dict) else False,
        "http_status":   http_code or (200 if status == "success" else 502),
        "error":         error or (result.get("error") if isinstance(result, dict) else None),
    }


async def _push_to_greenhouse(
    external_id: str,
    enrichment: dict,
    api_key: str
) -> dict:
    """Push enrichment data to Greenhouse Harvest API."""
    if not api_key:
        return {"ok": False, "error": "No API key stored for this connection."}
    if not external_id:
        # An uploaded CV has no record in the ATS, so there is nothing to
        # attach a note to. Say that, rather than "Missing external_id".
        return {"ok": False, "http_status": 409, "error":
                "This candidate came from a CV uploaded here, so there is no "
                "record in your ATS to attach the score to. Scores can only be "
                "pushed for candidates that arrived from your ATS."}

    try:
        async with httpx.AsyncClient() as client:
            # Add note to candidate in Greenhouse
            resp = await client.post(
                f"https://harvest.greenhouse.io/v1/candidates/{external_id}/activity_feed",
                auth=(api_key, ""),
                json={
                    "user_id":  1,
                    "subject":  "AI Talent Match Pro Score",
                    "body":     (
                        f"Match Score: {enrichment['aitmp_match_score']}/100\n"
                        f"Tier: {enrichment['aitmp_tier'].upper()}\n"
                        f"Adaptability: {enrichment['aitmp_adaptability']}/100\n"
                        f"Silent Skill: {enrichment['aitmp_silent_skill']}\n"
                        f"Analysis: {enrichment['aitmp_ai_analysis']}"
                    ),
                    "visibility": "admin_only"
                },
                timeout=10.0
            )
            return {"ok": resp.status_code < 400, "http_status": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _push_to_lever(
    external_id: str,
    enrichment: dict,
    api_key: str
) -> dict:
    """Push enrichment data to Lever API."""
    if not api_key:
        return {"ok": False, "error": "No API key stored for this connection."}
    if not external_id:
        # An uploaded CV has no record in the ATS, so there is nothing to
        # attach a note to. Say that, rather than "Missing external_id".
        return {"ok": False, "http_status": 409, "error":
                "This candidate came from a CV uploaded here, so there is no "
                "record in your ATS to attach the score to. Scores can only be "
                "pushed for candidates that arrived from your ATS."}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.lever.co/v1/opportunities/{external_id}/notes",
                auth=(api_key, ""),
                json={
                    "value": (
                        f"🎯 AI Talent Match Pro\n"
                        f"Score: {enrichment['aitmp_match_score']}/100 | "
                        f"Tier: {enrichment['aitmp_tier'].upper()} | "
                        f"Adaptability: {enrichment['aitmp_adaptability']}/100\n"
                        f"Analysis: {enrichment['aitmp_ai_analysis']}"
                    ),
                    "secret": False
                },
                timeout=10.0
            )
            return {"ok": resp.status_code < 400, "http_status": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================================================
# STEP 5 — WEBHOOK SIGNATURE VERIFICATION
# Verify incoming webhooks from partners
# ============================================================

def verify_greenhouse_signature(
    payload: bytes,
    signature: str,
    secret: str
) -> bool:
    """Verify Greenhouse webhook HMAC-SHA256 signature."""
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_lever_signature(
    payload: bytes,
    signature: str,
    secret: str
) -> bool:
    """Verify Lever webhook HMAC-SHA256 signature."""
    expected = "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ============================================================
# STEP 6 — ZAPIER APP MANIFEST
# ============================================================

ZAPIER_APP_MANIFEST = {
    "name":        "AI Talent Match Pro",
    "description": "Connect your ATS to AI-powered candidate scoring and narrative generation.",
    "version":     "1.0.0",
    "authentication": {
        "type":   "api_key",
        "header": "X-API-Key"
    },
    "triggers": [
        {
            "key":         "candidate_created",
            "name":        "New Candidate",
            "description": "Triggers when a new candidate is added",
            "url":         "/api/v1/candidates",
            "method":      "GET"
        },
        {
            "key":         "narrative_generated",
            "name":        "Narrative Generated",
            "description": "Triggers when an AI narrative is generated",
            "url":         "/api/narrative/insights",
            "method":      "GET"
        },
        {
            "key":         "sla_alert",
            "name":        "SLA Alert",
            "description": "Triggers when an SLA alert is created",
            "url":         "/api/sla/alerts",
            "method":      "GET"
        }
    ],
    "actions": [
        {
            "key":         "create_candidate",
            "name":        "Create Candidate",
            "description": "Add a candidate to AITMP",
            "url":         "/api/v1/candidates",
            "method":      "POST",
            "fields": [
                {"key": "name",        "label": "Candidate Name",  "required": True},
                {"key": "role",        "label": "Role",            "required": False},
                {"key": "linkedin_url","label": "LinkedIn URL",    "required": False},
                {"key": "notes",       "label": "Notes",           "required": False}
            ]
        },
        {
            "key":         "generate_narrative",
            "name":        "Generate Narrative",
            "description": "Generate an AI narrative for a candidate",
            "url":         "/api/v1/narratives/generate",
            "method":      "POST",
            "fields": [
                {"key": "candidate_id",   "label": "Candidate ID",    "required": True},
                {"key": "narrative_type", "label": "Narrative Type",  "required": False}
            ]
        },
        {
            "key":         "update_candidate",
            "name":        "Update Candidate",
            "description": "Update candidate notes or shortlist status",
            "url":         "/api/v1/candidates/{id}",
            "method":      "PATCH",
            "fields": [
                {"key": "id",          "label": "Candidate ID",    "required": True},
                {"key": "notes",       "label": "Notes",           "required": False},
                {"key": "shortlisted", "label": "Shortlisted",     "required": False}
            ]
        }
    ]
}


# ============================================================
# STEP 7 — MAKE.COM MODULE MANIFEST
# ============================================================

MAKECOM_MODULE_MANIFEST = {
    "name":        "AI Talent Match Pro",
    "description": "AI-powered recruiting intelligence for your ATS",
    "version":     "1.0.0",
    "modules": [
        {
            "name":         "Watch Candidates",
            "type":         "trigger",
            "description":  "Watch for new or updated candidates",
            "endpoint":     "/api/v1/candidates",
            "method":       "GET",
            "polling":      True,
            "poll_interval": 15
        },
        {
            "name":        "Generate Narrative",
            "type":        "action",
            "description": "Generate an AI narrative for a candidate",
            "endpoint":    "/api/v1/narratives/generate",
            "method":      "POST",
            "fields": [
                {"name": "candidate_id",   "type": "text",   "required": True},
                {"name": "narrative_type", "type": "select", "options": ["summary","strengths","risks","full"]}
            ]
        },
        {
            "name":        "Search Candidates",
            "type":        "search",
            "description": "Search for candidates by name or tier",
            "endpoint":    "/api/v1/candidates",
            "method":      "GET"
        },
        {
            "name":        "Create Candidate",
            "type":        "action",
            "description": "Add a candidate to AITMP",
            "endpoint":    "/api/v1/candidates",
            "method":      "POST",
            "fields": [
                {"name": "name",        "type": "text", "required": True},
                {"name": "role",        "type": "text"},
                {"name": "linkedin_url","type": "url"}
            ]
        }
    ],
    "webhooks": {
        "supported": True,
        "hmac_header": "X-AITMP-Signature",
        "events": [
            "candidate.created", "candidate.updated",
            "narrative.generated", "sla.alert.created"
        ]
    }
}


# ============================================================
# STEP 8 — RETRY FAILED SYNCS
# ============================================================

def retry_failed_syncs(db: Session, company_id: str) -> int:
    """
    Retry all failed partner syncs with exponential backoff.
    Returns count of retried syncs.
    """
    now = datetime.utcnow()
    failed = db.query(PartnerSyncLogORM).filter(
        PartnerSyncLogORM.company_id == company_id,
        PartnerSyncLogORM.status == "failed",
        PartnerSyncLogORM.attempt < 5,
        PartnerSyncLogORM.next_retry_at <= now
    ).all()

    retried = 0
    for log in failed:
        # Mark as retrying
        log.status = "retrying"
        log.attempt += 1
        backoff = 60 * (2 ** (log.attempt - 1))
        log.next_retry_at = now + timedelta(seconds=backoff)
        retried += 1

    try:
        db.commit()
    except Exception:
        db.rollback()

    return retried


# ============================================================
# INTERNAL — LOG SYNC EVENT
# ============================================================

def _log_sync(
    db: Session,
    company_id: str,
    partner: str,
    direction: str,
    event_type: str,
    payload: str = None,
    normalized: str = None,
    status: str = "success",
    error: str = None,
    latency_ms: float = None,
    candidate_id: str = None,
    external_id: str = None,
    attempt: int = 1
):
    """Log a partner sync event to PartnerSyncLogORM."""
    next_retry = None
    if status == "failed" and attempt < 5:
        backoff = 60 * (2 ** (attempt - 1))
        next_retry = datetime.utcnow() + timedelta(seconds=backoff)

    log = PartnerSyncLogORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        partner=partner,
        direction=direction,
        event_type=event_type,
        payload=payload,
        normalized=normalized,
        status=status,
        error=error,
        latency_ms=latency_ms,
        candidate_id=candidate_id,
        external_id=external_id,
        attempt=attempt,
        next_retry_at=next_retry
    )
    db.add(log)
    try:
        db.commit()
    except Exception:
        db.rollback()


# ============================================================
# HELPER — GET INTEGRATION STATUS
# ============================================================

def get_integration_status(db: Session, company_id: str) -> dict:
    """
    Get sync status summary for all partners.
    Powers the Integrations admin dashboard.
    """
    since = datetime.utcnow() - timedelta(days=7)

    logs = db.query(PartnerSyncLogORM).filter(
        PartnerSyncLogORM.company_id == company_id,
        PartnerSyncLogORM.created_at >= since
    ).all()

    summary = {}
    for partner in PARTNERS:
        partner_logs = [l for l in logs if l.partner == partner]
        total        = len(partner_logs)
        success      = sum(1 for l in partner_logs if l.status == "success")
        failed       = sum(1 for l in partner_logs if l.status == "failed")
        inbound      = sum(1 for l in partner_logs if l.direction == "inbound")
        outbound     = sum(1 for l in partner_logs if l.direction == "outbound")
        last_sync    = max((l.created_at for l in partner_logs), default=None)

        summary[partner] = {
            "total":     total,
            "success":   success,
            "failed":    failed,
            "inbound":   inbound,
            "outbound":  outbound,
            "success_rate": round(success / max(total, 1) * 100, 1),
            "last_sync": last_sync.isoformat() if last_sync else None,
            "status":    "connected" if total > 0 else "not_configured"
        }

    return summary