"""
============================================================
PHASE 38 — REAL-TIME CANDIDATE SIGNALS ENGINE
Ingests, scores, and broadcasts candidate signals.
Feeds into: Alerts (34), Forecast (37), Narrative (36),
            Digest (34), Recruiter OS (33), Copilot (33)
============================================================
"""

import uuid, json, time, logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db import (
    CandidateSignalORM,
    CompanyCandidateORM,
    IntelligenceAlertORM,
    UsageLogORM,
)

logger = logging.getLogger(__name__)

# ── Signal type metadata ──────────────────────────────────
SIGNAL_TYPES = {
    "viewed_profile":            {"label": "Viewed Your Profile",     "icon": "🎯", "badge_color": "#4d9fff",  "base_confidence": 0.7},
    "updated_experience":        {"label": "Updated Experience",       "icon": "📝", "badge_color": "#a78bfa",  "base_confidence": 0.85},
    "new_skill":                 {"label": "New Skill Added",          "icon": "🆕", "badge_color": "#00d68f",  "base_confidence": 0.90},
    "job_change":                {"label": "Changed Jobs",             "icon": "⚠",  "badge_color": "#ff4d6d",  "base_confidence": 0.95},
    "open_to_work":              {"label": "Open to Work",             "icon": "🟢", "badge_color": "#00d68f",  "base_confidence": 0.99},
    "recruiter_message_seen":    {"label": "Saw Your Message",         "icon": "👁",  "badge_color": "#f5a623",  "base_confidence": 0.80},
    "recruiter_message_replied": {"label": "Replied to Outreach",      "icon": "💬", "badge_color": "#00d68f",  "base_confidence": 1.00},
    "interest_spike":            {"label": "Interest Spike Detected",  "icon": "🔥", "badge_color": "#f5a623",  "base_confidence": 0.75},
    "risk_signal":               {"label": "Risk Signal Detected",     "icon": "🚨", "badge_color": "#ff4d6d",  "base_confidence": 0.70},
    "profile_update":            {"label": "Profile Updated",          "icon": "🔄", "badge_color": "#4d9fff",  "base_confidence": 0.80},
}


# ============================================================
# 38.1 — INGEST SIGNAL
# ============================================================

def ingest_signal(
    db: Session,
    company_id: str,
    candidate_id: str,
    signal_type: str,
    metadata: dict = None,
    job_id: str = None,
) -> CandidateSignalORM:
    """Ingest a new candidate signal and trigger downstream effects."""

    if signal_type not in SIGNAL_TYPES:
        signal_type = "profile_update"

    confidence = calculate_signal_confidence(signal_type, metadata or {})

    signal = CandidateSignalORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        candidate_id=candidate_id,
        job_id=job_id,
        signal_type=signal_type,
        metadata_json=json.dumps(metadata or {}),
        confidence_score=confidence,
    )
    db.add(signal)

    # Update candidate relevance
    update_candidate_relevance(db, candidate_id, signal_type)

    # Trigger alert for high-priority signals
    if signal_type in ("job_change", "open_to_work", "recruiter_message_replied", "interest_spike"):
        _create_signal_alert(db, company_id, candidate_id, signal_type, confidence)

    # Usage log
    try:
        log = UsageLogORM(
            company_id=company_id,
            user_id="system",
            action=f"signal_{signal_type}",
            details=json.dumps({"candidate_id": candidate_id}),
        )
        db.add(log)
    except Exception:
        pass

    try:
        db.commit()
        db.refresh(signal)
    except Exception:
        db.rollback()

    return signal


# ============================================================
# 38.2 — CALCULATE SIGNAL CONFIDENCE
# ============================================================

def calculate_signal_confidence(signal_type: str, metadata: dict) -> float:
    """Score signal confidence 0-1 based on type and metadata."""
    base = SIGNAL_TYPES.get(signal_type, {}).get("base_confidence", 0.75)

    # Boost confidence if metadata is rich
    if metadata:
        if metadata.get("source") == "linkedin":
            base = min(1.0, base + 0.05)
        if metadata.get("verified"):
            base = min(1.0, base + 0.10)
        if metadata.get("timestamp"):
            base = min(1.0, base + 0.03)

    return round(base, 2)


