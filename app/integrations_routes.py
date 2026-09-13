# integrations_routes.py
# ============================================================
# AI Talent Match Pro — real ATS connections
#
# Replaces a UI that offered six integrations and delivered none. Only
# Greenhouse and Lever are offered here, because they are the only two with a
# working push implementation.
#
# The key difference from what was there before: the push actually happens on
# the server, using a credential stored server-side. The browser never holds
# the customer's ATS key and never gets it back.
# ============================================================
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db, CompanyCandidateORM
import app.partner_credentials as creds

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ats", tags=["ats"])


def _current(request: Request, db: Session):
    from app.main import require_recruiter_or_admin
    user = require_recruiter_or_admin(request, db)
    return user.company_id, user.id


@router.get("/partners")
async def list_partners(request: Request, db: Session = Depends(get_db)):
    """The ATS systems we can actually push to, and whether you're connected.

    Two entries, not six. We don't advertise a connection we can't make.
    """
    company_id, _ = _current(request, db)
    return JSONResponse({
        "ok": True,
        "partners": creds.list_partners(db, company_id),
        "labels": creds.PARTNER_LABELS,
    })


@router.post("/{partner}/connect")
async def connect_partner(partner: str, request: Request, db: Session = Depends(get_db)):
    """Store an ATS credential, encrypted, server-side.

    The key is never echoed back — the response carries a 4-character hint so
    the UI can show which key is in use without exposing it.
    """
    company_id, user_id = _current(request, db)
    body = await request.json()

    try:
        summary = creds.save_credential(
            db, company_id, user_id, partner,
            api_key=body.get("api_key", ""),
            account_ref=body.get("account_ref", ""),
        )
    except creds.CredentialError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.warning("ats connect failed for %s: %s", partner, e)
        raise HTTPException(status_code=503,
                            detail="Could not store that credential securely — please retry.")

    return JSONResponse({
        "ok": True,
        **summary,
        "message": f"{summary['name']} connected. Scores can now be pushed to it.",
    })


@router.delete("/{partner}")
async def disconnect_partner(partner: str, request: Request, db: Session = Depends(get_db)):
    company_id, _ = _current(request, db)
    removed = creds.disconnect(db, company_id, partner)
    if not removed:
        raise HTTPException(status_code=404, detail="Not connected")
    return JSONResponse({"ok": True, "partner": partner, "connected": False,
                         "message": "Disconnected. The stored key has been deleted."})


@router.post("/{partner}/push/{candidate_id}")
async def push_candidate(partner: str, candidate_id: str, request: Request,
                         db: Session = Depends(get_db)):
    """Push one candidate's score to the connected ATS — for real.

    This is the call the old UI never made. It fails loudly when the partner
    isn't connected, rather than reporting a success that didn't happen.
    """
    company_id, _ = _current(request, db)

    partner = (partner or "").strip().lower()
    if partner not in creds.SUPPORTED_PARTNERS:
        raise HTTPException(
            status_code=400,
            detail=f"{partner} isn't supported. Available: "
                   f"{', '.join(creds.PARTNER_LABELS[p]['name'] for p in creds.SUPPORTED_PARTNERS)}.",
        )

    api_key = creds.read_key(db, company_id, partner)
    if not api_key:
        raise HTTPException(
            status_code=409,
            detail=f"{creds.PARTNER_LABELS[partner]['name']} isn't connected. "
                   f"Add your API key in Integrations first.",
        )

    candidate = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.id == candidate_id,
        CompanyCandidateORM.company_id == company_id,
    ).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    from app.integrations_engine import push_to_partner
    result = await push_to_partner(
        db=db, company_id=company_id, candidate_id=candidate_id,
        partner=partner, partner_api_key=api_key,
    )

    if not result.get("ok"):
        # The partner API refused, or the candidate has no matching record
        # there. Report what happened — never a green toast over a failure.
        raise HTTPException(
            status_code=result.get("http_status") or 502,
            detail=result.get("error") or
                   f"{creds.PARTNER_LABELS[partner]['name']} rejected the update.",
        )

    return JSONResponse({"ok": True, "partner": partner, "candidate_id": candidate_id,
                         "latency_ms": result.get("latency_ms"),
                         "message": f"Pushed to {creds.PARTNER_LABELS[partner]['name']}."})
