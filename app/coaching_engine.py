"""
============================================================
PHASE 39 — AI RECRUITER COACHING ENGINE
Watches recruiter behavior and generates real-time coaching.
Feeds into: Copilot (33), Alerts (34), Digest (34),
            Analytics (34), Narrative (36), Signals (38)
============================================================
"""

import uuid, json, logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.db import (
    RecruiterCoachingEventORM,
    CompanyUserORM,
    CompanyCandidateORM,
    OutreachORM,
    RecruiterCopilotORM,
    CandidateSignalORM,
    IntelligenceAlertORM,
    UsageLogORM,
)

logger = logging.getLogger(__name__)

# ── Coaching type definitions ─────────────────────────────
COACHING_TYPES = {
    "timing":            {"icon": "⏰", "label": "Timing Issue"},
    "tone":              {"icon": "🎯", "label": "Tone/Style"},
    "prioritization":    {"icon": "📋", "label": "Prioritization"},
    "risk":              {"icon": "🚨", "label": "Risk Alert"},
    "opportunity":       {"icon": "💡", "label": "Opportunity"},
    "outreach_quality":  {"icon": "✍️",  "label": "Outreach Quality"},
    "follow_up":         {"icon": "🔔", "label": "Follow-Up"},
    "signal_response":   {"icon": "📡", "label": "Signal Response"},
    "pipeline":          {"icon": "🔻", "label": "Pipeline"},
    "forecast":          {"icon": "📈", "label": "Forecast"},
}

SEVERITY_COLORS = {
    "info":       "#4d9fff",
    "suggestion": "#a78bfa",
    "warning":    "#f5a623",
    "critical":   "#ff4d6d",
}


# ============================================================
# 39.1 — ANALYZE RECRUITER BEHAVIOR
# ============================================================

def analyze_recruiter_behavior(db: Session, company_id: str, user_id: str) -> List[dict]:
    """Run all coaching checks for a recruiter and return events."""
    events = []

    events += detect_slow_followups(db, company_id, user_id)
    events += detect_bad_outreach_patterns(db, company_id, user_id)
    events += detect_missed_opportunities(db, company_id, user_id)
    events += detect_signal_ignores(db, company_id, user_id)
    events += detect_pipeline_issues(db, company_id, user_id)

    # Store all events
    for event in events:
        store_coaching_event(
            db=db,
            company_id=company_id,
            user_id=user_id,
            coaching_type=event["coaching_type"],
            message=event["message"],
            severity=event["severity"],
            metadata=event.get("metadata", {}),
        )

    return events


# ============================================================
# 39.2 — DETECT SLOW FOLLOW-UPS
# ============================================================

def detect_slow_followups(db: Session, company_id: str, user_id: str) -> List[dict]:
    """Detect outreach sent with no follow-up after 48h."""
    events = []
    cutoff = datetime.utcnow() - timedelta(hours=48)

    try:
        old_outreach = db.query(OutreachORM).filter(
            OutreachORM.company_id  == company_id,
            OutreachORM.created_by  == user_id,
            OutreachORM.sent        == True,
            OutreachORM.responded   == False,
            OutreachORM.created_at  <= cutoff,
        ).limit(5).all()

        if len(old_outreach) >= 3:
            events.append({
                "coaching_type": "follow_up",
                "message": f"You have {len(old_outreach)} messages with no response in 48+ hours. A well-timed follow-up increases response rates by 15-25%. Send follow-ups today.",
                "severity": "warning",
                "metadata": {"unanswered_count": len(old_outreach)},
            })
    except Exception as e:
        logger.error(f"detect_slow_followups: {e}")

    return events


# ============================================================
# 39.3 — DETECT BAD OUTREACH PATTERNS
# ============================================================

def detect_bad_outreach_patterns(db: Session, company_id: str, user_id: str) -> List[dict]:
    """Detect low quality or single-channel outreach."""
    events = []

    try:
        messages = db.query(OutreachORM).filter(
            OutreachORM.company_id == company_id,
            OutreachORM.created_by == user_id,
            OutreachORM.is_deleted == False,
        ).all()

        if not messages:
            return events

        sent   = [m for m in messages if m.sent]
        replied = [m for m in messages if m.responded]

        if len(sent) >= 5:
            response_rate = len(replied) / len(sent)
            if response_rate < 0.20:
                events.append({
                    "coaching_type": "outreach_quality",
                    "message": f"Your response rate is {round(response_rate*100)}% — below the 34% benchmark. Try more personalized LinkedIn InMail with candidate-specific references to their recent work.",
                    "severity": "warning",
                    "metadata": {"response_rate": round(response_rate, 2)},
                })

        # Channel diversity check
        channels = [m.channel for m in messages if m.channel]
        if channels:
            channel_counts = {}
            for c in channels:
                channel_counts[c] = channel_counts.get(c, 0) + 1
            dominant = max(channel_counts, key=channel_counts.get)
            if channel_counts[dominant] / len(channels) > 0.85:
                events.append({
                    "coaching_type": "tone",
                    "message": f"85%+ of your outreach uses {dominant} only. Diversify channels — LinkedIn InMail outperforms connection requests for senior roles by 2x.",
                    "severity": "suggestion",
                    "metadata": {"dominant_channel": dominant},
                })

    except Exception as e:
        logger.error(f"detect_bad_outreach_patterns: {e}")

    return events


