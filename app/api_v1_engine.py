# ============================================================
# app/api_v1_engine.py
# AI Talent Match Pro — Phase 31 External API Engine
# API Key Auth + Webhooks + Partner Integrations
# This turns AI Talent Match Pro into a platform
# ============================================================

import hashlib
import hmac
import json
import secrets
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
import httpx

from app.db import (
    APIKeyORM, WebhookORM, WebhookDeliveryLogORM,
    APIAuditLogORM, CompanyORM
)

# ============================================================
# API KEY SCOPES
# ============================================================
VALID_SCOPES = [
    "candidates:read",
    "candidates:write",
    "narratives:generate",
    "analytics:read",
    "webhooks:manage",
    "forecasts:read",
    "cost:read",
    "sla:read",
]

# ============================================================
# WEBHOOK EVENTS
# ============================================================
WEBHOOK_EVENTS = [
    "candidate.created",
    "candidate.updated",
    "candidate.deleted",
    "narrative.generated",
    "narrative.updated",
    "billing.invoice.created",
    "billing.subscription.updated",
    "sla.alert.created",
    "sla.alert.resolved",
    "model.retrained",
    "forecast.generated",
]

# ============================================================
# RATE LIMITS PER PLAN
# ============================================================
PLAN_RATE_LIMITS = {
    "free":       60,    # 60 req/min
    "business":   120,   # 120 req/min
    "corporate":  300,   # 300 req/min
    "enterprise": 600,   # 600 req/min
}

# In-memory rate limit store (use Redis in production)
_api_key_rate_store: dict = {}

# ============================================================
# SECTION A — API KEY MANAGEMENT
# ============================================================

def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.
    Returns: (raw_key, key_hash, key_prefix)
    Never store the raw key — only the hash.
    Format: aitmp_<random64>
    """
    raw_key    = f"aitmp_{secrets.token_hex(32)}"
    key_hash   = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]  # "aitmp_" + 6 chars
    return raw_key, key_hash, key_prefix


def hash_api_key(raw_key: str) -> str:
    """Hash a raw API key for storage/lookup."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def validate_api_key(
    db: Session,
    raw_key: str,
    required_scope: str = None
) -> tuple[bool, Optional[APIKeyORM], str]:
    """
    Validate an API key from request header.
    Returns: (valid, api_key_orm, error_message)
    """
    if not raw_key or not raw_key.startswith("aitmp_"):
        return False, None, "Invalid API key format. Keys must start with 'aitmp_'"

    key_hash = hash_api_key(raw_key)

    api_key = db.query(APIKeyORM).filter(
        APIKeyORM.key_hash == key_hash,
        APIKeyORM.is_active == True,
        APIKeyORM.is_deleted == False
    ).first()

    if not api_key:
        return False, None, "Invalid or revoked API key"

    # Check expiry
    if api_key.expires_at and api_key.expires_at < datetime.utcnow():
        return False, None, "API key has expired"

    # Check scope
    if required_scope:
        scopes = json.loads(api_key.scopes or "[]")
        if required_scope not in scopes and "*" not in scopes:
            return False, None, f"API key missing required scope: {required_scope}"

    # Check rate limit
    allowed, reason = check_api_key_rate_limit(api_key.id, api_key.rate_limit)
    if not allowed:
        return False, None, reason

    # Update last used
    api_key.last_used_at = datetime.utcnow()
    api_key.total_calls  += 1
    try:
        db.commit()
    except Exception:
        db.rollback()

    return True, api_key, "ok"


