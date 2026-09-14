# ============================================================
# app/sla_engine.py
# AI Talent Match Pro — Phase 27 SLA Monitoring Engine
# Guarantees 99.9% uptime, <100ms latency, <0.1% error rate
# ============================================================

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid
import math

from app.db import TelemetryORM, SLAAlertORM, UsageLogORM

# ============================================================
# SLA TARGETS — Your contract with LinkedIn-level platforms
# ============================================================
SLA_TARGETS = {
    "p95_latency_ms":     100,    # < 100ms
    "p99_latency_ms":     300,    # < 300ms
    "uptime_pct":         99.9,   # > 99.9%
    "error_rate_pct":     0.1,    # < 0.1%
    "ai_latency_ms":      300,    # < 300ms
    "traffic_spike_mult": 3.0,    # > 3x average = anomaly
}

LOOKBACK_HOURS = 24


# ============================================================
# MAIN SLA CHECK JOB
# Runs hourly via Azure Timer Trigger or /api/sla/run
# ============================================================

def run_sla_check(db: Session, company_id: str = None) -> dict:
    """
    Run full SLA check.
    Computes metrics, creates alerts, resolves recovered alerts.

    Returns: dict of computed metrics
    """
    since = datetime.utcnow() - timedelta(hours=LOOKBACK_HOURS)

    # Pull telemetry
    query = db.query(TelemetryORM).filter(
        TelemetryORM.created_at >= since
    )
    if company_id:
        query = query.filter(TelemetryORM.company_id == company_id)

    logs = query.all()

    # Compute metrics
    metrics = _compute_sla_metrics(logs)

    # Check thresholds and create alerts
    alerts_created = _run_alert_rules(db, metrics, company_id)

    # Auto-resolve recovered alerts
    alerts_resolved = _auto_resolve_alerts(db, metrics, company_id)

    return {
        **metrics,
        "alerts_created":  alerts_created,
        "alerts_resolved": alerts_resolved,
        "checked_at":      datetime.utcnow().isoformat()
    }


# ============================================================
# STEP 2+3 — COMPUTE SLA METRICS
# ============================================================

def _compute_sla_metrics(logs: list) -> dict:
    """
    Compute all SLA metrics from telemetry logs.
    """
    total_requests = len(logs)

    if total_requests == 0:
        return {
            "total_requests":  0,
            "uptime_pct":      100.0,
            "error_rate_pct":  0.0,
            "avg_latency_ms":  0.0,
            "p95_latency_ms":  0.0,
            "p99_latency_ms":  0.0,
            "ai_latency_ms":   0.0,
            "requests_per_hour": 0.0,
            "status":          "healthy"
        }

    # Error counts
    errors      = sum(1 for l in logs if l.status_code >= 500)
    error_rate  = round(errors / total_requests * 100, 4)
    uptime      = round((total_requests - errors) / total_requests * 100, 4)

    # Latency percentiles
    latencies   = sorted([l.latency_ms for l in logs if l.latency_ms])
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    p95_latency = _percentile(latencies, 95)
    p99_latency = _percentile(latencies, 99)

    # AI model latency. This filtered on "/api/grade", a route that does not
    # exist and never has, so the scoring calls — the slowest thing the app
    # does — were missing from the number entirely.
    _AI_PATHS = ("/api/candidates/score", "/api/candidates/bulk",
                 "/api/team-dna", "/api/narrative")
    ai_logs     = [l for l in logs
                   if any(p in (l.endpoint or "") for p in _AI_PATHS)]
    ai_latency  = round(
        sum(l.latency_ms for l in ai_logs) / len(ai_logs), 2
    ) if ai_logs else 0.0

    # Traffic rate
    requests_per_hour = round(total_requests / LOOKBACK_HOURS, 1)

    # Overall status
    status = _compute_status(uptime, p95_latency, error_rate)

    return {
        "total_requests":    total_requests,
        "errors":            errors,
        "uptime_pct":        uptime,
        "error_rate_pct":    error_rate,
        "avg_latency_ms":    avg_latency,
        "p95_latency_ms":    p95_latency,
        "p99_latency_ms":    p99_latency,
        "ai_latency_ms":     ai_latency,
        "requests_per_hour": requests_per_hour,
        "status":            status
    }


# ============================================================
# STEP 4 — ALERT RULES
# ============================================================