# ============================================================
# 38.3 — UPDATE CANDIDATE RELEVANCE
# ============================================================

def update_candidate_relevance(db: Session, candidate_id: str, signal_type: str):
    """Update candidate match score based on positive/negative signals."""
    try:
        candidate = db.query(CompanyCandidateORM).filter(
            CompanyCandidateORM.id == candidate_id,
            CompanyCandidateORM.is_deleted == False,
        ).first()

        if not candidate:
            return

        current_score = candidate.match_score or 0

        # Signal impact on match score
        score_delta = {
            "open_to_work":              +3.0,
            "recruiter_message_replied": +2.0,
            "new_skill":                 +1.5,
            "interest_spike":            +1.0,
            "viewed_profile":            +0.5,
            "updated_experience":        +1.0,
            "profile_update":            +0.5,
            "job_change":                -2.0,
            "risk_signal":               -1.5,
            "recruiter_message_seen":    +0.0,
        }.get(signal_type, 0.0)

        if score_delta != 0:
            new_score = max(0, min(100, current_score + score_delta))
            candidate.match_score = round(new_score, 1)

    except Exception as e:
        logger.error(f"update_candidate_relevance error: {e}")


# ============================================================
# 38.4 — GET RECENT SIGNALS
# ============================================================

def get_recent_signals(db: Session, company_id: str, limit: int = 50) -> List[dict]:
    signals = db.query(CandidateSignalORM).filter(
        CandidateSignalORM.company_id == company_id,
    ).order_by(desc(CandidateSignalORM.created_at)).limit(limit).all()

    return [_format_signal(s) for s in signals]


def get_candidate_signals(db: Session, company_id: str, candidate_id: str) -> List[dict]:
    signals = db.query(CandidateSignalORM).filter(
        CandidateSignalORM.company_id   == company_id,
        CandidateSignalORM.candidate_id == candidate_id,
    ).order_by(desc(CandidateSignalORM.created_at)).all()

    return [_format_signal(s) for s in signals]


def _format_signal(s: CandidateSignalORM) -> dict:
    meta = json.loads(s.metadata_json or "{}")
    info = SIGNAL_TYPES.get(s.signal_type, {"label": s.signal_type, "icon": "📡", "badge_color": "#8ba4c0"})
    return {
        "id":               s.id,
        "candidate_id":     s.candidate_id,
        "signal_type":      s.signal_type,
        "label":            info["label"],
        "icon":             info["icon"],
        "badge_color":      info["badge_color"],
        "confidence_score": s.confidence_score,
        "metadata":         meta,
        "is_read":          s.is_read,
        "created_at":       s.created_at.isoformat(),
        "time_ago":         _time_ago(s.created_at),
    }


def _time_ago(dt: datetime) -> str:
    diff = datetime.utcnow() - dt
    if diff.seconds < 60:
        return "just now"
    elif diff.seconds < 3600:
        return f"{diff.seconds // 60}m ago"
    elif diff.days == 0:
        return f"{diff.seconds // 3600}h ago"
    elif diff.days == 1:
        return "yesterday"
    else:
        return f"{diff.days}d ago"


# ============================================================
# 38.5 — SIGNAL SUMMARY (Intelligence Layer)
# ============================================================

