# email_intake.py
# ============================================================
# AI Talent Match Pro — candidates arrive by email
#
# The friction in this product is that a recruiter has to download CV
# attachments and drag them in. This removes that: every role gets its own
# address, e.g. role-7f3a9c21@apply.aitmp.io. Forward an application there —
# or set it as the destination on AllJobs, Drushim, a careers page, anything
# — and the CV is parsed and scored on arrival.
#
# Deliberately provider-agnostic: it accepts the inbound-parse webhook shape
# used by SendGrid, Mailgun and Postmark. No partnership or API approval is
# needed from any job board, because every job board can send an email.
#
# SECURITY: the webhook is authenticated with a shared secret, and the role
# token is random and unguessable. Without both, anyone who learned the URL
# could inject candidates into a stranger's account.
# ============================================================
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

INTAKE_DOMAIN = os.getenv("EMAIL_INTAKE_DOMAIN", "apply.aitmp.io").strip()
INTAKE_SECRET = os.getenv("EMAIL_INTAKE_SECRET", "").strip()

# Attachment types worth trying to read. Everything else (images, calendar
# invites, signatures) is skipped silently rather than failing the message.
READABLE = (".pdf", ".docx", ".txt", ".text", ".md")

MAX_ATTACHMENTS_PER_EMAIL = 20


def make_role_token() -> str:
    """Unguessable token for a role's intake address.

    Must not be derived from the role id: the address ends up in job-board
    settings and forwarded mail headers, so it leaks easily. A leaked token
    should reveal nothing and be revocable on its own.
    """
    return secrets.token_urlsafe(12).replace("-", "").replace("_", "").lower()[:16]


def intake_address(token: str) -> str:
    return f"role-{token}@{INTAKE_DOMAIN}"


def parse_recipient(to_field: str) -> Optional[str]:
    """Pull the role token out of whatever the provider put in `to`.

    Handles 'Name <role-abc@d>', bare addresses, and comma-separated lists —
    a forwarded application often carries several recipients.
    """
    if not to_field:
        return None
    for m in re.finditer(r"role-([a-z0-9]{6,32})@", to_field, re.I):
        return m.group(1).lower()
    return None


def verify_webhook(raw_body: bytes, signature: str) -> bool:
    """Shared-secret check on the inbound webhook.

    Returns False when unset — an unauthenticated intake endpoint would let
    anyone inject candidates into any account, so it fails closed.
    """
    if not INTAKE_SECRET or not signature:
        return False
    expected = hmac.new(INTAKE_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def is_configured() -> bool:
    return bool(INTAKE_SECRET and INTAKE_DOMAIN)


def sender_name(from_field: str) -> str:
    """A display name from the From header, falling back to the local part."""
    if not from_field:
        return "Emailed candidate"
    m = re.match(r'\s*"?([^"<@]+?)"?\s*<', from_field)
    if m and m.group(1).strip():
        return m.group(1).strip()[:120]
    m = re.search(r"([A-Za-z0-9._%+-]+)@", from_field)
    if m:
        return m.group(1).replace(".", " ").replace("_", " ").title()[:120]
    return "Emailed candidate"


def extract_candidates(attachments: List[dict], body_text: str = "",
                       from_field: str = "") -> Tuple[List[dict], List[dict]]:
    """Turn one inbound email into candidates.

    attachments: [{"filename": str, "content": bytes}]
    Returns (candidates, skipped). Never raises — one unreadable attachment
    must not discard the rest of the message.
    """
    from app.cv_extract import extract_text, guess_name

    candidates, skipped = [], []
    for att in (attachments or [])[:MAX_ATTACHMENTS_PER_EMAIL]:
        filename = att.get("filename") or "attachment"
        if not filename.lower().endswith(READABLE):
            skipped.append({"filename": filename, "reason": "not a CV file type"})
            continue
        data = att.get("content") or b""
        text, error = extract_text(filename, data)
        if error:
            skipped.append({"filename": filename, "reason": error})
            continue
        candidates.append({
            "name": guess_name(filename, text) or sender_name(from_field),
            "text": text,
            "source": "email",
            "filename": filename,
        })

    # No readable attachment, but a substantial body — some applicants paste
    # their CV inline rather than attaching it.
    if not candidates and body_text and len(body_text.strip()) >= 400:
        candidates.append({
            "name": sender_name(from_field),
            "text": body_text.strip()[:30000],
            "source": "email_body",
            "filename": None,
        })

    return candidates, skipped


def setup_instructions() -> dict:
    """What the operator must configure. Stated plainly, including the parts
    we cannot do for them."""
    return {
        "domain": INTAKE_DOMAIN,
        "configured": is_configured(),
        "steps": [
            f"Add an MX record for {INTAKE_DOMAIN} pointing at an inbound-email "
            f"provider (SendGrid Inbound Parse, Mailgun Routes, or Postmark).",
            "Point that provider's inbound webhook at "
            "https://aitmp.io/api/intake/email",
            "Set EMAIL_INTAKE_SECRET on the App Service and configure the same "
            "secret as the webhook signature in the provider.",
            f"Optionally set EMAIL_INTAKE_DOMAIN if you use a domain other "
            f"than {INTAKE_DOMAIN}.",
        ],
        "note": "Resend (already used for outbound) does not receive mail — "
                "inbound needs one of the providers above.",
    }
