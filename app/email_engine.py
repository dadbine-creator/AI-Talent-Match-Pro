# ============================================================
# app/email_engine.py
# Transactional email via Resend (https://resend.com).
#
# Sends through Resend's REST API using httpx (already a dependency) — no extra
# package to install. Stays a GRACEFUL NO-OP until RESEND_API_KEY is set, so
# register/reset/webhook flows never break before the key exists.
#
# Env vars:
#   RESEND_API_KEY  — from resend.com (required to actually send; never hardcode)
#   EMAIL_FROM      — verified sender, e.g. "AI Talent Match Pro <noreply@aitmp.io>"
#   APP_BASE_URL    — base URL for links in emails (default https://aitmp.io)
# ============================================================
from __future__ import annotations

import os
import logging
import httpx

logger = logging.getLogger(__name__)

RESEND_API_KEY  = os.getenv("RESEND_API_KEY", "").strip()
EMAIL_FROM      = os.getenv("EMAIL_FROM", "AI Talent Match Pro <noreply@aitmp.io>")
APP_BASE_URL    = os.getenv("APP_BASE_URL", "https://aitmp.io").rstrip("/")
RESEND_ENDPOINT = "https://api.resend.com/emails"


def is_configured() -> bool:
    """True once RESEND_API_KEY is set."""
    return bool(RESEND_API_KEY)


def send_email(to: str, subject: str, html: str, reply_to: str | None = None) -> dict:
    """
    Send one email via Resend. NEVER raises — returns a status dict.
    When RESEND_API_KEY is unset it's a clean no-op ({"configured": False}), so
    callers can fire-and-forget without guarding.
    """
    if not to or not RESEND_API_KEY:
        if not RESEND_API_KEY:
            logger.info("Resend not configured — skipped email '%s' to %s", subject, to)
        return {"ok": False, "configured": bool(RESEND_API_KEY), "skipped": True}

    payload = {"from": EMAIL_FROM, "to": [to], "subject": subject, "html": html}
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        r = httpx.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=15.0,
        )
        if r.status_code >= 400:
            logger.error("Resend send failed %s: %s", r.status_code, r.text[:300])
            return {"ok": False, "configured": True, "status": r.status_code, "error": r.text[:300]}
        data = {}
        try:
            data = r.json()
        except Exception:
            pass
        return {"ok": True, "configured": True, "id": data.get("id")}
    except Exception as e:
        logger.error("Resend send exception: %s", e)
        return {"ok": False, "configured": True, "error": str(e)}


# ── Shared HTML shell ───────────────────────────────────────
def _wrap(title: str, body_html: str, cta_text: str | None = None, cta_url: str | None = None) -> str:
    cta = ""
    if cta_text and cta_url:
        cta = (
            f'<div style="margin-top:24px;">'
            f'<a href="{cta_url}" style="display:inline-block;padding:12px 24px;background:#2563eb;'
            f'color:#ffffff;text-decoration:none;border-radius:10px;font-weight:600;font-size:15px;">{cta_text}</a>'
            f'</div>'
        )
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f4f6fb;font-family:-apple-system,'Segoe UI',Arial,sans-serif;">
  <div style="max-width:520px;margin:0 auto;padding:32px 20px;">
    <div style="font-weight:800;font-size:18px;color:#0d1f3a;margin-bottom:20px;">AI&nbsp;Talent&nbsp;Match·Pro</div>
    <div style="background:#ffffff;border:1px solid #e6e9f0;border-radius:16px;padding:28px;">
      <h1 style="font-size:20px;color:#0d1f3a;margin:0 0 12px;">{title}</h1>
      <div style="font-size:15px;color:#475069;line-height:1.6;">{body_html}</div>
      {cta}
    </div>
    <div style="font-size:12px;color:#98a0b3;text-align:center;margin-top:20px;">AI Talent Match Pro · <a href="{APP_BASE_URL}" style="color:#98a0b3;">aitmp.io</a></div>
  </div>