# ============================================================
# 39.4 — DETECT MISSED OPPORTUNITIES
# ============================================================

def detect_missed_opportunities(db: Session, company_id: str, user_id: str) -> List[dict]:
    """Detect gold candidates with no outreach."""
    events = []

    try:
        gold_no_outreach = db.query(CompanyCandidateORM).filter(
            CompanyCandidateORM.company_id == company_id,
            CompanyCandidateORM.tier       == "gold",
            CompanyCandidateORM.shortlisted == False,
            CompanyCandidateORM.is_deleted == False,
        ).limit(10).all()

        contacted_ids = set(
            o.candidate_id for o in db.query(OutreachORM).filter(
                OutreachORM.company_id == company_id,
                OutreachORM.created_by == user_id,
            ).all()
        )

        uncontacted_gold = [c for c in gold_no_outreach if c.id not in contacted_ids]

        if len(uncontacted_gold) >= 2:
            names = ", ".join(c.name for c in uncontacted_gold[:3])
            events.append({
                "coaching_type": "opportunity",
                "message": f"You have {len(uncontacted_gold)} Gold tier candidates with no outreach yet: {names}. These are your highest-probability hires — contact them first.",
                "severity": "suggestion",
                "metadata": {"uncontacted_count": len(uncontacted_gold)},
            })
    except Exception as e:
        logger.error(f"detect_missed_opportunities: {e}")

    return events


# ============================================================
# 39.5 — DETECT SIGNAL IGNORES
# ============================================================

def detect_signal_ignores(db: Session, company_id: str, user_id: str) -> List[dict]:
    """Detect high-priority signals that were ignored."""
    events = []

    try:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        high_signals = db.query(CandidateSignalORM).filter(
            CandidateSignalORM.company_id  == company_id,
            CandidateSignalORM.signal_type.in_(["open_to_work", "interest_spike", "recruiter_message_replied"]),
            CandidateSignalORM.created_at  >= cutoff,
            CandidateSignalORM.is_read     == False,
        ).all()

        if len(high_signals) >= 2:
            events.append({
                "coaching_type": "signal_response",
                "message": f"{len(high_signals)} high-priority candidate signals are unread — including 'Open to Work' and 'Interest Spike' alerts. Act within 2 hours for best results.",
                "severity": "warning",
                "metadata": {"unread_signals": len(high_signals)},
            })
    except Exception as e:
        logger.error(f"detect_signal_ignores: {e}")

    return events


# ============================================================
# 39.6 — DETECT PIPELINE ISSUES
# ============================================================

def detect_pipeline_issues(db: Session, company_id: str, user_id: str) -> List[dict]:
    """Detect candidates stuck in pipeline stages."""
    events = []

    try:
        total = db.query(CompanyCandidateORM).filter(
            CompanyCandidateORM.company_id == company_id,
            CompanyCandidateORM.is_deleted == False,
        ).count()

        shortlisted = db.query(CompanyCandidateORM).filter(
            CompanyCandidateORM.company_id == company_id,
            CompanyCandidateORM.shortlisted == True,
            CompanyCandidateORM.is_deleted == False,
        ).count()

        if total > 0 and shortlisted / total < 0.10:
            events.append({
                "coaching_type": "pipeline",
                "message": f"Only {round(shortlisted/total*100)}% of candidates are shortlisted — well below the 25% target. Review your top gold candidates and shortlist the best fits today.",
                "severity": "suggestion",
                "metadata": {"shortlist_rate": round(shortlisted/total, 2)},
            })
    except Exception as e:
        logger.error(f"detect_pipeline_issues: {e}")

    return events


# ============================================================
# 39.7 — STORE COACHING EVENT
# ============================================================

def store_coaching_event(
    db: Session,
    company_id: str,
    user_id: str,
    coaching_type: str,
    message: str,
    severity: str = "suggestion",
    metadata: dict = None,
    candidate_id: str = None,
) -> RecruiterCoachingEventORM:
    event = RecruiterCoachingEventORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        user_id=user_id,
        candidate_id=candidate_id,
        coaching_type=coaching_type,
        message=message,
        severity=severity,
        metadata_json=json.dumps(metadata or {}),
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
    except Exception:
        db.rollback()
    return event


