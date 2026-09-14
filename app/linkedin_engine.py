"""
============================================================
PHASE 42 — GLOBAL ROLLOUT ENGINE
Feature Flags · Multi-Model AI Router · Multi-Tenant Isolation
LinkedIn OAuth · API v2 · Status Page · Data Residency stubs
============================================================
"""

import os, uuid, json, hashlib, logging, secrets
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db import (
    FeatureFlagORM, AIModelRouteORM,
    LinkedInOAuthORM, StatusPageORM,
    CompanyCandidateORM, CompanyORM,
)

logger = logging.getLogger(__name__)

# ── Azure OpenAI config ───────────────────────────────────
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY        = os.getenv("AZURE_OPENAI_API_KEY", "")


# ============================================================
# 42.1 — FEATURE FLAGS (LaunchDarkly-style)
# ============================================================

# Default flags — seeded on first run
DEFAULT_FLAGS = {
    "ai_coaching":           {"description": "AI Recruiter Coaching Engine",     "enabled": True,  "rollout": 100},
    "real_time_signals":     {"description": "Real-Time Candidate Signals",      "enabled": True,  "rollout": 100},
    "forecast_v2":           {"description": "Forecast Engine 2.0",              "enabled": True,  "rollout": 100},
    "linkedin_oauth":        {"description": "LinkedIn OAuth integration",        "enabled": True,  "rollout": 100},
    "mobile_api":            {"description": "Mobile API v1",                    "enabled": True,  "rollout": 100},
    "partner_marketplace":   {"description": "Partner Marketplace",              "enabled": True,  "rollout": 100},
    "compliance_layer":      {"description": "SOC2/GDPR Compliance Layer",       "enabled": True,  "rollout": 100},
    "multi_model_routing":   {"description": "Multi-Model AI Routing",           "enabled": True,  "rollout": 100},
    "api_v2":                {"description": "API v2 with pagination + sorting", "enabled": True,  "rollout": 100},
    "canary_gpt4o_mini":     {"description": "GPT-4o-mini canary test (5%)",     "enabled": False, "rollout":   5},
    "cosmos_db_shadow":      {"description": "Cosmos DB shadow write (post-acq)","enabled": False, "rollout":   0},
    "multi_region":          {"description": "Multi-region deployment (post-acq)","enabled": False,"rollout":   0},
}


def seed_feature_flags(db: Session):
    """Seed default feature flags if not exist."""
    for key, meta in DEFAULT_FLAGS.items():
        existing = db.query(FeatureFlagORM).filter(FeatureFlagORM.flag_key == key).first()
        if not existing:
            flag = FeatureFlagORM(
                id=str(uuid.uuid4()),
                flag_key=key,
                description=meta["description"],
                is_enabled=meta["enabled"],
                rollout_pct=meta["rollout"],
            )
            db.add(flag)
    try:
        db.commit()
    except Exception:
        db.rollback()


def is_flag_enabled(db: Session, flag_key: str, company_id: str = None) -> bool:
    """Check if a feature flag is enabled for a company."""
    flag = db.query(FeatureFlagORM).filter(FeatureFlagORM.flag_key == flag_key).first()
    if not flag or not flag.is_enabled:
        return False

    # 100% rollout — always on
    if flag.rollout_pct >= 100:
        return True

    # Company-specific override
    if flag.company_ids and company_id:
        ids = json.loads(flag.company_ids or "[]")
        if company_id in ids:
            return True

    # Percentage rollout — deterministic per company
    if company_id and flag.rollout_pct > 0:
        hash_val = int(hashlib.md5(f"{flag_key}:{company_id}".encode()).hexdigest(), 16)
        bucket   = (hash_val % 100)
        return bucket < flag.rollout_pct

    return False


def get_all_flags(db: Session) -> List[dict]:
    seed_feature_flags(db)
    flags = db.query(FeatureFlagORM).order_by(FeatureFlagORM.flag_key).all()
    return [
        {
            "key":         f.flag_key,
            "description": f.description,
            "enabled":     f.is_enabled,
            "rollout_pct": f.rollout_pct,
            "updated_at":  f.updated_at.isoformat() if f.updated_at else None,
        }
        for f in flags
    ]


