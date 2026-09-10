# outcomes_routes.py
# ============================================================
# AI Talent Match Pro — hiring outcome endpoints
#
# Own APIRouter so main.py takes a 2-line change. Nothing here modifies an
# existing route.
#
# TENANCY: every query filters on company_id, matching the Team DNA
# convention. user_id is recorded for audit and never scopes a read.
# ============================================================
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import (
    get_db,
    CandidateOutcomeORM,
    CompanyCandidateORM,
    CompanyRoleORM,
)
import app.outcomes as outcomes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["outcomes"])


def _current(request: Request, db: Session):
    from app.main import require_recruiter_or_admin
    user = require_recruiter_or_admin(request, db)
    return user.company_id, user.id


def _check_role(db: Session, company_id: str, role_id: str) -> None:
    """Reject a role_id belonging to another tenant. Mirrors team_dna_routes."""
    if not role_id:
        raise HTTPException(status_code=400, detail="role_id is required")
    row = db.query(CompanyRoleORM).filter(CompanyRoleORM.id == role_id).first()
    if row is not None and row.company_id != company_id:
        raise HTTPException(status_code=404, detail="Role not found")


def _serialize(row) -> dict:
    return {
        "id": row.id,
        "candidate_id": row.candidate_id,
        "role_id": row.role_id,
        "stage": row.stage,
        "furthest_stage": row.furthest_stage,
        "score_at_time": row.score_at_time,
        "tier_at_time": row.tier_at_time,
        "rejected_reason": row.rejected_reason,
        "hired_at": row.hired_at.isoformat() if row.hired_at else None,
        "still_employed": row.still_employed,
        "still_employed_check_at": (
            row.still_employed_check_at.isoformat() if row.still_employed_check_at else None
        ),
        "follow_up_due": outcomes.follow_up_due(row),
        "follow_up_date": outcomes.follow_up_date(row),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ============================================================
# POST /api/outcomes — create or update a candidate's stage
# ============================================================

@router.post("/outcomes")
async def record_outcome(request: Request, db: Session = Depends(get_db)):
    """Record where a candidate got to.

    On FIRST write the candidate's current score is snapshotted into
    score_at_time and never touched again — later re-scoring must not rewrite
    history, or the correlation this table exists for becomes meaningless.
    """
    company_id, user_id = _current(request, db)

    body = await request.json()
    role_id = (body.get("role_id") or "").strip()
    candidate_id = (body.get("candidate_id") or "").strip()
    stage = (body.get("stage") or "").strip().lower()
    rejected_reason = (body.get("rejected_reason") or "").strip() or None

    _check_role(db, company_id, role_id)
    if not candidate_id:
        raise HTTPException(status_code=400, detail="candidate_id is required")
    if stage not in outcomes.VALID_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"stage must be one of: {', '.join(outcomes.VALID_STAGES)}",
        )

    # The candidate must belong to the caller's tenant.
    candidate = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.id == candidate_id,
        CompanyCandidateORM.company_id == company_id,
    ).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    row = db.query(CandidateOutcomeORM).filter(
        CandidateOutcomeORM.company_id == company_id,
        CandidateOutcomeORM.role_id == role_id,
        CandidateOutcomeORM.candidate_id == candidate_id,
    ).first()

    created = row is None
    if created:
        row = CandidateOutcomeORM(
            id=str(uuid.uuid4()),
            company_id=company_id,
            user_id=user_id,
            role_id=role_id,
            candidate_id=candidate_id,
            # Frozen here, once.
            score_at_time=candidate.match_score,
            tier_at_time=candidate.tier,
            stage=stage,
            furthest_stage=outcomes.advance_furthest("sourced", stage),
        )
        db.add(row)
    else:
        # score_at_time / tier_at_time are deliberately NOT reassigned.
        row.furthest_stage = outcomes.advance_furthest(row.furthest_stage, stage)
        row.stage = stage
        row.updated_at = datetime.utcnow()

    if stage == "rejected":
        row.rejected_reason = rejected_reason
    if stage == "hired" and not row.hired_at:
        row.hired_at = datetime.utcnow()

    db.commit()
    db.refresh(row)

    return JSONResponse({
        "ok": True,
        "created": created,
        "outcome": _serialize(row),
    }, status_code=201 if created else 200)


# ============================================================
# PATCH /api/outcomes/{outcome_id}/retention — 12-month check
# ============================================================

@router.patch("/outcomes/{outcome_id}/retention")
async def record_retention_check(outcome_id: str, request: Request,
                                 db: Session = Depends(get_db)):
    """Answer the 12-month still-employed follow-up for a hired candidate."""
    company_id, _ = _current(request, db)

    body = await request.json()
    if "still_employed" not in body or not isinstance(body["still_employed"], bool):
        raise HTTPException(status_code=400, detail="still_employed (true/false) is required")

    row = db.query(CandidateOutcomeORM).filter(
        CandidateOutcomeORM.id == outcome_id,
        CandidateOutcomeORM.company_id == company_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Outcome not found")
    if row.stage != "hired":
        raise HTTPException(status_code=400,
                            detail="Retention checks only apply to hired candidates")

    row.still_employed = body["still_employed"]
    row.still_employed_check_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return JSONResponse({"ok": True, "outcome": _serialize(row)})


# ============================================================
# GET /api/outcomes/stats — aggregate, with the under-5 rule
# ============================================================
# Declared BEFORE /outcomes/{role_id} so the literal path wins the match —
# otherwise "stats" is swallowed as a role_id and this endpoint is unreachable.

@router.get("/outcomes/stats")
async def outcome_stats(request: Request, db: Session = Depends(get_db)):
    """Company-wide outcome stats by score band.

    Optional ?role_id= narrows to one role. Bands under the minimum sample
    return insufficient_data and carry no percentages at all.
    """
    company_id, _ = _current(request, db)
    role_id = (request.query_params.get("role_id") or "").strip()

    query = db.query(CandidateOutcomeORM).filter(
        CandidateOutcomeORM.company_id == company_id
    )
    if role_id:
        _check_role(db, company_id, role_id)
        query = query.filter(CandidateOutcomeORM.role_id == role_id)

    rows = query.all()
    stats = outcomes.compute_band_stats(rows)

    pending = [r for r in rows if outcomes.follow_up_due(r)]
    stats.update({
        "ok": True,
        "role_id": role_id or None,
        "retention_follow_ups_due": len(pending),
    })
    return JSONResponse(stats)


# ============================================================
# GET /api/outcomes/{role_id} — everything recorded for a role
# ============================================================

@router.get("/outcomes/{role_id}")
async def outcomes_for_role(role_id: str, request: Request, db: Session = Depends(get_db)):
    company_id, _ = _current(request, db)
    _check_role(db, company_id, role_id)

    rows = db.query(CandidateOutcomeORM).filter(
        CandidateOutcomeORM.company_id == company_id,
        CandidateOutcomeORM.role_id == role_id,
    ).order_by(CandidateOutcomeORM.updated_at.desc()).all()

    # Candidate names for display, resolved in one query.
    names = {}
    if rows:
        ids = [r.candidate_id for r in rows]
        for c in db.query(CompanyCandidateORM).filter(
            CompanyCandidateORM.company_id == company_id,
            CompanyCandidateORM.id.in_(ids),
        ).all():
            names[c.id] = c.name

    return JSONResponse({
        "ok": True,
        "role_id": role_id,
        "count": len(rows),
        "stages": outcomes.STAGE_ORDER + outcomes.TERMINAL_STAGES,
        "outcomes": [
            {**_serialize(r), "candidate_name": names.get(r.candidate_id)}
            for r in rows
        ],
    })
