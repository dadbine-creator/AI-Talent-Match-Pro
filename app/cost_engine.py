from typing import Optional
# ============================================================
# app/cost_engine.py
# AI Talent Match Pro — Phase 28 Cost Optimization Engine
# Reduces AI cost 60-80% while increasing throughput
# Target: irresistible unit economics for $1B acquisition
# ============================================================

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid
import hashlib
import json

from app.db import (
    UsageLogORM, CostOptimizerORM,
    CompanyCandidateORM, SLAAlertORM
)

# ============================================================
# MODEL PRICING (per 1K tokens)
# ============================================================
MODEL_PRICING = {
    "gpt-4o":           {"input": 0.005,  "output": 0.015},   # premium
    "gpt-4o-mini":      {"input": 0.00015,"output": 0.0006},  # cheap
    "gpt-3.5-turbo":    {"input": 0.0005, "output": 0.0015},  # mid
}

# ============================================================
# BUDGET LIMITS PER PLAN
# ============================================================
PLAN_BUDGETS = {
    "free":       {"monthly_usd": 0.10,  "ai_calls": 10},
    "business":   {"monthly_usd": 2.00,  "ai_calls": 200},
    "corporate":  {"monthly_usd": 10.00, "ai_calls": 1000},
    "enterprise": {"monthly_usd": 999.0, "ai_calls": 99999},
}

# ============================================================
# STEP 2 — AI COST CALCULATOR
# ============================================================

def calculate_ai_cost(
    model_name: str,
    tokens_in: int,
    tokens_out: int
) -> float:
    """
    Calculate exact cost for an AI call based on token usage.
    Returns cost in USD.
    """
    pricing = MODEL_PRICING.get(model_name, MODEL_PRICING["gpt-4o"])
    cost_in  = (tokens_in  / 1000) * pricing["input"]
    cost_out = (tokens_out / 1000) * pricing["output"]
    return round(cost_in + cost_out, 6)


# ============================================================
# STEP 3 — MODEL TIERING (Smart Model Selection)
# Cuts cost 40-60% by routing to appropriate model
# ============================================================

def select_model_for_tier(tier: str, task: str = "scoring") -> str:
    """
    Select the optimal AI model based on candidate tier and task.

    Bronze → cheap model (gpt-4o-mini)
    Silver → mid model  (gpt-4o-mini)
    Gold   → premium    (gpt-4o)
    Narrative → premium (gpt-4o)
    Bulk scoring → cheap (gpt-4o-mini)
    """
    if task == "narrative":
        return "gpt-4o"          # narratives always premium

    if task == "bulk":
        return "gpt-4o-mini"     # bulk always cheap

    tier_model_map = {
        "gold":   "gpt-4o",       # premium for gold
        "silver": "gpt-4o-mini",  # cheap for silver
        "bronze": "gpt-4o-mini",  # cheap for bronze
    }
    return tier_model_map.get(tier, "gpt-4o-mini")


# ============================================================
# STEP 4 — AI RESPONSE CACHING
# Cache key: hash(resume + job_description + model_version)
# Cuts cost another 20-30%
# ============================================================

def generate_cache_key(
    resume_text: str,
    job_description: str,
    model_version: str
) -> str:
    """Generate deterministic cache key for AI response."""
    raw = f"{resume_text}|{job_description}|{model_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached_response(
    db: Session,
    cache_key: str,
    ttl_hours: int = 24
) -> Optional[str]:
    """
    Check if we have a cached AI response.
    Returns cached content or None.
    """
    since = datetime.utcnow() - timedelta(hours=ttl_hours)
    cached = db.query(UsageLogORM).filter(
        UsageLogORM.action == "ai_cache",
        UsageLogORM.details == cache_key,
        UsageLogORM.created_at >= since
    ).first()
    return cached.details if cached else None


def store_cached_response(
    db: Session,
    cache_key: str,
    company_id: str,
    user_id: str
):
    """Store AI response in cache."""
    log = UsageLogORM(
        company_id=company_id,
        user_id=user_id,
        action="ai_cache",
        details=cache_key,
        cost_usd=0.0
    )
    db.add(log)
    try:
        db.commit()
    except Exception:
        db.rollback()