def _run_alert_rules(db: Session, metrics: dict, company_id: str = None) -> int:
    """
    Check all SLA thresholds and create alerts for breaches.
    Returns: number of alerts created
    """
    alerts_created = 0

    rules = [
        # (alert_type, metric_key, threshold, operator, severity)
        ("latency_p95",   "p95_latency_ms",   SLA_TARGETS["p95_latency_ms"],  ">", "warning"),
        ("latency_p99",   "p99_latency_ms",   SLA_TARGETS["p99_latency_ms"],  ">", "critical"),
        ("uptime",        "uptime_pct",        SLA_TARGETS["uptime_pct"],      "<", "critical"),
        ("error_rate",    "error_rate_pct",    SLA_TARGETS["error_rate_pct"],  ">", "critical"),
        ("ai_latency",    "ai_latency_ms",     SLA_TARGETS["ai_latency_ms"],   ">", "warning"),
    ]

    for alert_type, metric_key, threshold, operator, severity in rules:
        value = metrics.get(metric_key, 0)
        breached = (value > threshold) if operator == ">" else (value < threshold)

        if breached and value > 0:
            # Check if alert already exists
            existing = db.query(SLAAlertORM).filter(
                SLAAlertORM.alert_type == alert_type,
                SLAAlertORM.resolved == False,
                SLAAlertORM.company_id == company_id
            ).first()

            if not existing:
                alert = SLAAlertORM(
                    id=str(uuid.uuid4()),
                    alert_type=alert_type,
                    severity=severity,
                    message=_build_alert_message(alert_type, value, threshold, operator),
                    metric_value=value,
                    threshold=threshold,
                    company_id=company_id
                )
                db.add(alert)
                alerts_created += 1

    # Traffic spike check
    avg_requests = metrics.get("requests_per_hour", 0)
    if avg_requests > 0:
        spike_threshold = avg_requests * SLA_TARGETS["traffic_spike_mult"]
        existing_spike  = db.query(SLAAlertORM).filter(
            SLAAlertORM.alert_type == "traffic_spike",
            SLAAlertORM.resolved == False
        ).first()
        if not existing_spike and avg_requests > spike_threshold:
            db.add(SLAAlertORM(
                id=str(uuid.uuid4()),
                alert_type="traffic_spike",
                severity="warning",
                message=f"Traffic spike detected: {avg_requests} req/hr (3x normal)",
                metric_value=avg_requests,
                threshold=spike_threshold,
                company_id=company_id
            ))
            alerts_created += 1

    try:
        db.commit()
    except Exception:
        db.rollback()

    return alerts_created


# ============================================================
# STEP 7 — AUTO-RESOLUTION
# Mark alerts as resolved when metrics recover
# ============================================================

def _auto_resolve_alerts(db: Session, metrics: dict, company_id: str = None) -> int:
    """
    Auto-resolve alerts when metrics return to normal.
    Returns: number of alerts resolved
    """
    resolved_count = 0

    # Map alert types to recovery conditions
    recovery_map = {
        "latency_p95": metrics.get("p95_latency_ms", 0) <= SLA_TARGETS["p95_latency_ms"],
        "latency_p99": metrics.get("p99_latency_ms", 0) <= SLA_TARGETS["p99_latency_ms"],
        "uptime":      metrics.get("uptime_pct", 100)   >= SLA_TARGETS["uptime_pct"],
        "error_rate":  metrics.get("error_rate_pct", 0) <= SLA_TARGETS["error_rate_pct"],
        "ai_latency":  metrics.get("ai_latency_ms", 0)  <= SLA_TARGETS["ai_latency_ms"],
    }

    for alert_type, recovered in recovery_map.items():
        if recovered:
            alerts = db.query(SLAAlertORM).filter(
                SLAAlertORM.alert_type == alert_type,
                SLAAlertORM.resolved == False,
                SLAAlertORM.company_id == company_id
            ).all()

            for alert in alerts:
                alert.resolved    = True
                alert.resolved_at = datetime.utcnow()
                resolved_count   += 1

    try:
        db.commit()
    except Exception:
        db.rollback()

    return resolved_count


# ============================================================
# HELPERS
# ============================================================

def _percentile(sorted_list: list, pct: int) -> float:
    """Compute percentile from sorted list."""
    if not sorted_list:
        return 0.0
    idx = max(0, int(len(sorted_list) * pct / 100) - 1)
    return round(sorted_list[idx], 2)


def _compute_status(uptime: float, p95: float, error_rate: float) -> str:
    """Compute overall system status."""
    if uptime >= 99.9 and p95 <= 100 and error_rate <= 0.1:
        return "healthy"
    elif uptime >= 99.0 and p95 <= 300 and error_rate <= 1.0:
        return "degraded"
    else:
        return "down"


def _build_alert_message(alert_type: str, value: float, threshold: float, operator: str) -> str:
    """Build human-readable alert message."""
    messages = {
        "latency_p95": f"P95 latency {value:.1f}ms exceeds {threshold}ms target",
        "latency_p99": f"P99 latency {value:.1f}ms exceeds {threshold}ms target — CRITICAL",
        "uptime":      f"Uptime {value:.2f}% below {threshold}% SLA target — CRITICAL",
        "error_rate":  f"Error rate {value:.3f}% exceeds {threshold}% threshold — CRITICAL",
        "ai_latency":  f"AI model latency {value:.1f}ms exceeds {threshold}ms target",
    }
    return messages.get(alert_type, f"{alert_type}: {value} {'>' if operator == '>' else '<'} {threshold}")


def get_sla_status_color(status: str) -> str:
    """Get color for UI status indicator."""
    return {"healthy": "green", "degraded": "yellow", "down": "red"}.get(status, "grey")