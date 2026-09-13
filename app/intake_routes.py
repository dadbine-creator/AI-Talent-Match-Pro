# intake_routes.py
# ============================================================
# AI Talent Match Pro — inbound email endpoints
#
# One address per role. Forward an application to it and the CV is parsed,
# scored against that role's Team DNA, and added to the shortlist.
#
# The webhook is deliberately unauthenticated by session (a mail provider has
# no cookie) and authenticated by shared secret instead. It fails closed: with
# no secret configured, nothing is accepted.
# ============================================================
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.db import get_db, CompanyRoleORM, CompanyCandidateORM, CompanyORM
import app.email_intake as intake

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/intake", tags=["intake"])


def _current(request: Request, db: Session):
    from app.main import require_recruiter_or_admin
    user = require_recruiter_or_admin(request, db)
    return user.company_id, user.id


# ============================================================
# The role's address — shown to the recruiter
# ============================================================

@router.get("/address/{role_id}")
async def get_intake_address(role_id: str, request: Request, db: Session = Depends(get_db)):
    """The email address for this role, creating one on first request."""
    company_id, _ = _current(request, db)

    role = db.query(CompanyRoleORM).filter(
        CompanyRoleORM.id == role_id,
        CompanyRoleORM.company_id == company_id,
        CompanyRoleORM.is_deleted == False,   # noqa: E712
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    token = getattr(role, "intake_token", None)
    if not token:
        token = intake.make_role_token()
        role.intake_token = token
        db.commit()

    return JSONResponse({
        "ok": True,
        "role_id": role_id,
        "address": intake.intake_address(token),
        "configured": intake.is_configured(),
        "setup": None if intake.is_configured() else intake.setup_instructions(),
        "how_to_use": "Forward applications here, or set it as the destination "
                      "address on your job board listing. CVs are parsed and "
                      "scored automatically.",
    })


@router.post("/address/{role_id}/rotate")
async def rotate_intake_address(role_id: str, request: Request, db: Session = Depends(get_db)):
    """Issue a new address. Use when the old one starts attracting spam."""
    company_id, _ = _current(request, db)
    role = db.query(CompanyRoleORM).filter(
        CompanyRoleORM.id == role_id,
        CompanyRoleORM.company_id == company_id,
        CompanyRoleORM.is_deleted == False,   # noqa: E712
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    role.intake_token = intake.make_role_token()
    db.commit()
    return JSONResponse({"ok": True, "address": intake.intake_address(role.intake_token),
                         "message": "New address issued. The old one no longer accepts mail."})


# ============================================================
# The webhook the mail provider calls
# ============================================================

@router.post("/email")
async def receive_email(request: Request, db: Session = Depends(get_db)):
    """Inbound-parse webhook. Accepts SendGrid / Mailgun / Postmark shapes.

    Authenticated by shared secret, not by session — a mail provider has no
    cookie. Fails closed when EMAIL_INTAKE_SECRET is unset.
    """
    raw = await request.body()
    signature = (request.headers.get("X-Intake-Signature")
                 or request.headers.get("X-Webhook-Signature") or "")

    if not intake.is_configured():
        raise HTTPException(status_code=503,
                            detail="Email intake is not configured on this server.")
    if not intake.verify_webhook(raw, signature):
        # Same response whether the secret is wrong or absent — no oracle.
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await _parse_payload(request, raw)
    token = intake.parse_recipient(payload.get("to", ""))
    if not token:
        # Not an error worth retrying — the provider should stop resending.
        return JSONResponse({"ok": True, "ignored": "no role address in recipients"})

    role = db.query(CompanyRoleORM).filter(
        CompanyRoleORM.intake_token == token,
        CompanyRoleORM.is_deleted == False,   # noqa: E712
    ).first()
    if not role:
        return JSONResponse({"ok": True, "ignored": "unknown or revoked address"})

    candidates, skipped = intake.extract_candidates(
        payload.get("attachments", []), payload.get("text", ""), payload.get("from", "")
    )
    if not candidates:
        logger.info("intake: nothing readable in mail for role %s", role.id)
        return JSONResponse({"ok": True, "accepted": 0, "skipped": skipped,
                             "reason": "no readable CV found in the message"})

    company = db.query(CompanyORM).filter(CompanyORM.id == role.company_id).first()
    plan = (company.plan if company else "free") or "free"

    # Plan limits still apply to email arrivals. Over quota, the mail is
    # recorded as skipped rather than silently dropped or silently charged.
    import app.roles as roles_engine
    try:
        roles_engine.check_candidate_quota(db, role.company_id, plan, adding=len(candidates))
    except HTTPException as e:
        logger.info("intake: over quota for company %s", role.company_id)
        return JSONResponse({"ok": True, "accepted": 0, "over_quota": True,
                             "detail": e.detail}, status_code=200)

    saved = await _score_and_save(db, role, company, candidates)

    return JSONResponse({"ok": True, "role_id": role.id,
                         "accepted": len(saved), "skipped": skipped,
                         "candidates": saved})


async def _parse_payload(request: Request, raw: bytes) -> dict:
    """Normalise the three common inbound-parse shapes into one dict."""
    ctype = (request.headers.get("content-type") or "").lower()

    if "multipart/form-data" in ctype:          # SendGrid Inbound Parse
        form = await request.form()
        atts = []
        for key in form.keys():
            for value in form.getlist(key):
                if hasattr(value, "filename") and getattr(value, "filename", None):
                    atts.append({"filename": value.filename, "content": await value.read()})
        return {"to": form.get("to", ""), "from": form.get("from", ""),
                "subject": form.get("subject", ""), "text": form.get("text", ""),
                "attachments": atts}

    try:
        body = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return {"to": "", "from": "", "text": "", "attachments": []}

    # Postmark uses capitalised keys; Mailgun lowercase.
    atts = []
    for a in (body.get("Attachments") or body.get("attachments") or []):
        name = a.get("Name") or a.get("filename") or "attachment"
        content = a.get("Content") or a.get("content") or ""
        try:
            data = base64.b64decode(content) if isinstance(content, str) else bytes(content)
        except Exception:
            continue
        atts.append({"filename": name, "content": data})

    return {
        "to":      body.get("To") or body.get("to") or body.get("recipient") or "",
        "from":    body.get("From") or body.get("from") or body.get("sender") or "",
        "subject": body.get("Subject") or body.get("subject") or "",
        "text":    body.get("TextBody") or body.get("text") or body.get("body-plain") or "",
        "attachments": atts,
    }


async def _score_and_save(db: Session, role, company, candidates: list) -> list:
    """Score against the role's Team DNA when one exists; otherwise store
    unscored rather than inventing a number."""
    import uuid
    from app.db import TeamDNAModelORM

    model_row = db.query(TeamDNAModelORM).filter(
        TeamDNAModelORM.company_id == role.company_id,
        TeamDNAModelORM.role_id == role.id,
    ).first()

    model = None
    if model_row and model_row.source_fingerprint:
        try:
            model = json.loads(model_row.extracted_traits)
        except Exception:
            model = None

    calibration = ""
    if model:
        try:
            import app.team_dna as team_dna
            from app.outcomes import outcome_context
            calibration = "\n\n".join(x for x in (
                team_dna.feedback_context(db, role.company_id, model_row.user_id, role.id),
                outcome_context(db, role.company_id, role.id),
            ) if x)
        except Exception:
            calibration = ""

    saved = []
    for c in candidates:
        scored = None
        if model:
            try:
                from app.ai_engine import score_against_team_dna
                scored = await run_in_threadpool(
                    score_against_team_dna, c["text"], model, None, c["name"], calibration)
            except Exception as e:
                logger.warning("intake: scoring failed for %s: %s", c.get("filename"), e)
                scored = None

        cid = str(uuid.uuid4())
        db.add(CompanyCandidateORM(
            id=cid, company_id=role.company_id, added_by=role.created_by,
            name=(scored or c)["name"] if scored else c["name"],
            role=role.title,
            tier=(scored or {}).get("tier") or "bronze",
            match_score=(scored or {}).get("match_score") or 0,
            adaptability=(scored or {}).get("adaptability") or 0,
            focus_penalty=(scored or {}).get("focus_penalty") or 0,
            ai_analysis=(scored or {}).get("ai_analysis")
                        or "Arrived by email. Not scored — this role has no Team DNA yet.",
            silent_skill=(scored or {}).get("silent_skill"),
            shortlisted=False, job_id=role.id, partner_source="email_intake",
        ))
        saved.append({"id": cid, "name": c["name"],
                      "scored": scored is not None,
                      "match_score": (scored or {}).get("match_score")})
    db.commit()
    return saved


@router.get("/status")
async def intake_status(request: Request, db: Session = Depends(get_db)):
    """Whether email intake is switched on, and what is still needed."""
    _current(request, db)
    return JSONResponse({"ok": True, **intake.setup_instructions()})