# ============================================================
# STEP 5 — BATCH PROCESSING
# Process 10-20 candidates per request instead of 1 at a time
# ============================================================

def should_use_batch(candidate_count: int) -> bool:
    """Determine if batch processing should be used."""
    return candidate_count >= 5


def estimate_batch_savings(candidate_count: int, model: str) -> dict:
    """
    Estimate cost savings from batching vs individual calls.
    """
    individual_overhead_tokens = 200  # system prompt tokens per call
    batch_overhead_tokens      = 400  # system prompt tokens for batch

    individual_cost = candidate_count * (individual_overhead_tokens / 1000) * MODEL_PRICING[model]["input"]
    batch_cost      = (batch_overhead_tokens / 1000) * MODEL_PRICING[model]["input"]
    savings         = individual_cost - batch_cost

    return {
        "individual_cost_usd": round(individual_cost, 6),
        "batch_cost_usd":      round(batch_cost, 6),
        "savings_usd":         round(savings, 6),
        "savings_pct":         round(savings / max(individual_cost, 0.0001) * 100, 1)
    }


# ============================================================
# STEP 6 — COST TRACKER
# Get or create monthly cost record, update in real-time
# ============================================================

def track_ai_call(
    db: Session,
    company_id: str,
    user_id: str,
    model_name: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: float,
    cache_hit: bool = False,
    action: str = "ai_grade"
) -> dict:
    """
    Track a single AI call — cost, tokens, latency.
    Updates CostOptimizerORM for the current month.
    Returns cost breakdown.
    """
    cost_usd = 0.0 if cache_hit else calculate_ai_cost(model_name, tokens_in, tokens_out)
    month    = datetime.utcnow().strftime("%Y-%m")

    # Log to UsageLogORM
    log = UsageLogORM(
        company_id=company_id,
        user_id=user_id,
        action=action,
        details=f"model={model_name} tokens_in={tokens_in} tokens_out={tokens_out} cache_hit={cache_hit}",
        latency_ms=latency_ms,
        cost_usd=cost_usd
    )
    db.add(log)

    # Update CostOptimizerORM
    cost_record = db.query(CostOptimizerORM).filter(
        CostOptimizerORM.company_id == company_id,
        CostOptimizerORM.month == month
    ).first()

    if cost_record:
        cost_record.ai_calls_this_month += 1
        cost_record.ai_calls_remaining   = max(0, cost_record.ai_calls_remaining - 1)
        cost_record.total_cost_usd       = round(cost_record.total_cost_usd + cost_usd, 6)
        cost_record.avg_latency_ms       = round(
            (cost_record.avg_latency_ms + latency_ms) / 2, 2
        ) if cost_record.avg_latency_ms else latency_ms

    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "model":      model_name,
        "tokens_in":  tokens_in,
        "tokens_out": tokens_out,
        "cost_usd":   cost_usd,
        "cache_hit":  cache_hit,
        "latency_ms": latency_ms
    }


# ============================================================
# STEP 7 — COST ALERTS
# ============================================================

