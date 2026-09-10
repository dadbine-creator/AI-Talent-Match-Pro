"""
============================================================
PHASE 37 — FORECAST ENGINE 2.0
Predictive Hiring Funnel + Scenario Simulation + Confidence Bands
+ Bottleneck Detection + Full Recruiter OS intelligence
============================================================
"""

import os, json, uuid, time, logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db import (
    CompanyCandidateORM,
    OutreachORM,
    RecruiterProjectORM,
    ProjectCandidateORM,
    PipelineStageORM,
    UsageLogORM,
    ForecastCacheORM,
    ScenarioLogORM,
    FunnelStatsORM,
)

logger = logging.getLogger(__name__)

# ── Cache TTL ─────────────────────────────────────────────
CACHE_TTL_SECONDS = 3600  # 1 hour

FUNNEL_STAGES = [
    "Outreach",
    "Response",
    "Shortlist",
    "Interview",
    "Offer",
    "Hire",
]

# ── Default conversion rates (industry benchmarks) ───────
DEFAULT_CONVERSIONS = {
    "Outreach":   0.34,   # 34% respond
    "Response":   0.60,   # 60% of responders get shortlisted
    "Shortlist":  0.50,   # 50% of shortlisted get interviewed
    "Interview":  0.40,   # 40% of interviewed get offers
    "Offer":      0.75,   # 75% of offers get accepted
    "Hire":       1.00,
}

DEFAULT_STAGE_DAYS = {
    "Outreach":   3,
    "Response":   5,
    "Shortlist":  4,
    "Interview":  7,
    "Offer":      3,
    "Hire":       2,
}


# ============================================================
# 37.1 — FUNNEL MODELING
# ============================================================

def compute_funnel(db: Session, company_id: str, project_id: Optional[str] = None) -> dict:
    """Compute hiring funnel predictions with drop-off at each stage."""

    # Get real data
    candidates = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.is_deleted == False,
    ).all()

    outreach_all = db.query(OutreachORM).filter(
        OutreachORM.company_id == company_id,
        OutreachORM.is_deleted == False,
    ).all()

    total_candidates = len(candidates)
    outreach_sent    = sum(1 for o in outreach_all if o.sent)
    outreach_replied = sum(1 for o in outreach_all if o.responded)
    shortlisted      = sum(1 for c in candidates if c.shortlisted)

    # Real conversion rates
    real_response_rate = outreach_replied / outreach_sent if outreach_sent > 0 else DEFAULT_CONVERSIONS["Outreach"]
    real_shortlist_rate = shortlisted / outreach_replied if outreach_replied > 0 else DEFAULT_CONVERSIONS["Response"]

    # Build funnel
    outreach_count  = max(outreach_sent, total_candidates)
    response_count  = round(outreach_count * real_response_rate)
    shortlist_count = round(response_count * real_shortlist_rate)
    interview_count = round(shortlist_count * DEFAULT_CONVERSIONS["Shortlist"])
    offer_count     = round(interview_count * DEFAULT_CONVERSIONS["Interview"])
    hire_count      = round(offer_count * DEFAULT_CONVERSIONS["Offer"])

    counts = [outreach_count, response_count, shortlist_count, interview_count, offer_count, hire_count]

    stages = []
    for i, (stage, count) in enumerate(zip(FUNNEL_STAGES, counts)):
        drop_off = 0.0
        if i > 0 and counts[i - 1] > 0:
            drop_off = round((1 - count / counts[i - 1]) * 100, 1)

        conversion = round((count / counts[i - 1] * 100) if i > 0 and counts[i - 1] > 0 else 100, 1)

        stages.append({
            "stage":          stage,
            "predicted_count": count,
            "drop_off_pct":   drop_off,
            "conversion_pct": conversion,
            "avg_time_days":  DEFAULT_STAGE_DAYS.get(stage, 3),
            "is_bottleneck":  False,
        })

    # Mark bottleneck — stage with highest drop-off
    if stages:
        bottleneck = max(stages[1:], key=lambda s: s["drop_off_pct"])
        bottleneck["is_bottleneck"] = True

    total_days = sum(s["avg_time_days"] for s in stages)

    # Save to FunnelStatsORM
    for s in stages:
        try:
            stat = FunnelStatsORM(
                id=str(uuid.uuid4()),
                company_id=company_id,
                project_id=project_id,
                stage_name=s["stage"],
                predicted_count=s["predicted_count"],
                drop_off_pct=s["drop_off_pct"],
                conversion_pct=s["conversion_pct"],
                avg_time_days=s["avg_time_days"],
                is_bottleneck=s["is_bottleneck"],
            )
            db.add(stat)
        except Exception:
            pass
    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "ok":            True,
        "stages":        stages,
        "total_days":    total_days,
        "predicted_hire": hire_count,
        "outreach_needed": max(0, round(1 / max(real_response_rate * real_shortlist_rate * DEFAULT_CONVERSIONS["Shortlist"] * DEFAULT_CONVERSIONS["Interview"] * DEFAULT_CONVERSIONS["Offer"], 0.001))),
    }


