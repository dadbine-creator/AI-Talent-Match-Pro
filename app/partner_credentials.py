# partner_credentials.py
# ============================================================
# AI Talent Match Pro — storing a customer's ATS API key safely
#
# Before this, the "Connect Greenhouse" button put the customer's API key in
# browser localStorage and never sent it anywhere. That was two problems at
# once: the key sat in a place any script on the page could read, and the
# connection was fiction.
#
# Here the key is encrypted at rest with a Fernet key derived from
# SESSION_SECRET_KEY, and is NEVER returned to the browser — reads get the
# last four characters so the UI can say "connected" without handing the
# secret back out.
#
# Only Greenhouse and Lever are supported, because they are the only two with
# real push implementations in integrations_engine.py.
# ============================================================
from __future__ import annotations

import base64
import hashlib
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# The partners with a genuine server-side implementation. Anything else is
# refused rather than stored — we don't collect credentials we can't use.
SUPPORTED_PARTNERS = ("greenhouse", "lever")

PARTNER_LABELS = {
    "greenhouse": {"name": "Greenhouse", "account_label": "Subdomain",
                   "account_hint": "yourcompany", "key_label": "Harvest API key"},
    "lever":      {"name": "Lever", "account_label": "Account ID",
                   "account_hint": "your-lever-account", "key_label": "API key"},
}


class CredentialError(Exception):
    """Raised when a credential cannot be stored or read back."""


def _fernet():
    """Fernet built from SESSION_SECRET_KEY.

    Rotating SESSION_SECRET_KEY makes stored credentials unreadable — that is
    the correct failure (the customer reconnects) rather than a silent
    fallback to plaintext.
    """
    from cryptography.fernet import Fernet

    secret = os.getenv("SESSION_SECRET_KEY", "")
    if not secret:
        raise CredentialError("Server is not configured to store credentials.")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def save_credential(db, company_id: str, user_id: str, partner: str,
                    api_key: str, account_ref: str = "") -> dict:
    """Encrypt and store one partner credential. Returns a SAFE summary."""
    from app.db import PartnerCredentialORM

    partner = (partner or "").strip().lower()
    if partner not in SUPPORTED_PARTNERS:
        raise CredentialError(
            f"{partner or 'That partner'} isn't supported. "
            f"Available: {', '.join(PARTNER_LABELS[p]['name'] for p in SUPPORTED_PARTNERS)}."
        )
    api_key = (api_key or "").strip()
    if len(api_key) < 8:
        raise CredentialError("That API key looks too short — check and paste it again.")

    enc = _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")
    hint = api_key[-4:]

    row = db.query(PartnerCredentialORM).filter(
        PartnerCredentialORM.company_id == company_id,
        PartnerCredentialORM.partner == partner,
    ).first()

    if row:
        row.secret_enc = enc
        row.key_hint = hint
        row.account_ref = (account_ref or "").strip() or row.account_ref
        row.user_id = user_id
        row.is_active = True
    else:
        db.add(PartnerCredentialORM(
            id=str(uuid.uuid4()), company_id=company_id, user_id=user_id,
            partner=partner, secret_enc=enc, key_hint=hint,
            account_ref=(account_ref or "").strip() or None, is_active=True,
        ))
    db.commit()
    return public_summary(db, company_id, partner)


def read_key(db, company_id: str, partner: str) -> Optional[str]:
    """Decrypt the stored key for server-side use only. Never send this to a client."""
    from app.db import PartnerCredentialORM
    from cryptography.fernet import InvalidToken

    row = db.query(PartnerCredentialORM).filter(
        PartnerCredentialORM.company_id == company_id,
        PartnerCredentialORM.partner == (partner or "").strip().lower(),
        PartnerCredentialORM.is_active == True,   # noqa: E712
    ).first()
    if not row:
        return None
    try:
        return _fernet().decrypt(row.secret_enc.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception):
        # Usually means SESSION_SECRET_KEY was rotated. Honest failure: the
        # customer is told to reconnect rather than the push failing obscurely.
        logger.warning("partner credential for %s/%s could not be decrypted",
                       company_id, partner)
        return None


def disconnect(db, company_id: str, partner: str) -> bool:
    from app.db import PartnerCredentialORM
    row = db.query(PartnerCredentialORM).filter(
        PartnerCredentialORM.company_id == company_id,
        PartnerCredentialORM.partner == (partner or "").strip().lower(),
    ).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def public_summary(db, company_id: str, partner: str) -> dict:
    """What the browser is allowed to see: connected or not, and a 4-char hint."""
    from app.db import PartnerCredentialORM
    meta = PARTNER_LABELS.get(partner, {"name": partner})
    row = db.query(PartnerCredentialORM).filter(
        PartnerCredentialORM.company_id == company_id,
        PartnerCredentialORM.partner == partner,
        PartnerCredentialORM.is_active == True,   # noqa: E712
    ).first()
    return {
        "partner": partner,
        "name": meta.get("name", partner),
        "connected": row is not None,
        "account_ref": row.account_ref if row else None,
        "key_hint": ("…" + row.key_hint) if row and row.key_hint else None,
        "connected_at": row.created_at.isoformat() if row else None,
    }


def list_partners(db, company_id: str) -> list:
    """Every SUPPORTED partner with its connection state.

    Deliberately does not list partners we have no implementation for — a
    customer should never be offered a connection that cannot do anything.
    """
    return [public_summary(db, company_id, p) for p in SUPPORTED_PARTNERS]
