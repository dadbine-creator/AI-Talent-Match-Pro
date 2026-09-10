# ============================================================
# app/paddle_engine.py
# Paddle Billing (v2) integration — NEW, alongside Stripe (Stripe code untouched).
# Sandbox-first: PADDLE_ENV defaults to "sandbox".
#
# Env vars (set with your SANDBOX values first):
#   PADDLE_ENV              "sandbox" (default) | "production"
#   PADDLE_CLIENT_TOKEN     client-side token for Paddle.js (starts test_ in sandbox) — PUBLIC, safe in browser
#   PADDLE_SANDBOX_API_KEY  server-side API key (secret) — used for server→Paddle API calls
#   PADDLE_WEBHOOK_SECRET   notification destination signing secret (endpoint_secret_key)
#   PADDLE_PRICE_BUSINESS   sandbox price id (pri_...) for the Business plan
#   PADDLE_PRICE_CORPORATE  sandbox price id (pri_...) for the Corporate plan
#   PADDLE_VENDOR_ID        seller/vendor id (optional, informational)
#
# Nothing here sends or verifies anything until the env vars are set — it stays a
# graceful no-op so the app runs fine before Paddle is configured.
# ============================================================
from __future__ import annotations

import os
import hmac
import hashlib
import logging

logger = logging.getLogger(__name__)

PADDLE_ENV             = os.getenv("PADDLE_ENV", "sandbox").strip().lower()
PADDLE_CLIENT_TOKEN    = os.getenv("PADDLE_CLIENT_TOKEN", "").strip()
PADDLE_API_KEY         = (os.getenv("PADDLE_SANDBOX_API_KEY", "") or os.getenv("PADDLE_API_KEY", "")).strip()
PADDLE_WEBHOOK_SECRET  = os.getenv("PADDLE_WEBHOOK_SECRET", "").strip()
PADDLE_PRICE_BUSINESS  = os.getenv("PADDLE_PRICE_BUSINESS", "").strip()
PADDLE_PRICE_CORPORATE = os.getenv("PADDLE_PRICE_CORPORATE", "").strip()
PADDLE_VENDOR_ID       = os.getenv("PADDLE_VENDOR_ID", "").strip()

# Server-side API base — sandbox vs production
API_BASE = "https://sandbox-api.paddle.com" if PADDLE_ENV != "production" else "https://api.paddle.com"


# Placeholder values that have been sitting in the app settings as stand-ins for the
# real credentials. Treating them as "configured" opens a checkout that fails inside
# Paddle's overlay, which is worse than showing no checkout at all.
_PLACEHOLDERS = {
    "live_actual_token", "test_actual_token", "actual_token",
    "pri_actual_id", "actual_id",
    "your_token_here", "your_price_id", "changeme", "todo", "xxx",
}


def _real(value: str, *prefixes: str) -> bool:
    """A value counts as real only if it is non-empty, not a known placeholder,
    and (when prefixes are given) carries one of Paddle's id prefixes."""
    v = (value or "").strip()
    if not v or v.lower() in _PLACEHOLDERS:
        return False
    if prefixes and not v.startswith(prefixes):
        return False
    return True


def is_configured() -> bool:
    """True only once a REAL client token + at least one REAL price id are set.
    Paddle client tokens start with 'test_' (sandbox) or 'live_'; prices with 'pri_'."""
    return bool(
        _real(PADDLE_CLIENT_TOKEN, "test_", "live_")
        and (_real(PADDLE_PRICE_BUSINESS, "pri_") or _real(PADDLE_PRICE_CORPORATE, "pri_"))
    )


def public_config() -> dict:
    """Config safe to expose to the browser so Paddle.js can initialize.
    The client token is public by design; the API key/webhook secret are NEVER included."""
    ok = is_configured()
    return {
        "configured":  ok,
        "environment": "sandbox" if PADDLE_ENV != "production" else "production",
        # Only hand the browser credentials we believe are real — a placeholder
        # token would just make Paddle.js fail with a confusing overlay error.
        "token":       PADDLE_CLIENT_TOKEN if ok else None,
        "prices": {
            "business":  PADDLE_PRICE_BUSINESS  if ok and _real(PADDLE_PRICE_BUSINESS,  "pri_") else None,
            "corporate": PADDLE_PRICE_CORPORATE if ok and _real(PADDLE_PRICE_CORPORATE, "pri_") else None,
        },
    }


def plan_for_price(price_id: str) -> str | None:
    """Map a Paddle price id back to our plan name."""
    if not price_id:
        return None
    if price_id == PADDLE_PRICE_BUSINESS:
        return "business"
    if price_id == PADDLE_PRICE_CORPORATE:
        return "corporate"
    return None


def verify_webhook(raw_body: bytes, signature_header: str) -> bool:
    """
    Verify a Paddle Billing webhook signature.
    Header format: 'ts=<unix>;h1=<hex hmac_sha256(f"{ts}:{body}")>'.
    Returns False (never raises) if the secret is unset or the signature doesn't match.
    """
    if not PADDLE_WEBHOOK_SECRET or not signature_header:
        return False
    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(";") if "=" in p)
        ts, h1 = parts.get("ts"), parts.get("h1")
        if not ts or not h1:
            return False
        signed = f"{ts}:{raw_body.decode('utf-8')}".encode("utf-8")
        expected = hmac.new(PADDLE_WEBHOOK_SECRET.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, h1)
    except Exception as e:
        logger.error("Paddle webhook verification error: %s", e)
        return False
