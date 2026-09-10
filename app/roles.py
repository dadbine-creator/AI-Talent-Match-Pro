# roles.py
# ============================================================
# AI Talent Match Pro — active-role accounting
#
# Pricing is per ACTIVE ROLE. A role counts as active when it has real work
# attached to it:
#     Team DNA exemplars, OR scored candidates.
# A role someone created and never used costs nothing. Archiving frees the
# slot and keeps every row.
#
# The limit is enforced at ACTIVATION — the moment a role first gets work
# attached — never during scoring. Blocking someone halfway through a search
# they already started is the worst possible moment to mention billing.
# ============================================================
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session


def _plans():
    from app.main import PLANS, UNLIMITED
    return PLANS, UNLIMITED


def role_is_active(db: Session, company_id: str, role_id: str) -> bool:
    """True when a role has work attached: Team DNA exemplars or scored candidates."""
    from app.db import TeamDNAProfileORM, CompanyCandidateORM

    has_dna = db.query(TeamDNAProfileORM.id).filter(
        TeamDNAProfileORM.company_id == company_id,
        TeamDNAProfileORM.role_id == role_id,
        TeamDNAProfileORM.is_deleted == False,   # noqa: E712
    ).first() is not None
    if has_dna:
        return True

    return db.query(CompanyCandidateORM.id).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.job_id == role_id,
        CompanyCandidateORM.is_deleted == False,   # noqa: E712
    ).first() is not None


def active_role_ids(db: Session, company_id: str) -> List[str]:
    """Every non-archived role for this company that currently counts."""
    from app.db import CompanyRoleORM

    roles = db.query(CompanyRoleORM).filter(
        CompanyRoleORM.company_id == company_id,
        CompanyRoleORM.is_deleted == False,     # noqa: E712
    ).all()
    out = []
    for r in roles:
        if getattr(r, "is_archived", False):
            continue
        if role_is_active(db, company_id, r.id):
            out.append(r.id)
    return out


def active_role_count(db: Session, company_id: str) -> int:
    return len(active_role_ids(db, company_id))


def role_limit(plan_key: str) -> int:
    PLANS, UNLIMITED = _plans()
    return PLANS.get(plan_key or "free", PLANS["free"]).get("active_roles", 1)


def next_tier_for_roles(plan_key: str) -> Optional[dict]:
    """The cheapest tier that allows more active roles than the current one.

    Used to name a specific upgrade rather than saying "upgrade your plan".
    """
    PLANS, UNLIMITED = _plans()
    current = role_limit(plan_key)
    candidates = [
        (PLANS[k]["price_monthly"], k, PLANS[k])
        for k in ("free", "single", "team", "agency")
        if PLANS[k].get("active_roles", 0) > current
    ]
    if not candidates:
        return None
    _, key, plan = sorted(candidates)[0]
    return {"key": key, "name": plan["name"],
            "price_monthly": plan["price_monthly"],
            "active_roles": plan["active_roles"]}


def check_can_activate(db: Session, company_id: str, plan_key: str, role_id: str) -> None:
    """Raise 402 if activating THIS role would exceed the plan's active-role limit.

    Called before attaching the first work to a role. A role that is already
    active passes free — you can always keep working on what you started.
    """
    from fastapi import HTTPException

    PLANS, UNLIMITED = _plans()
    limit = role_limit(plan_key)
    if limit >= UNLIMITED:
        return

    active = active_role_ids(db, company_id)
    if role_id in active:
        return                                  # already counted, not a new activation
    if len(active) < limit:
        return

    upgrade = next_tier_for_roles(plan_key)
    plan_name = PLANS.get(plan_key or "free", PLANS["free"])["name"]
    detail = (
        f"Your {plan_name} plan covers {limit} active role"
        f"{'s' if limit != 1 else ''} and you're using {len(active)}. "
        "Archive a role you've finished with to free the slot — archiving keeps all its data."
    )
    if upgrade:
        roles = ("unlimited active roles" if upgrade["active_roles"] >= UNLIMITED
                 else f"{upgrade['active_roles']} active roles")
        detail += f" Or move to {upgrade['name']} (${upgrade['price_monthly']}/mo) for {roles}."

    raise HTTPException(status_code=402, detail=detail)


def check_candidate_quota(db: Session, company_id: str, plan_key: str, adding: int = 1) -> None:
    """Free-tier monthly candidate cap. Paid plans have none.

    The window rolls from the company's signup anniversary date, so the counter
    resets on the day they joined rather than on the 1st.
    """
    from fastapi import HTTPException
    from app.db import CompanyORM, CompanyCandidateORM

    PLANS, UNLIMITED = _plans()
    plan = PLANS.get(plan_key or "free", PLANS["free"])
    cap = plan.get("candidates_per_month", UNLIMITED)
    if cap >= UNLIMITED:
        return

    company = db.query(CompanyORM).filter(CompanyORM.id == company_id).first()
    window_start = month_window_start(company.created_at if company else None)

    used = db.query(CompanyCandidateORM.id).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.created_at >= window_start,
    ).count()

    if used + adding <= cap:
        return

    raise HTTPException(
        status_code=402,
        detail=(
            f"The Free plan scores {cap} candidates a month and you've used {used} "
            f"since {window_start.date().isoformat()}. "
            f"Single (${PLANS['single']['price_monthly']}/mo) removes the cap entirely."
        ),
    )


def month_window_start(signup: Optional[datetime]) -> datetime:
    """Start of the current monthly window, anchored to the signup day-of-month."""
    now = datetime.utcnow()
    if not signup:
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    day = min(signup.day, 28)          # 28 keeps every month valid
    start = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    if start > now:                    # anniversary hasn't happened yet this month
        month = start.month - 1 or 12
        year = start.year - (1 if start.month == 1 else 0)
        start = start.replace(year=year, month=month)
    return start


def usage_summary(db: Session, company_id: str, plan_key: str) -> dict:
    """What the workspace shows: what's used, what's allowed, what removes the limit."""
    from app.db import CompanyORM, CompanyCandidateORM

    PLANS, UNLIMITED = _plans()
    plan = PLANS.get(plan_key or "free", PLANS["free"])
    active = active_role_ids(db, company_id)
    limit = plan.get("active_roles", 1)

    company = db.query(CompanyORM).filter(CompanyORM.id == company_id).first()
    window_start = month_window_start(company.created_at if company else None)
    cap = plan.get("candidates_per_month", UNLIMITED)
    used = 0
    if cap < UNLIMITED:
        used = db.query(CompanyCandidateORM.id).filter(
            CompanyCandidateORM.company_id == company_id,
            CompanyCandidateORM.created_at >= window_start,
        ).count()

    return {
        "plan": plan_key or "free",
        "plan_name": plan["name"],
        "active_roles": {
            "used": len(active),
            "limit": None if limit >= UNLIMITED else limit,
            "unlimited": limit >= UNLIMITED,
            "role_ids": active,
        },
        "candidates_this_month": {
            "used": used,
            "limit": None if cap >= UNLIMITED else cap,
            "unlimited": cap >= UNLIMITED,
            "window_start": window_start.isoformat(),
        },
        "bulk_batch_limit": plan.get("bulk_batch_limit", 200),
        "shared_team_dna": plan.get("shared_team_dna", True),
    }
