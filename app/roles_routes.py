# roles_routes.py
# ============================================================
# AI Talent Match Pro — role listing, archiving, and plan usage
#
# Additive router. Archiving is what makes per-role pricing humane: you finish
# a hire, archive the role, and the slot comes back without losing the Team DNA
# or the candidates you scored against it.
# ============================================================
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db, CompanyRoleORM, CompanyORM
import app.roles as roles

router = APIRouter(prefix="/api", tags=["roles"])


def _current(request: Request, db: Session):
    from app.main import require_recruiter_or_admin
    user = require_recruiter_or_admin(request, db)
    company = db.query(CompanyORM).filter(CompanyORM.id == user.company_id).first()
    plan = (company.plan if company else "free") or "free"
    return user.company_id, user.id, plan


@router.get("/roles")
async def list_roles(request: Request, db: Session = Depends(get_db)):
    """Every role, with whether it currently counts against the plan."""
    company_id, _, plan = _current(request, db)

    rows = db.query(CompanyRoleORM).filter(
        CompanyRoleORM.company_id == company_id,
        CompanyRoleORM.is_deleted == False,   # noqa: E712
    ).order_by(CompanyRoleORM.created_at.desc()).all()

    active_ids = set(roles.active_role_ids(db, company_id))
    out = []
    for r in rows:
        archived = bool(getattr(r, "is_archived", False))
        out.append({
            "id": r.id,
            "title": r.title,
            "location": r.location,
            "archived": archived,
            "counts_toward_plan": r.id in active_ids,
            "has_work": roles.role_is_active(db, company_id, r.id),
            "created_at": r.created_at.isoformat(),
            "archived_at": r.archived_at.isoformat() if getattr(r, "archived_at", None) else None,
        })

    return JSONResponse({
        "ok": True,
        "roles": out,
        "usage": roles.usage_summary(db, company_id, plan),
    })


@router.post("/roles/{role_id}/archive")
async def archive_role(role_id: str, request: Request, db: Session = Depends(get_db)):
    """Archive a role. Frees the plan slot; deletes nothing."""
    company_id, _, plan = _current(request, db)

    role = db.query(CompanyRoleORM).filter(
        CompanyRoleORM.id == role_id,
        CompanyRoleORM.company_id == company_id,
        CompanyRoleORM.is_deleted == False,   # noqa: E712
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    role.is_archived = True
    role.archived_at = datetime.utcnow()
    db.commit()

    return JSONResponse({
        "ok": True, "role_id": role_id, "archived": True,
        "message": "Archived. Its Team DNA and candidates are kept — unarchive any time.",
        "usage": roles.usage_summary(db, company_id, plan),
    })


@router.post("/roles/{role_id}/unarchive")
async def unarchive_role(role_id: str, request: Request, db: Session = Depends(get_db)):
    """Bring a role back. Refused when it would exceed the plan's active-role limit."""
    company_id, _, plan = _current(request, db)

    role = db.query(CompanyRoleORM).filter(
        CompanyRoleORM.id == role_id,
        CompanyRoleORM.company_id == company_id,
        CompanyRoleORM.is_deleted == False,   # noqa: E712
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Only counts as an activation if the role actually has work attached.
    if roles.role_is_active(db, company_id, role_id):
        roles.check_can_activate(db, company_id, plan, role_id)

    role.is_archived = False
    role.archived_at = None
    db.commit()

    return JSONResponse({
        "ok": True, "role_id": role_id, "archived": False,
        "usage": roles.usage_summary(db, company_id, plan),
    })


@router.get("/plan/usage")
async def plan_usage(request: Request, db: Session = Depends(get_db)):
    """What's used, what's allowed, and which tier removes each limit."""
    company_id, _, plan = _current(request, db)
    return JSONResponse({"ok": True, **roles.usage_summary(db, company_id, plan)})