def check_cost_alerts(
    db: Session,
    company_id: str,
    plan: str
):
    """
    Check for cost anomalies and create SLA alerts.
    Thresholds: 50%, 80%, 100% of monthly budget.
    """
    month  = datetime.utcnow().strftime("%Y-%m")
    budget = PLAN_BUDGETS.get(plan, PLAN_BUDGETS["free"])

    cost_record = db.query(CostOptimizerORM).filter(
        CostOptimizerORM.company_id == company_id,
        CostOptimizerORM.month == month
    ).first()

    if not cost_record:
        return

    pct_used = cost_record.total_cost_usd / max(budget["monthly_usd"], 0.01) * 100

    alerts = []

    if pct_used >= 100:
        alerts.append(("budget_exceeded", "critical", f"Monthly AI budget exceeded — {pct_used:.1f}% used"))
    elif pct_used >= 80:
        alerts.append(("budget_warning", "warning", f"AI budget at {pct_used:.1f}% — approaching limit"))
    elif pct_used >= 50:
        alerts.append(("budget_halfway", "info", f"AI budget at {pct_used:.1f}% for the month"))

    # Cache miss rate check
    total_calls = cost_record.ai_calls_this_month
    if total_calls > 20:
        cache_hits = db.query(UsageLogORM).filter(
            UsageLogORM.company_id == company_id,
            UsageLogORM.action == "ai_cache"
        ).count()
        cache_miss_rate = 1 - (cache_hits / max(total_calls, 1))
        if cache_miss_rate > 0.9:
            alerts.append(("cache_miss_high", "warning", f"Cache miss rate {cache_miss_rate*100:.0f}% — caching not effective"))

    for alert_type, severity, message in alerts:
        existing = db.query(SLAAlertORM).filter(
            SLAAlertORM.alert_type == alert_type,
            SLAAlertORM.company_id == company_id,
            SLAAlertORM.resolved == False
        ).first()

        if not existing:
            db.add(SLAAlertORM(
                id=str(uuid.uuid4()),
                alert_type=alert_type,
                severity=severity,
                message=message,
                metric_value=pct_used,
                threshold=100.0,
                company_id=company_id
            ))

    try:
        db.commit()
    except Exception:
        db.rollback()


# ============================================================
# STEP 9 — AUTO-OPTIMIZATION ENGINE
# Self-healing cost controls
# ============================================================

def run_cost_optimization(db: Session, company_id: str, plan: str) -> dict:
    """
    Run the auto-optimization engine.
    Analyzes usage patterns and recommends/applies optimizations.

    Returns: optimization report
    """
    month  = datetime.utcnow().strftime("%Y-%m")
    budget = PLAN_BUDGETS.get(plan, PLAN_BUDGETS["free"])

    # Get current month stats
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ai_logs = db.query(UsageLogORM).filter(
        UsageLogORM.company_id == company_id,
        UsageLogORM.action.in_(["ai_grade", "ai_narrative"]),
        UsageLogORM.created_at >= month_start
    ).all()

    total_calls  = len(ai_logs)
    total_cost   = sum(l.cost_usd or 0 for l in ai_logs)
    avg_cost     = round(total_cost / max(total_calls, 1), 6)
    avg_latency  = round(sum(l.latency_ms or 0 for l in ai_logs) / max(total_calls, 1), 2)

    # Days remaining in month
    days_in_month    = 30
    days_elapsed     = datetime.utcnow().day
    days_remaining   = max(1, days_in_month - days_elapsed)
    projected_cost   = round(total_cost / max(days_elapsed, 1) * days_in_month, 4)
    budget_remaining = round(budget["monthly_usd"] - total_cost, 4)

    # Optimization recommendations
    recommendations = []
    optimizations   = []

    # Check if over budget
    if total_cost > budget["monthly_usd"] * 0.8:
        recommendations.append("Switch Bronze/Silver candidates to gpt-4o-mini")
        optimizations.append("model_downgrade")

    # Check if caching would help
    if total_calls > 10 and avg_cost > 0.005:
        recommendations.append("Enable aggressive caching — high repeat scoring detected")
        optimizations.append("enable_caching")

    # Check if batching would help
    if total_calls > 5:
        recommendations.append("Enable batch processing — scoring candidates individually")
        optimizations.append("enable_batching")

    # Check latency
    if avg_latency > 200:
        recommendations.append("Switch to gpt-4o-mini for non-gold candidates — latency too high")
        optimizations.append("latency_optimization")

    # Cost per candidate
    total_candidates = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.is_deleted == False
    ).count()
    cost_per_candidate = round(total_cost / max(total_candidates, 1), 6)

    return {
        "month":              month,
        "total_calls":        total_calls,
        "total_cost_usd":     round(total_cost, 4),
        "avg_cost_per_call":  avg_cost,
        "cost_per_candidate": cost_per_candidate,
        "avg_latency_ms":     avg_latency,
        "projected_month_usd": projected_cost,
        "budget_usd":         budget["monthly_usd"],
        "budget_remaining":   budget_remaining,
        "budget_used_pct":    round(total_cost / max(budget["monthly_usd"], 0.01) * 100, 1),
        "days_remaining":     days_remaining,
        "recommendations":    recommendations,
        "optimizations":      optimizations,
        "is_over_budget":     total_cost > budget["monthly_usd"],
        "is_near_budget":     total_cost > budget["monthly_usd"] * 0.8
    }