# ============================================================
# 37.2 — CONFIDENCE BANDS
# ============================================================

def compute_confidence_bands(db: Session, company_id: str) -> dict:
    """Compute low/mid/high forecast curves with confidence intervals."""

    from app.intelligence_engine import predict_pipeline_metrics, get_snapshot_trend

    preds = predict_pipeline_metrics(db, company_id)
    trend = get_snapshot_trend(db, company_id, days=30)

    base_days = preds.get("est_time_to_hire_days", 21)
    volatility = preds.get("score_volatility", 5)

    # Confidence multipliers
    low_mult  = 1.0 + (volatility / 100)
    high_mult = max(0.5, 1.0 - (volatility / 200))

    # Generate curves over 30-day horizon
    days = list(range(1, 31))
    mid_curve  = [round(min(100, (d / base_days) * 100), 1) for d in days]
    low_curve  = [round(min(100, (d / (base_days * low_mult)) * 100), 1) for d in days]
    high_curve = [round(min(100, (d / (base_days * high_mult)) * 100), 1) for d in days]

    # Score volatility → confidence score
    confidence_score = max(0.3, min(0.95, 1.0 - volatility / 50))

    return {
        "ok":               True,
        "days":             days,
        "curves": {
            "low":          low_curve,
            "expected":     mid_curve,
            "high":         high_curve,
        },
        "confidence_score": round(confidence_score, 2),
        "volatility_score": volatility,
        "base_time_to_hire": base_days,
        "bands": {
            "p50": base_days,
            "p80": round(base_days * low_mult, 1),
            "p95": round(base_days * low_mult * 1.2, 1),
        },
    }


# ============================================================
# 37.3 — SCENARIO SIMULATION
# ============================================================