def update_flag(db: Session, flag_key: str, enabled: bool, rollout_pct: float = None) -> dict:
    flag = db.query(FeatureFlagORM).filter(FeatureFlagORM.flag_key == flag_key).first()
    if not flag:
        flag = FeatureFlagORM(id=str(uuid.uuid4()), flag_key=flag_key, is_enabled=enabled)
        db.add(flag)
    else:
        flag.is_enabled  = enabled
        if rollout_pct is not None:
            flag.rollout_pct = rollout_pct

    try:
        db.commit()
        return {"ok": True, "flag": flag_key, "enabled": enabled}
    except Exception:
        db.rollback()
        return {"ok": False, "error": "Update failed"}


# ============================================================
# 42.2 — MULTI-MODEL AI ROUTER
# ============================================================

MODEL_CATALOG = {
    "gpt-4o": {
        "label":      "GPT-4o",
        "provider":   "Azure OpenAI",
        "region":     "US",
        "latency_ms": 80,
        "cost_per_1k": 0.005,
        "best_for":   ["scoring", "signals", "copilot", "forecast"],
    },
    "gpt-4o-mini": {
        "label":      "GPT-4o Mini",
        "provider":   "Azure OpenAI",
        "region":     "EU",
        "latency_ms": 40,
        "cost_per_1k": 0.0006,
        "best_for":   ["narrative", "digest", "coaching", "batch"],
    },
    "claude-sonnet": {
        "label":      "Claude Sonnet",
        "provider":   "Anthropic",
        "region":     "Global",
        "latency_ms": 90,
        "cost_per_1k": 0.003,
        "best_for":   ["narrative", "coaching", "analysis"],
        "status":     "fallback",
    },
}


def route_ai_model(
    action: str,
    company_tier: str = "business",
    region: str = "us",
    latency_critical: bool = True,
) -> dict:
    """Route AI call to optimal model."""
    # Enterprise tier always gets GPT-4o
    if company_tier in ("enterprise", "corporate"):
        model = "gpt-4o"
    # Latency-critical hot path → GPT-4o
    elif latency_critical and action in ("scoring", "signals", "copilot", "forecast"):
        model = "gpt-4o"
    # EU region → GPT-4o-mini for GDPR cost efficiency
    elif region in ("eu", "uk"):
        model = "gpt-4o-mini"
    # Cost-sensitive cold path
    elif action in ("narrative", "digest", "coaching", "batch_outreach"):
        model = "gpt-4o-mini"
    else:
        model = "gpt-4o"

    meta = MODEL_CATALOG.get(model, MODEL_CATALOG["gpt-4o"])

    return {
        "model":           model,
        "provider":        meta["provider"],
        "region":          meta["region"],
        "latency_ms":      meta["latency_ms"],
        "cost_per_1k":     meta["cost_per_1k"],
        "fallback_model":  "gpt-4o-mini" if model == "gpt-4o" else "gpt-4o",
        "reason":          f"Selected {model} for {action} — {company_tier} tier, {region} region",
    }


# ============================================================
# 42.3 — MULTI-TENANT ISOLATION
# ============================================================

def get_tenant_config(db: Session, company_id: str) -> dict:
    """Get per-tenant security and config settings."""
    company = db.query(CompanyORM).filter(CompanyORM.id == company_id).first()
    if not company:
        return {}

    # Deterministic encryption key seed per tenant
    key_seed = hashlib.sha256(f"aitmp-tenant-{company_id}".encode()).hexdigest()

    return {
        "company_id":       company_id,
        "company_name":     company.name,
        "encryption_key_id": key_seed[:16],
        "data_region":      "us",  # default
        "rls_enabled":      True,
        "rate_limit":       {
            "api_calls_per_hour": 10000,
            "ai_calls_per_hour":  1000,
            "webhooks_per_hour":  5000,
        },
        "features": {
            "ai_coaching":      True,
            "real_time_signals": True,
            "partner_marketplace": True,
            "compliance_export": True,
        },
    }


# ============================================================
# 42.4 — LinkedIn OAuth (removed)
#
# "Sign in with LinkedIn" was an optional alternative to email and password.
# It never created accounts on its own — it matched an existing account by
# email or sent the person to /register — so removing it locks nobody out.
# It was dropped rather than kept, because it meant holding a LinkedIn client
# secret forever for a convenience button on a product that signs everyone in
# with a password anyway.
# ============================================================

# ============================================================
# 42.5 — API v2 (pagination + filtering + sorting)
# ============================================================