def create_api_key(
    db: Session,
    company_id: str,
    created_by: str,
    name: str,
    scopes: list,
    rate_limit: int = 60,
    expires_in_days: int = None
) -> dict:
    """
    Create a new API key for a company.
    Returns the raw key ONCE — never retrievable again.
    """
    # Validate scopes
    invalid = [s for s in scopes if s not in VALID_SCOPES]
    if invalid:
        raise ValueError(f"Invalid scopes: {invalid}")

    raw_key, key_hash, key_prefix = generate_api_key()
    expires_at = datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None

    api_key = APIKeyORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        created_by=created_by,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=json.dumps(scopes),
        rate_limit=rate_limit,
        expires_at=expires_at
    )
    db.add(api_key)
    db.commit()

    return {
        "id":         api_key.id,
        "name":       name,
        "key":        raw_key,      # shown ONCE only
        "key_prefix": key_prefix,
        "scopes":     scopes,
        "rate_limit": rate_limit,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "created_at": api_key.created_at.isoformat(),
        "warning":    "Store this key securely — it will never be shown again"
    }


# ============================================================
# SECTION G — RATE LIMITING PER API KEY
# ============================================================

def check_api_key_rate_limit(
    key_id: str,
    max_calls: int,
    window_seconds: int = 60
) -> tuple[bool, str]:
    """
    Check rate limit for a specific API key.
    Returns (allowed, reason)
    """
    now   = time.time()
    calls = [t for t in _api_key_rate_store.get(key_id, []) if now - t < window_seconds]
    _api_key_rate_store[key_id] = calls

    if len(calls) >= max_calls:
        return False, f"Rate limit exceeded: {max_calls} requests/minute. Upgrade your plan for higher limits."

    _api_key_rate_store[key_id].append(now)
    return True, "ok"


# ============================================================
# SECTION E — WEBHOOK DELIVERY ENGINE
# ============================================================

def generate_webhook_secret() -> str:
    """Generate a secure HMAC secret for a webhook."""
    return secrets.token_hex(32)


def sign_webhook_payload(payload: str, secret: str) -> str:
    """
    Generate HMAC-SHA256 signature for webhook payload.
    Header: X-AITMP-Signature: sha256=<signature>
    """
    signature = hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"sha256={signature}"


async def deliver_webhook(
    db: Session,
    webhook: WebhookORM,
    event_type: str,
    payload: dict,
    attempt: int = 1
) -> dict:
    """
    Deliver a webhook event to the registered URL.
    Includes HMAC signature, retry logic.
    Logs every attempt to WebhookDeliveryLogORM.
    """
    event_id     = str(uuid.uuid4())
    payload_str  = json.dumps({
        "event":      event_type,
        "event_id":   event_id,
        "timestamp":  datetime.utcnow().isoformat(),
        "data":       payload
    })
    signature    = sign_webhook_payload(payload_str, webhook.secret)
    headers      = {
        "Content-Type":       "application/json",
        "X-AITMP-Signature":  signature,
        "X-AITMP-Event":      event_type,
        "X-AITMP-Event-ID":   event_id,
        "X-AITMP-Timestamp":  datetime.utcnow().isoformat(),
        "User-Agent":         "AITMP-Webhooks/31.0"
    }

    start      = time.time()
    status     = "failed"
    http_code  = None
    response   = None
    error      = None

    try:
        async with httpx.AsyncClient() as client:
            resp      = await client.post(
                webhook.url,
                content=payload_str,
                headers=headers,
                timeout=10.0
            )
            http_code = resp.status_code
            response  = resp.text[:500]
            status    = "success" if resp.status_code < 400 else "failed"
    except Exception as e:
        error  = str(e)[:500]
        status = "failed"

    latency_ms = round((time.time() - start) * 1000, 2)

    # Calculate next retry with exponential backoff
    next_retry = None
    if status == "failed" and attempt < 5:
        backoff_seconds = 60 * (2 ** (attempt - 1))  # 1m, 2m, 4m, 8m, 16m
        next_retry = datetime.utcnow() + timedelta(seconds=backoff_seconds)

    # Log delivery attempt
    log = WebhookDeliveryLogORM(
        id=str(uuid.uuid4()),
        webhook_id=webhook.id,
        company_id=webhook.company_id,
        event_type=event_type,
        event_id=event_id,
        payload=payload_str[:2000],
        status=status,
        http_status=http_code,
        response_body=response,
        error=error,
        latency_ms=latency_ms,
        attempt=attempt,
        next_retry_at=next_retry
    )
    db.add(log)

    # Update webhook stats
    webhook.last_delivery = datetime.utcnow()
    webhook.total_sent   += 1
    if status == "failed":
        webhook.failure_count += 1
    else:
        webhook.failure_count = 0  # reset on success

    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "event_id":   event_id,
        "event_type": event_type,
        "status":     status,
        "http_status": http_code,
        "latency_ms": latency_ms,
        "attempt":    attempt,
        "next_retry": next_retry.isoformat() if next_retry else None
    }


