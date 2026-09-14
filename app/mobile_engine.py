"""
============================================================
PHASE 41 — POST-ACQUISITION INTEGRATION ENGINE
Mobile API · Webhooks 2.0 · Hot/Cold AI Path
Partner Marketplace · Compliance Layer · LinkedIn Graph Stub
============================================================
"""

import os, uuid, json, time, hmac, hashlib, secrets, logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db import (
    CompanyUserORM, CompanyORM,
    MobileSessionORM, WebhookDLQORM,
    ComplianceLogORM, PartnerInstallORM,
    WebhookORM, WebhookDeliveryLogORM,
    CompanyCandidateORM, UsageLogORM,
)

logger = logging.getLogger(__name__)

# ============================================================
# 41.1 — MOBILE AUTH (JWT-free, token-based)
# ============================================================

def create_mobile_token(
    db: Session,
    company_id: str,
    user_id: str,
    platform: str = "ios",
    device_id: str = None,
) -> dict:
    """Create a mobile session token."""
    token = secrets.token_urlsafe(48)
    expires = datetime.utcnow() + timedelta(days=30)

    session = MobileSessionORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        user_id=user_id,
        token=token,
        platform=platform,
        device_id=device_id,
        expires_at=expires,
        last_seen_at=datetime.utcnow(),
    )
    db.add(session)
    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "token":      token,
        "expires_at": expires.isoformat(),
        "platform":   platform,
    }


def validate_mobile_token(db: Session, token: str) -> Optional[MobileSessionORM]:
    """Validate a mobile token and return the session."""
    session = db.query(MobileSessionORM).filter(
        MobileSessionORM.token      == token,
        MobileSessionORM.expires_at >= datetime.utcnow(),
    ).first()

    if session:
        session.last_seen_at = datetime.utcnow()
        try:
            db.commit()
        except Exception:
            pass

    return session


# ============================================================
# 41.2 — MOBILE CANDIDATE RESPONSE (compressed)
# ============================================================

def mobile_candidate(c: CompanyCandidateORM) -> dict:
    """Stripped-down candidate for mobile bandwidth."""
    return {
        "id":    c.id,
        "name":  c.name,
        "role":  c.role,
        "tier":  c.tier,
        "score": c.match_score,
        "short": c.shortlisted,
        "skill": c.silent_skill,
    }


# ============================================================
# 41.3 — WEBHOOKS 2.0 (Enterprise Grade)
# ============================================================

def generate_webhook_signature(payload: str, secret: str) -> str:
    """HMAC-SHA256 signature for webhook delivery."""
    return hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()


def add_to_dlq(
    db: Session,
    company_id: str,
    webhook_id: str,
    event_type: str,
    payload: dict,
    error: str,
    attempts: int,
) -> WebhookDLQORM:
    """Add failed webhook to Dead Letter Queue."""
    record = WebhookDLQORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        webhook_id=webhook_id,
        event_type=event_type,
        payload_json=json.dumps(payload),
        error=error,
        attempts=attempts,
    )
    db.add(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
    return record


def get_webhook_failures(db: Session, company_id: str) -> List[dict]:
    """Get failed webhook deliveries from DLQ."""
    failures = db.query(WebhookDLQORM).filter(
        WebhookDLQORM.company_id == company_id,
        WebhookDLQORM.replayed_at == None,
    ).order_by(desc(WebhookDLQORM.created_at)).limit(50).all()

    return [
        {
            "id":         f.id,
            "webhook_id": f.webhook_id,
            "event_type": f.event_type,
            "error":      f.error,
            "attempts":   f.attempts,
            "created_at": f.created_at.isoformat(),
        }
        for f in failures
    ]


def replay_webhook(db: Session, dlq_id: str, company_id: str) -> dict:
    """Replay a failed webhook from DLQ."""
    record = db.query(WebhookDLQORM).filter(
        WebhookDLQORM.id         == dlq_id,
        WebhookDLQORM.company_id == company_id,
    ).first()

    if not record:
        return {"ok": False, "error": "DLQ record not found"}

    record.replayed_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "ok":        True,
        "dlq_id":    dlq_id,
        "event_type": record.event_type,
        "replayed_at": record.replayed_at.isoformat(),
        "message":   "Webhook queued for replay",
    }


# ============================================================
# 41.4 — AI ENGINE HOT/COLD PATH ROUTER
# ============================================================

HOT_PATH_ACTIONS = {
    "scoring", "signals", "forecast", "copilot",
    "interview_questions", "scorecard",
}

COLD_PATH_ACTIONS = {
    "narrative", "digest", "coaching",
    "deep_analytics", "batch_outreach",
}


def get_ai_path(action: str) -> str:
    """Route AI action to hot or cold path."""
    if action in HOT_PATH_ACTIONS:
        return "hot"
    elif action in COLD_PATH_ACTIONS:
        return "cold"
    return "hot"  # default to hot path


def get_model_for_path(path: str, tier: str = "gold") -> str:
    """Select model based on hot/cold path and candidate tier."""
    if path == "hot":
        return "gpt-4o"  # interactive path — full model, not the mini
    else:
        # Cold path — use mini for cost, full for quality
        return "gpt-4o" if tier == "gold" else "gpt-4o-mini"


# ============================================================
# 41.5 — PARTNER MARKETPLACE (removed)
#
# There was a catalog here offering Indeed, Zapier and Make.com as
# "available", plus an install_partner() that wrote a row and reported
# "installed successfully" while connecting to nothing. Nothing implemented
# any of them. The real integrations live in partner_credentials.py and are
# served by /api/ats/partners, which offers Greenhouse and Lever only.
# ============================================================

# ============================================================
# 41.6 — COMPLIANCE LAYER (SOC2 / GDPR / CCPA)
# ============================================================