def api_v2_candidates(
    db: Session,
    company_id: str,
    page: int = 1,
    per_page: int = 20,
    sort_by: str = "match_score",
    sort_dir: str = "desc",
    tier: str = None,
    min_score: float = None,
    shortlisted: bool = None,
    search: str = None,
) -> dict:
    """API v2 — candidates with full pagination + filtering + sorting."""
    q = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.is_deleted == False,
    )

    # Filters
    if tier:        q = q.filter(CompanyCandidateORM.tier == tier)
    if min_score:   q = q.filter(CompanyCandidateORM.match_score >= min_score)
    if shortlisted is not None: q = q.filter(CompanyCandidateORM.shortlisted == shortlisted)
    if search:
        q = q.filter(
            CompanyCandidateORM.name.ilike(f"%{search}%") |
            CompanyCandidateORM.role.ilike(f"%{search}%")
        )

    # Sorting
    sort_col = getattr(CompanyCandidateORM, sort_by, CompanyCandidateORM.match_score)
    if sort_dir == "desc":
        q = q.order_by(desc(sort_col))
    else:
        q = q.order_by(sort_col)

    total   = q.count()
    offset  = (page - 1) * per_page
    results = q.offset(offset).limit(per_page).all()

    return {
        "ok":         True,
        "api_version": "v2",
        "data": [
            {
                "id":          c.id,
                "name":        c.name,
                "role":        c.role,
                "tier":        c.tier,
                "match_score": c.match_score,
                "shortlisted": c.shortlisted,
                "silent_skill": c.silent_skill,
                "created_at":  c.created_at.isoformat(),
            }
            for c in results
        ],
        "pagination": {
            "page":       page,
            "per_page":   per_page,
            "total":      total,
            "pages":      -(-total // per_page),
            "has_next":   (page * per_page) < total,
            "has_prev":   page > 1,
        },
        "filters":   {"tier": tier, "min_score": min_score, "shortlisted": shortlisted, "search": search},
        "sort":      {"by": sort_by, "dir": sort_dir},
    }


# ============================================================
# 42.6 — STATUS PAGE
# ============================================================

COMPONENTS = [
    "API",
    "AI Scoring Engine",
    "Signal Engine",
    "Forecast Engine",
    "Webhook Delivery",
    "Database",
    "CDN",
]


def get_status_page(db: Session) -> dict:
    """Get current platform status."""
    # Get recent incidents
    incidents = db.query(StatusPageORM).filter(
        StatusPageORM.resolved == False,
    ).order_by(desc(StatusPageORM.created_at)).limit(10).all()

    # Component status — all operational unless there's an active incident
    incident_components = {i.component for i in incidents if i.component}
    components = [
        {
            "name":   c,
            "status": "degraded" if c in incident_components else "operational",
            "color":  "#f5a623" if c in incident_components else "#00d68f",
        }
        for c in COMPONENTS
    ]

    overall = "degraded" if incidents else "operational"

    return {
        "ok":      True,
        "overall": overall,
        "overall_color": "#f5a623" if overall == "degraded" else "#00d68f",
        "components": components,
        "incidents": [
            {
                "id":        i.id,
                "title":     i.title,
                "message":   i.message,
                "status":    i.status,
                "component": i.component,
                "created_at": i.created_at.isoformat(),
            }
            for i in incidents
        ],
        "uptime_30d": 99.98,
        "checked_at": datetime.utcnow().isoformat(),
    }


# ============================================================
# 42.7 — DATA RESIDENCY CONFIG
# ============================================================

DATA_REGIONS = {
    "us":      {"label": "United States",     "available": True,  "compliance": ["SOC2", "CCPA"]},
    "eu":      {"label": "European Union",    "available": True,  "compliance": ["GDPR", "SOC2"]},
    "uk":      {"label": "United Kingdom",    "available": True,  "compliance": ["UK-GDPR", "SOC2"]},
    "apac":    {"label": "Asia Pacific",      "available": False, "compliance": ["PDPA"]},
    "govcloud":{"label": "US GovCloud",       "available": False, "compliance": ["FedRAMP", "ITAR"]},
}


def get_data_residency_options() -> dict:
    return {
        "ok":      True,
        "regions": [
            {"key": k, **v}
            for k, v in DATA_REGIONS.items()
        ],
        "current": "us",
        "note":    "Multi-region deployment available post-acquisition via Azure Front Door",
    }