async def fire_event(
    db: Session,
    company_id: str,
    event_type: str,
    payload: dict
):
    """
    Fire an event to all active webhooks subscribed to it.
    Called throughout the app when events occur.
    """
    if event_type not in WEBHOOK_EVENTS:
        return

    webhooks = db.query(WebhookORM).filter(
        WebhookORM.company_id == company_id,
        WebhookORM.is_active == True,
        WebhookORM.is_deleted == False
    ).all()

    for webhook in webhooks:
        subscribed = json.loads(webhook.event_types or "[]")
        if event_type in subscribed or "*" in subscribed:
            await deliver_webhook(db, webhook, event_type, payload)


# ============================================================
# SECTION I — ABUSE DETECTION
# ============================================================

def detect_abuse(
    db: Session,
    company_id: str,
    api_key_id: str
) -> dict:
    """
    Detect abuse patterns:
    - Brute force (many failed attempts)
    - Suspicious volume (10x normal)
    - Key sharing (multiple IPs)
    """
    since = datetime.utcnow() - timedelta(hours=1)

    recent_calls = db.query(APIAuditLogORM).filter(
        APIAuditLogORM.company_id == company_id,
        APIAuditLogORM.api_key_id == api_key_id,
        APIAuditLogORM.created_at >= since
    ).all()

    total         = len(recent_calls)
    errors        = sum(1 for c in recent_calls if c.status_code >= 400)
    error_rate    = errors / max(total, 1)
    unique_ips    = len(set(c.ip_address for c in recent_calls if c.ip_address))

    flags = []
    if error_rate > 0.5 and total > 10:
        flags.append("high_error_rate")
    if total > 500:
        flags.append("suspicious_volume")
    if unique_ips > 10:
        flags.append("possible_key_sharing")

    return {
        "total_calls":  total,
        "error_rate":   round(error_rate, 3),
        "unique_ips":   unique_ips,
        "flags":        flags,
        "is_suspicious": len(flags) > 0
    }


# ============================================================
# SECTION I — API AUDIT LOGGING
# ============================================================

def log_api_call(
    db: Session,
    company_id: str,
    api_key_id: str,
    endpoint: str,
    method: str,
    status_code: int,
    latency_ms: float,
    ip_address: str = None,
    user_agent: str = None,
    error: str = None,
    cost_usd: float = 0.0
):
    """Log every external API call for compliance."""
    log = APIAuditLogORM(
        company_id=company_id,
        api_key_id=api_key_id,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        latency_ms=latency_ms,
        ip_address=ip_address,
        user_agent=user_agent,
        error=error,
        cost_usd=cost_usd
    )
    db.add(log)
    try:
        db.commit()
    except Exception:
        db.rollback()


# ============================================================
# HELPER — GET COMPANY FROM API KEY
# ============================================================

def get_company_from_api_key(
    db: Session,
    raw_key: str
) -> Optional[CompanyORM]:
    """Get company object from a validated API key."""
    key_hash = hash_api_key(raw_key)
    api_key  = db.query(APIKeyORM).filter(
        APIKeyORM.key_hash == key_hash,
        APIKeyORM.is_active == True
    ).first()
    if not api_key:
        return None
    return db.query(CompanyORM).filter(
        CompanyORM.id == api_key.company_id
    ).first()