def run_scenario(
    db: Session,
    company_id: str,
    outreach_delta: float = 0.0,
    response_delta: float = 0.0,
    recruiter_load: float = 1.0,
    project_id: Optional[str] = None,
) -> dict:
    """
    Simulate 'what if' scenarios.
    outreach_delta: +0.2 = 20% more outreach
    response_delta: -0.1 = 10% lower response rate
    recruiter_load: 1.5 = 50% more workload
    """
    start = time.time()

    from app.intelligence_engine import predict_pipeline_metrics

    base = predict_pipeline_metrics(db, company_id, project_id)
    base_days     = base.get("est_time_to_hire_days", 21)
    base_response = base.get("response_probability", 34) / 100
    base_outreach = base.get("outreach_volume_needed", 10)

    # Apply deltas
    new_response  = max(0.05, min(0.95, base_response + response_delta))
    new_outreach  = max(1, round(base_outreach * (1 + outreach_delta)))
    load_factor   = max(0.5, min(3.0, recruiter_load))

    # Recompute time-to-hire
    response_lift    = new_response / max(base_response, 0.01)
    outreach_lift    = (1 + outreach_delta) if outreach_delta > 0 else 1.0
    load_penalty     = load_factor ** 0.5
    new_days         = round(base_days / (response_lift * outreach_lift) * load_penalty, 1)
    new_days         = max(7, new_days)

    # New funnel
    outreach_count   = new_outreach
    response_count   = round(outreach_count * new_response)
    shortlist_count  = round(response_count * 0.6)
    interview_count  = round(shortlist_count * 0.5)
    offer_count      = round(interview_count * 0.4)
    hire_count       = round(offer_count * 0.75)

    new_funnel = [
        {"stage": "Outreach",   "count": outreach_count},
        {"stage": "Response",   "count": response_count},
        {"stage": "Shortlist",  "count": shortlist_count},
        {"stage": "Interview",  "count": interview_count},
        {"stage": "Offer",      "count": offer_count},
        {"stage": "Hire",       "count": hire_count},
    ]

    # Risk score
    risk_score = "LOW"
    if new_days > base_days * 1.3 or new_response < 0.15:
        risk_score = "HIGH"
    elif new_days > base_days * 1.1:
        risk_score = "MEDIUM"

    improvement_pct = round((base_days - new_days) / base_days * 100, 1)

    latency_ms = round((time.time() - start) * 1000, 1)

    # Log scenario
    try:
        log = ScenarioLogORM(
            id=str(uuid.uuid4()),
            company_id=company_id,
            project_id=project_id,
            inputs_json=json.dumps({
                "outreach_delta": outreach_delta,
                "response_delta": response_delta,
                "recruiter_load": recruiter_load,
            }),
            outputs_json=json.dumps({
                "new_days": new_days,
                "risk_score": risk_score,
                "improvement_pct": improvement_pct,
            }),
            latency_ms=latency_ms,
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()

    return {
        "ok":               True,
        "inputs": {
            "outreach_delta":  outreach_delta,
            "response_delta":  response_delta,
            "recruiter_load":  recruiter_load,
        },
        "baseline": {
            "time_to_hire":    base_days,
            "response_rate":   round(base_response * 100, 1),
            "outreach_needed": base_outreach,
        },
        "scenario": {
            "time_to_hire":    new_days,
            "response_rate":   round(new_response * 100, 1),
            "outreach_needed": new_outreach,
            "risk_score":      risk_score,
            "funnel":          new_funnel,
        },
        "improvement_pct":  improvement_pct,
        "narrative":        _scenario_narrative(outreach_delta, response_delta, recruiter_load, new_days, base_days, improvement_pct),
        "latency_ms":       latency_ms,
    }


def _scenario_narrative(od, rd, rl, new_days, base_days, improvement_pct):
    parts = []
    if od > 0:
        parts.append(f"increasing outreach by {round(od*100)}%")
    elif od < 0:
        parts.append(f"reducing outreach by {round(abs(od)*100)}%")
    if rd > 0:
        parts.append(f"improving response rate by {round(rd*100)}%")
    elif rd < 0:
        parts.append(f"response rate dropping by {round(abs(rd)*100)}%")
    if rl > 1.0:
        parts.append(f"recruiter workload increasing {round(rl,1)}x")

    if not parts:
        return "No scenario changes applied."

    scenario_desc = ", ".join(parts)
    if improvement_pct > 0:
        return f"Scenario simulation suggests that {scenario_desc} could reduce time-to-hire by {improvement_pct}% — from {base_days} to {new_days} days."
    else:
        return f"Scenario simulation suggests that {scenario_desc} would increase time-to-hire by {abs(improvement_pct)}% — from {base_days} to {new_days} days."


# ============================================================
# 37.4 — BOTTLENECK DETECTION
# ============================================================

def detect_bottlenecks(db: Session, company_id: str, project_id: Optional[str] = None) -> dict:
    """Detect which pipeline stage is causing the most delay."""
    funnel = compute_funnel(db, company_id, project_id)
    stages = funnel.get("stages", [])

    if not stages:
        return {"ok": True, "bottleneck": None}

    # Find bottleneck — highest drop-off
    bottleneck = None
    for s in stages[1:]:
        if s["is_bottleneck"]:
            bottleneck = s
            break

    if not bottleneck and len(stages) > 1:
        bottleneck = max(stages[1:], key=lambda s: s["drop_off_pct"])

    root_causes = {
        "Response":   "Low response rate — messages may not be personalized enough or channel mix is off.",
        "Shortlist":  "High drop-off after response — candidates may not be aligned with role requirements.",
        "Interview":  "Scheduling delays or interview process too long.",
        "Offer":      "Offer not competitive enough — compensation or role fit issues.",
        "Hire":       "Candidates accepting competing offers — speed of process is critical.",
    }

    recommendations = {
        "Response":   "Switch to LinkedIn InMail, increase personalization, send follow-ups at day 5.",
        "Shortlist":  "Refine search criteria, add more gold tier candidates, review JD alignment.",
        "Interview":  "Streamline interview process to 2 rounds max, use async video screening.",
        "Offer":      "Benchmark compensation, add equity component, speed up offer delivery.",
        "Hire":       "Move faster — compress process to 10 days total, send offer same day as final interview.",
    }

    stage_name = bottleneck["stage"] if bottleneck else "Unknown"

    return {
        "ok":            True,
        "bottleneck": {
            "stage":       stage_name,
            "drop_off_pct": bottleneck["drop_off_pct"] if bottleneck else 0,
            "predicted_count": bottleneck["predicted_count"] if bottleneck else 0,
            "root_cause":  root_causes.get(stage_name, "Unknown cause."),
            "recommendation": recommendations.get(stage_name, "Review stage metrics."),
        },
        "all_stages":    stages,
        "funnel_health": "CRITICAL" if (bottleneck and bottleneck["drop_off_pct"] > 60) else "WARNING" if (bottleneck and bottleneck["drop_off_pct"] > 40) else "GOOD",
    }


# ============================================================
# 37.5 — RECRUITER OS: SMART SEARCH
# ============================================================

def smart_search(db: Session, company_id: str, query: str, filters: dict = None) -> dict:
    """Search candidates across all projects."""
    q = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.is_deleted == False,
    )

    if query:
        q = q.filter(
            CompanyCandidateORM.name.ilike(f"%{query}%") |
            CompanyCandidateORM.role.ilike(f"%{query}%") |
            CompanyCandidateORM.ai_analysis.ilike(f"%{query}%")
        )

    if filters:
        if filters.get("tier"):
            q = q.filter(CompanyCandidateORM.tier == filters["tier"])
        if filters.get("min_score"):
            q = q.filter(CompanyCandidateORM.match_score >= float(filters["min_score"]))
        if filters.get("shortlisted") is not None:
            q = q.filter(CompanyCandidateORM.shortlisted == filters["shortlisted"])

    candidates = q.order_by(desc(CompanyCandidateORM.match_score)).limit(50).all()

    return {
        "ok":    True,
        "query": query,
        "results": [
            {
                "id":          c.id,
                "name":        c.name,
                "role":        c.role,
                "tier":        c.tier,
                "match_score": c.match_score,
                "shortlisted": c.shortlisted,
                "created_at":  c.created_at.isoformat(),
            }
            for c in candidates
        ],
        "total": len(candidates),
    }


