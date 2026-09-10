# ============================================================
# app/recruiter_analytics_engine.py
# AI Talent Match Pro — Phase 26 Recruiter Behavior Analytics
# Behavioral intelligence layer for each recruiter
# ============================================================

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid
import math

from app.db import (
    CompanyUserORM, FeedbackEventORM,
    CompanyCandidateORM, RecruiterAnalyticsORM,
    SLAAlertORM
)

# ============================================================
# CONSTANTS
# ============================================================
LOOKBACK_DAYS          = 30
MIN_DECISIONS_FOR_FULL = 5     # min decisions for full metrics
HIGH_SKIP_RATE         = 0.70  # alert threshold
LOW_DIVERSITY_SCORE    = 0.30  # alert threshold
SLOW_DECISION_SECS     = 300   # 5 minutes = slow decision


# ============================================================
# MAIN AGGREGATION JOB
# Loops through all recruiters and computes behavior metrics
# ============================================================

def run_recruiter_analytics(db: Session, company_id: str) -> int:
    """
    Run the recruiter behavior analytics job.
    Computes metrics for all recruiters in a company.
    Writes RecruiterAnalyticsORM rows.

    Returns: number of recruiters processed
    """
    since  = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
    period = datetime.utcnow().strftime("%Y-%m")

    # Step 1 — Get all active recruiters
    recruiters = db.query(CompanyUserORM).filter(
        CompanyUserORM.company_id == company_id,
        CompanyUserORM.is_active == True,
        CompanyUserORM.is_deleted == False
    ).all()

    processed = 0

    for recruiter in recruiters:
        try:
            _compute_recruiter_metrics(db, company_id, recruiter, period, since)
            processed += 1
        except Exception:
            continue

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return processed


# ============================================================
# PER-RECRUITER METRIC COMPUTATION
# ============================================================

def _compute_recruiter_metrics(
    db: Session,
    company_id: str,
    recruiter: CompanyUserORM,
    period: str,
    since: datetime
):
    """
    Compute all behavioral metrics for a single recruiter.
    Writes or updates RecruiterAnalyticsORM row.
    """
    user_id = recruiter.id

    # Get all feedback events for this recruiter
    events = db.query(FeedbackEventORM).filter(
        FeedbackEventORM.company_id == company_id,
        FeedbackEventORM.user_id == user_id,
        FeedbackEventORM.created_at >= since,
        FeedbackEventORM.is_deleted == False
    ).order_by(FeedbackEventORM.created_at.asc()).all()

    # Step 1 — Basic counts
    total_decisions  = len(events)
    shortlist_count  = sum(1 for e in events if e.action == "shortlist")
    skip_count       = sum(1 for e in events if e.action == "skip")
    hire_count       = sum(1 for e in events if e.action == "hire")
    positive_signals = shortlist_count + hire_count
    negative_signals = skip_count

    # Step 3 — Decision speed
    avg_time_to_decision_s, decisions_per_day = _compute_decision_speed(
        events, since
    )

    # Step 4 — Score preferences
    avg_score_shortlisted, avg_score_skipped, gold_preference_rate = \
        _compute_score_preferences(db, company_id, events)

    # Step 5 — Tier diversity score
    tier_diversity_score = _compute_tier_diversity(db, company_id, user_id, since)

    # Get or create analytics row
    rec = db.query(RecruiterAnalyticsORM).filter(
        RecruiterAnalyticsORM.company_id == company_id,
        RecruiterAnalyticsORM.user_id == user_id,
        RecruiterAnalyticsORM.period == period
    ).first()

    if not rec:
        rec = RecruiterAnalyticsORM(
            id=str(uuid.uuid4()),
            company_id=company_id,
            user_id=user_id,
            user_name=recruiter.name,
            period=period
        )
        db.add(rec)

    # Step 6 — Write all metrics
    rec.total_decisions        = total_decisions
    rec.positive_signals       = positive_signals
    rec.negative_signals       = negative_signals
    rec.hire_count             = hire_count
    rec.shortlist_count        = shortlist_count
    rec.skip_count             = skip_count
    rec.avg_time_to_decision_s = avg_time_to_decision_s
    rec.decisions_per_day      = decisions_per_day
    rec.avg_score_shortlisted  = avg_score_shortlisted
    rec.avg_score_skipped      = avg_score_skipped
    rec.gold_preference_rate   = gold_preference_rate
    rec.tier_diversity_score   = tier_diversity_score

    # Step 9 — Check for alerts
    if total_decisions >= MIN_DECISIONS_FOR_FULL:
        _check_recruiter_alerts(db, company_id, user_id, recruiter.name, {
            "total_decisions":     total_decisions,
            "skip_count":          skip_count,
            "tier_diversity_score": tier_diversity_score,
            "avg_time_to_decision_s": avg_time_to_decision_s,
            "gold_preference_rate": gold_preference_rate
        })