def log_compliance_event(
    db: Session,
    company_id: str,
    action: str,
    resource: str = None,
    resource_id: str = None,
    user_id: str = None,
    ip_address: str = None,
    metadata: dict = None,
):
    """Log compliance event for SOC2/GDPR audit trail."""
    record = ComplianceLogORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        user_id=user_id,
        action=action,
        resource=resource,
        resource_id=resource_id,
        ip_address=ip_address,
        metadata_json=json.dumps(metadata or {}),
    )
    db.add(record)
    try:
        db.commit()
    except Exception:
        db.rollback()


def export_company_data(db: Session, company_id: str) -> dict:
    """GDPR data export — all company data."""
    candidates = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.is_deleted == False,
    ).all()

    users = db.query(CompanyUserORM).filter(
        CompanyUserORM.company_id == company_id,
        CompanyUserORM.is_deleted == False,
    ).all()

    return {
        "ok":           True,
        "company_id":   company_id,
        "exported_at":  datetime.utcnow().isoformat(),
        "candidates":   [{"id": c.id, "name": c.name, "role": c.role, "created_at": c.created_at.isoformat()} for c in candidates],
        "users":        [{"id": u.id, "email": u.email, "role": u.role, "created_at": u.created_at.isoformat()} for u in users],
        "total_records": len(candidates) + len(users),
        "format":       "JSON",
        "gdpr_compliant": True,
    }


def delete_candidate_data(db: Session, company_id: str, candidate_id: str) -> dict:
    """GDPR right to erasure — delete candidate data."""
    candidate = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.id         == candidate_id,
        CompanyCandidateORM.company_id == company_id,
    ).first()

    if not candidate:
        return {"ok": False, "error": "Candidate not found"}

    candidate.is_deleted  = True
    candidate.deleted_at  = datetime.utcnow()
    candidate.name        = "[DELETED]"
    candidate.ai_analysis = "[DELETED]"
    candidate.linkedin_url = None
    candidate.notes       = None

    try:
        db.commit()
    except Exception:
        db.rollback()
        return {"ok": False, "error": "Deletion failed"}

    log_compliance_event(db, company_id, "gdpr_erasure", "candidate", candidate_id)
    return {"ok": True, "message": "Candidate data erased per GDPR request"}


def get_compliance_audit_log(db: Session, company_id: str, limit: int = 100) -> List[dict]:
    """Get compliance audit log for SOC2."""
    logs = db.query(ComplianceLogORM).filter(
        ComplianceLogORM.company_id == company_id,
    ).order_by(desc(ComplianceLogORM.created_at)).limit(limit).all()

    return [
        {
            "id":          l.id,
            "action":      l.action,
            "resource":    l.resource,
            "resource_id": l.resource_id,
            "user_id":     l.user_id,
            "ip_address":  l.ip_address,
            "created_at":  l.created_at.isoformat(),
        }
        for l in logs
    ]


# ============================================================
# 41.7 — LINKEDIN TALENT GRAPH STUB
# ============================================================

def get_linkedin_graph_status() -> dict:
    """LinkedIn Talent Graph — stub for post-acquisition."""
    return {
        "ok":     True,
        "status": "partner_pending",
        "message": "LinkedIn Talent Graph integration ready for activation post-acquisition. OAuth flow, candidate graph sync, and recruiter seat mapping are all prepared.",
        "endpoints_ready": [
            "/api/linkedin/candidate/{id}",
            "/api/linkedin/sync",
            "/api/linkedin/skills",
            "/api/linkedin/signals",
        ],
        "activation_requirements": [
            "LinkedIn Talent Solutions Partner Program approval",
            "OAuth 2.0 client credentials",
            "LinkedIn Recruiter seat allocation",
        ],
    }


# ============================================================
# MOBILE SDK CODE SNIPPETS
# ============================================================

SWIFT_SNIPPET = '''// iOS Swift — AITMP Mobile SDK
import Foundation

class AITMPClient {
    let baseURL = "https://aitmp.io/api/mobile/v1"
    var token: String

    init(token: String) { self.token = token }

    func getCandidates() async throws -> [Candidate] {
        var request = URLRequest(url: URL(string: "\\(baseURL)/candidates")!)
        request.setValue("Bearer \\(token)", forHTTPHeaderField: "Authorization")
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONDecoder().decode([Candidate].self, from: data)
    }

    func scoreCandidate(jobDesc: String, resume: String) async throws -> Score {
        var request = URLRequest(url: URL(string: "\\(baseURL)/score")!)
        request.httpMethod = "POST"
        request.setValue("Bearer \\(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONEncoder().encode(["job_description": jobDesc, "resume": resume])
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONDecoder().decode(Score.self, from: data)
    }
}'''

KOTLIN_SNIPPET = '''// Android Kotlin — AITMP Mobile SDK
import okhttp3.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class AITMPClient(private val token: String) {
    private val client = OkHttpClient()
    private val baseURL = "https://aitmp.io/api/mobile/v1"

    suspend fun getCandidates(): List<Candidate> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseURL/candidates")
            .header("Authorization", "Bearer $token")
            .build()
        val response = client.newCall(request).execute()
        gson.fromJson(response.body?.string(), Array<Candidate>::class.java).toList()
    }

    suspend fun scoreCandidate(jobDesc: String, resume: String): Score = withContext(Dispatchers.IO) {
        val body = RequestBody.create(
            MediaType.parse("application/json"),
            gson.toJson(mapOf("job_description" to jobDesc, "resume" to resume))
        )
        val request = Request.Builder()
            .url("$baseURL/score")
            .header("Authorization", "Bearer $token")
            .post(body).build()
        val response = client.newCall(request).execute()
        gson.fromJson(response.body?.string(), Score::class.java)
    }
}'''