# ============================================================
# 37.6 — CANDIDATE TIMELINE
# ============================================================

def get_candidate_timeline(db: Session, company_id: str, candidate_id: str) -> dict:
    """Full history for a candidate — outreach, stages, scorecards, narratives."""
    events = []

    # Outreach events
    try:
        outreach_list = db.query(OutreachORM).filter(
            OutreachORM.candidate_id == candidate_id,
            OutreachORM.company_id   == company_id,
        ).order_by(OutreachORM.created_at).all()

        for o in outreach_list:
            events.append({
                "type":    "outreach",
                "label":   f"Outreach sent — {o.message_type}",
                "detail":  o.subject or o.content[:80] if o.content else "",
                "date":    o.created_at.isoformat(),
                "icon":    "📨",
            })
            if o.responded:
                events.append({
                    "type":  "response",
                    "label": "Candidate responded",
                    "detail": "",
                    "date":  o.responded_at.isoformat() if o.responded_at else o.created_at.isoformat(),
                    "icon":  "✅",
                })
    except Exception:
        pass

    # Scorecard events
    try:
        from app.db import ScorecardORM
        scorecard = db.query(ScorecardORM).filter(
            ScorecardORM.candidate_id == candidate_id,
            ScorecardORM.company_id   == company_id,
            ScorecardORM.is_deleted   == False,
        ).order_by(ScorecardORM.created_at).first()

        if scorecard:
            events.append({
                "type":   "scorecard",
                "label":  f"Scorecard generated — {scorecard.recommendation_label}",
                "detail": scorecard.summary or "",
                "date":   scorecard.created_at.isoformat(),
                "icon":   "📊",
            })
    except Exception:
        pass

    # Narrative events
    try:
        from app.db import AINarrativeORM
        narrative = db.query(AINarrativeORM).filter(
            AINarrativeORM.candidate_id == candidate_id,
            AINarrativeORM.company_id   == company_id,
        ).order_by(AINarrativeORM.created_at).first()

        if narrative:
            events.append({
                "type":   "narrative",
                "label":  "AI Narrative generated",
                "detail": narrative.narrative[:100] if narrative.narrative else "",
                "date":   narrative.created_at.isoformat(),
                "icon":   "📝",
            })
    except Exception:
        pass

    # Sort by date
    events.sort(key=lambda e: e["date"])

    return {
        "ok":       True,
        "candidate_id": candidate_id,
        "events":   events,
        "total":    len(events),
    }


# ============================================================
# 37.7 — CANDIDATE COMPARISON
# ============================================================

def compare_candidates(db: Session, company_id: str, candidate_id_a: str, candidate_id_b: str) -> dict:
    """Compare two candidates side by side."""
    a = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.id == candidate_id_a,
        CompanyCandidateORM.company_id == company_id,
    ).first()

    b = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.id == candidate_id_b,
        CompanyCandidateORM.company_id == company_id,
    ).first()

    if not a or not b:
        return {"ok": False, "error": "One or both candidates not found"}

    def to_dict(c):
        return {
            "id":           c.id,
            "name":         c.name,
            "role":         c.role,
            "tier":         c.tier,
            "match_score":  c.match_score,
            "adaptability": c.adaptability,
            "focus_penalty": c.focus_penalty,
            "silent_skill": c.silent_skill,
            "ai_analysis":  c.ai_analysis,
            "shortlisted":  c.shortlisted,
        }

    winner = a if (a.match_score or 0) >= (b.match_score or 0) else b

    return {
        "ok":        True,
        "candidate_a": to_dict(a),
        "candidate_b": to_dict(b),
        "winner":    winner.id,
        "winner_name": winner.name,
        "score_diff": round(abs((a.match_score or 0) - (b.match_score or 0)), 1),
    }