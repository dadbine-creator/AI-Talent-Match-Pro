# ============================================================
# app/forecast_engine.py
# AI Talent Match Pro — Phase 25 Forecasting Engine
# Rule-based forecasting with confidence intervals
# ============================================================

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid

from app.db import (
    CompanyRoleORM, CompanyCandidateORM,
    FeedbackEventORM, InsightSnapshotORM,
    ForecastORM
)

# ============================================================
# CONSTANTS
# ============================================================
MIN_CANDIDATES_FOR_FORECAST = 5    # minimum candidates per job
MIN_HIRES_FOR_FORECAST      = 1    # minimum hires per job
EPSILON                     = 0.01 # avoid division by zero
LOOKBACK_DAYS               = 90   # historical window


# ============================================================
# MAIN FORECAST JOB
# Called nightly via Azure Timer Trigger or /api/forecast/run
# ============================================================

def run_forecast_for_company(db: Session, company_id: str) -> int:
    """
    Compute forecasts for all active jobs in a company.
    Writes ForecastORM rows for each job.

    Returns: number of forecasts written
    """
    since = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)

    # Step 1 — Find all active jobs for this company
    active_jobs = db.query(CompanyRoleORM).filter(
        CompanyRoleORM.company_id == company_id,
        CompanyRoleORM.is_active == True,
        CompanyRoleORM.is_deleted == False
    ).all()

    forecasts_written = 0

    for job in active_jobs:
        try:
            forecast = _compute_forecast_for_job(db, company_id, job, since)
            if forecast:
                db.add(forecast)
                forecasts_written += 1
        except Exception:
            continue

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return forecasts_written


# ============================================================
# PER-JOB FORECAST COMPUTATION
# ============================================================

def _compute_forecast_for_job(
    db: Session,
    company_id: str,
    job: CompanyRoleORM,
    since: datetime
) -> ForecastORM | None:
    """
    Compute a forecast for a single job.
    Returns None if not enough data.
    """
    job_id = job.id

    # Step 2 — Aggregate historical signals from FeedbackEventORM
    feedback_events = db.query(FeedbackEventORM).filter(
        FeedbackEventORM.company_id == company_id,
        FeedbackEventORM.job_id == job_id,
        FeedbackEventORM.created_at >= since,
        FeedbackEventORM.is_deleted == False
    ).all()

    shortlists = sum(1 for e in feedback_events if e.action == "shortlist")
    skips      = sum(1 for e in feedback_events if e.action == "skip")
    hires      = sum(1 for e in feedback_events if e.action == "hire")

    # Aggregate from CompanyCandidateORM
    candidates = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.job_id == job_id,
        CompanyCandidateORM.is_deleted == False
    ).all()

    total_candidates = len(candidates)
    gold_count       = sum(1 for c in candidates if c.tier == "gold")
    silver_count     = sum(1 for c in candidates if c.tier == "silver")
    bronze_count     = sum(1 for c in candidates if c.tier == "bronze")

    avg_match_score = (
        sum(c.match_score for c in candidates) / total_candidates
        if total_candidates > 0 else 0.0
    )

    # Step 7 — Guardrails: not enough data
    if total_candidates < MIN_CANDIDATES_FOR_FORECAST:
        return _low_confidence_forecast(
            company_id, job_id,
            reason=f"Only {total_candidates} candidates — need {MIN_CANDIDATES_FOR_FORECAST}+"
        )

    # Step 3 — Compute forecast metrics using rule-based heuristics

    # predicted_hire_rate
    hire_rate = hires / max(shortlists, EPSILON)
    predicted_hire_rate = round(min(1.0, hire_rate), 4)

    # predicted_time_to_hire
    # Use insight snapshot if available, fallback to heuristic
    snapshot = db.query(InsightSnapshotORM).filter(
        InsightSnapshotORM.company_id == company_id
    ).order_by(InsightSnapshotORM.snapshot_date.desc()).first()

    if snapshot and snapshot.avg_time_to_hire_days:
        base_time = snapshot.avg_time_to_hire_days
    else:
        # Heuristic: lower match score = longer time to hire
        base_time = max(7.0, 30.0 - (avg_match_score * 0.2))

    predicted_time_to_hire = round(base_time, 1)

    # est_candidates_needed
    est_candidates_needed = max(
        3,
        round(1 / max(predicted_hire_rate, EPSILON))
    )

    # Hiring velocity (shortlists per week over lookback window)
    weeks           = LOOKBACK_DAYS / 7
    hiring_velocity = round(shortlists / max(weeks, 1), 1)

    # Confidence score — based on data volume
    data_points      = total_candidates + len(feedback_events)
    confidence_score = round(min(0.95, max(0.3, data_points / 100)), 2)

    # Confidence interval — ±10% around hire rate
    ci_low  = round(max(0.0, predicted_hire_rate - 0.10), 4)
    ci_high = round(min(1.0, predicted_hire_rate + 0.10), 4)

    # Tier quality bonus — more gold candidates = faster hire
    if gold_count > 0:
        predicted_time_to_hire = round(predicted_time_to_hire * 0.85, 1)

    # Step 4 — Build ForecastORM row
    return ForecastORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        job_id=job_id,
        forecast_date=datetime.utcnow(),

        # Core outputs
        predicted_hire_rate=predicted_hire_rate,
        predicted_time_to_hire=predicted_time_to_hire,
        est_candidates_needed=est_candidates_needed,

        # Extended metrics
        hiring_velocity=hiring_velocity,
        conversion_probability=round(predicted_hire_rate * 100, 1),
        est_time_to_hire_days=predicted_time_to_hire,

        # Confidence
        confidence_interval_low=ci_low,
        confidence_interval_high=ci_high,
        confidence_score=confidence_score,

        # Metadata
        model_version="v25.1",
        based_on_events=len(feedback_events)
    )


# ============================================================
# LOW CONFIDENCE FORECAST (not enough data)
# ============================================================

def _low_confidence_forecast(
    company_id: str,
    job_id: str,
    reason: str
) -> ForecastORM:
    """
    Create an experimental forecast when data is insufficient.
    Marked with low confidence score.
    """
    return ForecastORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        job_id=job_id,
        forecast_date=datetime.utcnow(),

        # Conservative defaults
        predicted_hire_rate=0.15,
        predicted_time_to_hire=14.0,
        est_candidates_needed=10,
        hiring_velocity=0.0,
        conversion_probability=15.0,
        est_time_to_hire_days=14.0,

        # Low confidence
        confidence_interval_low=0.05,
        confidence_interval_high=0.25,
        confidence_score=0.15,

        model_version="v25.1-experimental",
        based_on_events=0
    )


# ============================================================
# HELPER — GET FORECAST LABEL
# Human-readable confidence label for UI
# ============================================================

def get_confidence_label(confidence_score: float) -> str:
    """Convert confidence score to human-readable label."""
    if confidence_score >= 0.80:
        return "High"
    elif confidence_score >= 0.50:
        return "Medium"
    elif confidence_score >= 0.30:
        return "Low"
    else:
        return "Experimental"