</body></html>"""


# ── 1. Email verification (on register) ─────────────────────
def send_verification_email(to: str, token: str, name: str = "") -> dict:
    """Welcome email sent on register — includes the one-click verification link."""
    url = f"{APP_BASE_URL}/verify-email?token={token}"
    body = (f"Hi {name or 'there'},<br><br>Welcome to AI Talent Match Pro — glad you're here. "
            f"Paste a job description and our GPT-4o engine scores your candidates into "
            f"<strong>Gold</strong>, <strong>Silver</strong>, and <strong>Bronze</strong>, with the reasoning "
            f"behind every match.<br><br>Confirm your email to finish setting up your workspace "
            f"(this link expires in 24 hours).")
    return send_email(to, "Welcome to AI Talent Match Pro — verify your email",
                      _wrap("Welcome to AI Talent Match Pro", body, "Verify email & get started", url))


# ── 2. Password reset ───────────────────────────────────────
def send_password_reset_email(to: str, token: str, name: str = "") -> dict:
    url = f"{APP_BASE_URL}/reset-password?token={token}"
    body = (f"Hi {name or 'there'},<br><br>We received a request to reset your password. "
            f"This link expires in 1 hour. If you didn't request this, you can safely ignore this email — "
            f"your password won't change.")
    return send_email(to, "Reset your password — AI Talent Match Pro",
                      _wrap("Reset your password", body, "Reset password", url))


# ── 3. Payment receipt (after successful payment) ───────────
def send_payment_receipt(to: str, name: str = "", plan: str = "", amount: str = "", invoice_url: str | None = None) -> dict:
    body = (f"Hi {name or 'there'},<br><br>Thanks for your payment — your "
            f"<strong>{plan or 'subscription'}</strong> plan is now active.<br><br>"
            f"Amount charged: <strong>{amount or '—'}</strong>")
    return send_email(to, "Your payment receipt — AI Talent Match Pro",
                      _wrap("Payment received", body,
                            "View invoice" if invoice_url else "Open your workspace",
                            invoice_url or f"{APP_BASE_URL}/workspace"))


# ── 3b. Trial lifecycle emails (card-required trial) ────────
def send_welcome_free(to: str, name: str = "") -> dict:
    """Sent when a Free account is created.

    Replaces the old card-on-file trial email. There is no trial, no card and
    no countdown, so this says none of those things.
    """
    body = (f"Hi {name or 'there'},<br><br>Your <strong>Free</strong> account is ready — "
            f"no card, no expiry.<br><br>It covers <strong>one active role</strong> and "
            f"<strong>100 candidates scored a month</strong>. To get started, add two to five "
            f"people already on your team who are great at the role you're hiring for — the "
            f"engine learns what they have in common and ranks new candidates against it.")
    return send_email(to, "Your account is ready — AI Talent Match Pro",
                      _wrap("Welcome to AI Talent Match Pro", body,
                            "Open your workspace", f"{APP_BASE_URL}/workspace"))


def send_limit_reached(to: str, name: str = "", limit: str = "", upgrade_to: str = "",
                       price: str = "") -> dict:
    """Sent when a Free account hits a limit.

    Names the limit that was hit and the specific tier that removes it — never
    a vague "upgrade your plan".
    """
    upgrade = (f"<br><br><strong>{upgrade_to}</strong> ({price}/mo) removes it."
               if upgrade_to else "")
    body = (f"Hi {name or 'there'},<br><br>You've reached the limit on your Free plan: "
            f"<strong>{limit or 'your monthly allowance'}</strong>.{upgrade}<br><br>"
            f"Nothing has been deleted and your Team DNA is untouched — you can pick up "
            f"exactly where you left off.")
    return send_email(to, "You've hit your Free plan limit — AI Talent Match Pro",
                      _wrap("You've reached a Free plan limit", body,
                            "See the plans", f"{APP_BASE_URL}/plans"))


# ── 4. "Candidate replied YES" notification to HR ───────────
def send_candidate_reply_notification(to: str, candidate_name: str = "", role: str = "", hr_name: str = "") -> dict:
    body = (f"Hi {hr_name or 'there'},<br><br><strong>{candidate_name or 'A candidate'}</strong> "
            f"replied <strong>YES</strong> to your outreach"
            f"{f' for {role}' if role else ''}. They're interested — time to take the conversation forward.")
    return send_email(to, f"🎉 {candidate_name or 'A candidate'} said YES — AI Talent Match Pro",
                      _wrap("A candidate said YES", body, "Open your workspace", f"{APP_BASE_URL}/workspace"))