# ============================================================
# STEP 3 — DECISION SPEED
# ============================================================

def _compute_decision_speed(
    events: list,
    since: datetime
) -> tuple[float, float]:
    """
    Compute avg time between view and action.
    Returns (avg_time_to_decision_s, decisions_per_day)
    """
    if len(events) < 2:
        return None, None

    # Time between consecutive events
    deltas = []
    for i in range(1, len(events)):
        prev = events[i - 1]
        curr = events[i]
        # Only measure view → action pairs
        if prev.action == "view" and curr.action in ("shortlist", "skip", "hire"):
            delta = (curr.created_at - prev.created_at).total_seconds()
            if 0 < delta < 3600:  # ignore gaps > 1 hour
                deltas.append(delta)

    avg_time = round(sum(deltas) / len(deltas), 1) if deltas else None

    # Decisions per day
    days_active = max(1, (datetime.utcnow() - since).days)
    decisions_per_day = round(len(events) / days_active, 2)

    return avg_time, decisions_per_day


# ============================================================
# STEP 4 — SCORE PREFERENCES
# ============================================================

def _compute_score_preferences(
    db: Session,
    company_id: str,
    events: list
) -> tuple[float, float, float]:
    """
    Compute avg scores for shortlisted vs skipped candidates.
    Returns (avg_score_shortlisted, avg_score_skipped, gold_preference_rate)
    """
    shortlisted_ids = [e.candidate_id for e in events if e.action == "shortlist" and e.candidate_id]
    skipped_ids     = [e.candidate_id for e in events if e.action == "skip"      and e.candidate_id]

    avg_score_shortlisted = None
    avg_score_skipped     = None
    gold_preference_rate  = None

    if shortlisted_ids:
        shortlisted_candidates = db.query(CompanyCandidateORM).filter(
            CompanyCandidateORM.id.in_(shortlisted_ids),
            CompanyCandidateORM.is_deleted == False
        ).all()

        if shortlisted_candidates:
            avg_score_shortlisted = round(
                sum(c.match_score for c in shortlisted_candidates) / len(shortlisted_candidates), 1
            )
            # Gold preference rate
            gold_count           = sum(1 for c in shortlisted_candidates if c.tier == "gold")
            gold_preference_rate = round(gold_count / len(shortlisted_candidates), 4)

    if skipped_ids:
        skipped_candidates = db.query(CompanyCandidateORM).filter(
            CompanyCandidateORM.id.in_(skipped_ids),
            CompanyCandidateORM.is_deleted == False
        ).all()

        if skipped_candidates:
            avg_score_skipped = round(
                sum(c.match_score for c in skipped_candidates) / len(skipped_candidates), 1
            )

    return avg_score_shortlisted, avg_score_skipped, gold_preference_rate


# ============================================================
# STEP 5 — TIER DIVERSITY SCORE (Shannon Entropy)
# ============================================================

def _compute_tier_diversity(
    db: Session,
    company_id: str,
    user_id: str,
    since: datetime
) -> float:
    """
    Compute tier diversity score using Shannon entropy.
    Score of 1.0 = perfectly diverse, 0.0 = only one tier.
    """
    # Get shortlisted candidates by this recruiter
    shortlist_events = db.query(FeedbackEventORM).filter(
        FeedbackEventORM.company_id == company_id,
        FeedbackEventORM.user_id == user_id,
        FeedbackEventORM.action == "shortlist",
        FeedbackEventORM.created_at >= since,
        FeedbackEventORM.is_deleted == False
    ).all()

    if not shortlist_events:
        return None

    candidate_ids = [e.candidate_id for e in shortlist_events if e.candidate_id]
    if not candidate_ids:
        return None

    candidates = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.id.in_(candidate_ids),
        CompanyCandidateORM.is_deleted == False
    ).all()

    if not candidates:
        return None

    total = len(candidates)
    gold   = sum(1 for c in candidates if c.tier == "gold")
    silver = sum(1 for c in candidates if c.tier == "silver")
    bronze = sum(1 for c in candidates if c.tier == "bronze")

    # Shannon entropy
    entropy = 0.0
    for count in [gold, silver, bronze]:
        if count > 0:
            p        = count / total
            entropy -= p * math.log2(p)

    # Normalize to 0-1 (max entropy for 3 tiers = log2(3) ≈ 1.585)
    max_entropy           = math.log2(3)
    tier_diversity_score  = round(entropy / max_entropy, 4)

    return tier_diversity_score