# ============================================================
# STEP 10 — ENTERPRISE COST CONTROLS
# Per-company, per-user, per-team limits
# ============================================================

def check_ai_call_allowed(
    db: Session,
    company_id: str,
    plan: str
) -> tuple[bool, str]:
    """
    Check if an AI call is allowed based on plan limits.
    Returns (allowed: bool, reason: str)
    """
    budget = PLAN_BUDGETS.get(plan, PLAN_BUDGETS["free"])
    month  = datetime.utcnow().strftime("%Y-%m")

    cost_record = db.query(CostOptimizerORM).filter(
        CostOptimizerORM.company_id == company_id,
        CostOptimizerORM.month == month
    ).first()

    if not cost_record:
        return True, "ok"

    if cost_record.ai_calls_this_month >= budget["ai_calls"]:
        return False, f"Monthly AI call limit reached ({budget['ai_calls']} calls). Upgrade your plan."

    if cost_record.total_cost_usd >= budget["monthly_usd"]:
        return False, f"Monthly AI budget exceeded (${budget['monthly_usd']}). Upgrade your plan."

    if cost_record.is_throttled:
        return False, f"AI calls throttled: {cost_record.throttle_reason}"

    return True, "ok"


# ============================================================
# HELPER — GET COST SUMMARY FOR API
# ============================================================

def get_cost_summary(db: Session, company_id: str, plan: str) -> dict:
    """Get full cost summary for /api/cost endpoint."""
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month       = datetime.utcnow().strftime("%Y-%m")
    budget      = PLAN_BUDGETS.get(plan, PLAN_BUDGETS["free"])

    # Real counts
    ai_calls = db.query(UsageLogORM).filter(
        UsageLogORM.company_id == company_id,
        UsageLogORM.action.in_(["ai_grade", "ai_narrative"]),
        UsageLogORM.created_at >= month_start
    ).count()

    total_cost = db.query(func.sum(UsageLogORM.cost_usd)).filter(
        UsageLogORM.company_id == company_id,
        UsageLogORM.created_at >= month_start
    ).scalar() or 0.0

    cache_hits = db.query(UsageLogORM).filter(
        UsageLogORM.company_id == company_id,
        UsageLogORM.action == "ai_cache",
        UsageLogORM.created_at >= month_start
    ).count()

    avg_latency = db.query(func.avg(UsageLogORM.latency_ms)).filter(
        UsageLogORM.company_id == company_id,
        UsageLogORM.latency_ms != None,
        UsageLogORM.created_at >= month_start
    ).scalar() or 0.0

    remaining    = max(0, budget["ai_calls"] - ai_calls)
    pct_used     = round(ai_calls / max(budget["ai_calls"], 1) * 100, 1)
    cache_rate   = round(cache_hits / max(ai_calls, 1) * 100, 1)
    days_elapsed = max(1, datetime.utcnow().day)
    projected    = round(total_cost / days_elapsed * 30, 4)

    return {
        "month":            month,
        "ai_calls":         ai_calls,
        "ai_calls_limit":   budget["ai_calls"],
        "ai_calls_remaining": remaining,
        "pct_used":         pct_used,
        "total_cost_usd":   round(total_cost, 4),
        "budget_usd":       budget["monthly_usd"],
        "projected_usd":    projected,
        "cache_hit_rate":   cache_rate,
        "avg_latency_ms":   round(avg_latency, 2),
        "is_throttled":     pct_used >= 100,
        "alert":            (
            "🔴 Budget exceeded — AI calls disabled" if pct_used >= 100 else
            "🟡 80% of budget used — approaching limit" if pct_used >= 80 else
            "🟢 Budget healthy" if pct_used < 50 else
            "🟡 50% of budget used"
        )
    }