# ============================================================
# 39.8 — GET COACHING EVENTS
# ============================================================

def get_recent_coaching(db: Session, company_id: str, user_id: str = None, limit: int = 50) -> List[dict]:
    q = db.query(RecruiterCoachingEventORM).filter(
        RecruiterCoachingEventORM.company_id == company_id,
    )
    if user_id:
        q = q.filter(RecruiterCoachingEventORM.user_id == user_id)

    events = q.order_by(desc(RecruiterCoachingEventORM.created_at)).limit(limit).all()
    return [_format_event(e) for e in events]


def _format_event(e: RecruiterCoachingEventORM) -> dict:
    info = COACHING_TYPES.get(e.coaching_type, {"icon": "💡", "label": e.coaching_type})
    return {
        "id":            e.id,
        "user_id":       e.user_id,
        "coaching_type": e.coaching_type,
        "icon":          info["icon"],
        "label":         info["label"],
        "message":       e.message,
        "severity":      e.severity,
        "severity_color": SEVERITY_COLORS.get(e.severity, "#8ba4c0"),
        "is_read":       e.is_read,
        "is_applied":    e.is_applied,
        "created_at":    e.created_at.isoformat(),
        "time_ago":      _time_ago(e.created_at),
    }


def _time_ago(dt: datetime) -> str:
    diff = datetime.utcnow() - dt
    if diff.seconds < 60: return "just now"
    elif diff.seconds < 3600: return f"{diff.seconds // 60}m ago"
    elif diff.days == 0: return f"{diff.seconds // 3600}h ago"
    elif diff.days == 1: return "yesterday"
    else: return f"{diff.days}d ago"


# ============================================================
# 39.9 — COACHING SCORE
# ============================================================

def score_recruiter_coaching(db: Session, company_id: str, user_id: str) -> dict:
    """Compute overall coaching score 0-100."""
    scores = {}

    # Follow-up discipline
    try:
        sent = db.query(OutreachORM).filter(OutreachORM.company_id==company_id, OutreachORM.created_by==user_id, OutreachORM.sent==True).count()
        replied = db.query(OutreachORM).filter(OutreachORM.company_id==company_id, OutreachORM.created_by==user_id, OutreachORM.responded==True).count()
        scores["outreach_quality"] = min(100, round((replied / max(sent, 1)) * 200))
    except: scores["outreach_quality"] = 50

    # Signal responsiveness
    try:
        total_signals = db.query(CandidateSignalORM).filter(CandidateSignalORM.company_id==company_id).count()
        read_signals  = db.query(CandidateSignalORM).filter(CandidateSignalORM.company_id==company_id, CandidateSignalORM.is_read==True).count()
        scores["signal_responsiveness"] = min(100, round((read_signals / max(total_signals, 1)) * 100))
    except: scores["signal_responsiveness"] = 50

    # Pipeline management
    try:
        total = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id, CompanyCandidateORM.is_deleted==False).count()
        shortlisted = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id, CompanyCandidateORM.shortlisted==True, CompanyCandidateORM.is_deleted==False).count()
        scores["pipeline_management"] = min(100, round((shortlisted / max(total, 1)) * 300))
    except: scores["pipeline_management"] = 50

    # Copilot usage
    try:
        copilot_count = db.query(RecruiterCopilotORM).filter(RecruiterCopilotORM.company_id==company_id, RecruiterCopilotORM.user_id==user_id).count()
        scores["copilot_usage"] = min(100, copilot_count * 10)
    except: scores["copilot_usage"] = 0

    overall = round(sum(scores.values()) / max(len(scores), 1), 1)

    return {
        "ok":      True,
        "overall": overall,
        "scores":  scores,
        "grade":   "A" if overall >= 80 else "B" if overall >= 65 else "C" if overall >= 50 else "D",
    }


# ============================================================
# 39.10 — SSO ENGINE (Enterprise)
# ============================================================

def get_sso_login_url(tenant_id: str, client_id: str, redirect_uri: str) -> str:
    """Generate Azure AD OAuth URL."""
    return (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&scope=openid+email+profile"
        f"&response_mode=query"
    )


def get_sso_providers() -> List[dict]:
    return [
        {"key": "azure_ad",  "label": "Microsoft Azure AD",  "icon": "🔷", "color": "#0078d4"},
        {"key": "google",    "label": "Google Workspace",    "icon": "🔴", "color": "#4285f4"},
        {"key": "okta",      "label": "Okta",                "icon": "🔵", "color": "#007dc1"},
    ]