# ============================================================
# STEP 9 — RECRUITER ALERTS
# Internal alerts not visible to recruiter
# ============================================================

def _check_recruiter_alerts(
    db: Session,
    company_id: str,
    user_id: str,
    user_name: str,
    metrics: dict
):
    """
    Create internal SLA alerts for recruiter behavior issues.
    Not visible to the recruiter — only to admins.
    """
    alerts = []

    total     = metrics["total_decisions"]
    skips     = metrics["skip_count"]
    diversity = metrics["tier_diversity_score"]
    speed     = metrics["avg_time_to_decision_s"]
    gold_pref = metrics["gold_preference_rate"]

    # High skip rate alert
    skip_rate = skips / max(total, 1)
    if skip_rate > HIGH_SKIP_RATE:
        alerts.append({
            "type":    "high_skip_rate",
            "severity": "warning",
            "message": f"Recruiter {user_name} has a {round(skip_rate*100)}% skip rate — possible bias pattern"
        })

    # Low diversity alert
    if diversity is not None and diversity < LOW_DIVERSITY_SCORE:
        alerts.append({
            "type":    "low_diversity",
            "severity": "warning",
            "message": f"Recruiter {user_name} has low tier diversity score ({diversity}) — reviewing mostly gold candidates"
        })

    # Slow decision speed alert
    if speed is not None and speed > SLOW_DECISION_SECS:
        alerts.append({
            "type":    "slow_decisions",
            "severity": "info",
            "message": f"Recruiter {user_name} avg decision time is {round(speed/60, 1)} minutes"
        })

    # Gold bias alert
    if gold_pref is not None and gold_pref > 0.90:
        alerts.append({
            "type":    "gold_bias",
            "severity": "info",
            "message": f"Recruiter {user_name} shortlists {round(gold_pref*100)}% gold candidates only"
        })

    # Write alerts to SLAAlertORM
    for alert in alerts:
        existing = db.query(SLAAlertORM).filter(
            SLAAlertORM.alert_type == alert["type"],
            SLAAlertORM.company_id == company_id,
            SLAAlertORM.resolved == False
        ).first()

        if not existing:
            db.add(SLAAlertORM(
                id=str(uuid.uuid4()),
                alert_type=alert["type"],
                severity=alert["severity"],
                message=alert["message"],
                company_id=company_id
            ))


# ============================================================
# HELPER — GET BEHAVIOR FLAGS FOR UI
# Human-readable flags for dashboard
# ============================================================

def get_recruiter_flags(rec: RecruiterAnalyticsORM) -> list[str]:
    """
    Return list of behavior flags for a recruiter.
    Shown in the dashboard UI.
    """
    flags = []

    if rec.total_decisions < MIN_DECISIONS_FOR_FULL:
        flags.append("insufficient_data")
        return flags

    # Skip rate
    skip_rate = rec.skip_count / max(rec.total_decisions, 1)
    if skip_rate > HIGH_SKIP_RATE:
        flags.append("high_skip_rate")

    # Diversity
    if rec.tier_diversity_score is not None and rec.tier_diversity_score < LOW_DIVERSITY_SCORE:
        flags.append("low_diversity")

    # Decision speed
    if rec.avg_time_to_decision_s is not None and rec.avg_time_to_decision_s > SLOW_DECISION_SECS:
        flags.append("slow_decisions")

    # Gold bias
    if rec.gold_preference_rate is not None and rec.gold_preference_rate > 0.90:
        flags.append("gold_bias")

    # High performer
    if rec.hire_count >= 3 and skip_rate < 0.3:
        flags.append("top_performer")

    return flags