def get_signal_summary(db: Session, company_id: str) -> dict:
    """Aggregated signal intelligence — trending, rising, risk."""
    since = datetime.utcnow() - timedelta(hours=24)

    signals = db.query(CandidateSignalORM).filter(
        CandidateSignalORM.company_id  == company_id,
        CandidateSignalORM.created_at  >= since,
    ).all()

    # Group by candidate
    by_candidate = {}
    for s in signals:
        cid = s.candidate_id
        if cid not in by_candidate:
            by_candidate[cid] = []
        by_candidate[cid].append(s)

    # Interest spikes — candidates with 3+ positive signals
    positive_types = {"open_to_work", "recruiter_message_replied", "new_skill", "interest_spike", "viewed_profile"}
    interest_spikes = [
        cid for cid, sigs in by_candidate.items()
        if sum(1 for s in sigs if s.signal_type in positive_types) >= 2
    ]

    # Risk signals
    risk_types = {"job_change", "risk_signal"}
    risk_candidates = [
        cid for cid, sigs in by_candidate.items()
        if any(s.signal_type in risk_types for s in sigs)
    ]

    # Skill updates
    skill_updates = [
        cid for cid, sigs in by_candidate.items()
        if any(s.signal_type == "new_skill" for s in sigs)
    ]

    # Job changes
    job_changes = [
        cid for cid, sigs in by_candidate.items()
        if any(s.signal_type == "job_change" for s in sigs)
    ]

    # Open to work
    open_to_work = [
        cid for cid, sigs in by_candidate.items()
        if any(s.signal_type == "open_to_work" for s in sigs)
    ]

    return {
        "ok":              True,
        "total_signals":   len(signals),
        "active_candidates": len(by_candidate),
        "interest_spikes": interest_spikes,
        "risk_signals":    risk_candidates,
        "skill_updates":   skill_updates,
        "job_changes":     job_changes,
        "open_to_work":    open_to_work,
        "signal_volume":   len(signals),
        "period":          "last_24h",
    }


# ============================================================
# 38.6 — MARK SIGNALS AS READ
# ============================================================

def mark_signals_read(db: Session, company_id: str, signal_ids: List[str] = None):
    """Mark signals as read."""
    q = db.query(CandidateSignalORM).filter(
        CandidateSignalORM.company_id == company_id,
        CandidateSignalORM.is_read    == False,
    )
    if signal_ids:
        q = q.filter(CandidateSignalORM.id.in_(signal_ids))

    q.update({"is_read": True}, synchronize_session=False)
    try:
        db.commit()
    except Exception:
        db.rollback()


# ============================================================
# 38.7 — SIMULATE SIGNALS (for demo)
# ============================================================

def simulate_demo_signals(db: Session, company_id: str) -> int:
    """Generate realistic demo signals for all candidates."""
    import random

    candidates = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.is_deleted == False,
    ).limit(10).all()

    if not candidates:
        return 0

    signal_pool = [
        "viewed_profile", "updated_experience", "new_skill",
        "open_to_work", "recruiter_message_seen", "interest_spike",
        "profile_update",
    ]

    count = 0
    for c in candidates[:5]:
        signal_type = random.choice(signal_pool)
        ingest_signal(
            db=db,
            company_id=company_id,
            candidate_id=c.id,
            signal_type=signal_type,
            metadata={"source": "demo", "simulated": True},
        )
        count += 1

    return count


# ============================================================
# HELPERS
# ============================================================

def _create_signal_alert(db, company_id, candidate_id, signal_type, confidence):
    """Create an intelligence alert from a high-priority signal."""
    try:
        info = SIGNAL_TYPES.get(signal_type, {})
        severity_map = {
            "job_change":                "high",
            "open_to_work":              "medium",
            "recruiter_message_replied": "medium",
            "interest_spike":            "medium",
        }
        alert = IntelligenceAlertORM(
            id=str(uuid.uuid4()),
            company_id=company_id,
            alert_type=f"signal_{signal_type}",
            message=f"{info.get('icon','')} {info.get('label','Signal')}: candidate activity detected (confidence: {round(confidence*100)}%)",
            severity=severity_map.get(signal_type, "low"),
        )
        db.add(alert)
    except Exception as e:
        logger.error(f"_create_signal_alert error: {e}")


def get_signal_types():
    return [
        {"key": k, "label": v["label"], "icon": v["icon"], "badge_color": v["badge_color"]}
        for k, v in SIGNAL_TYPES.items()
    ]