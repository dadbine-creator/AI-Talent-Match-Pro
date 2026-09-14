# team_dna_routes.py
# ============================================================
# AI Talent Match Pro — Team DNA endpoints
#
# Kept in its own APIRouter so main.py needs a 2-line change rather than a
# 500-line one. Nothing here modifies an existing route.
#
# TENANCY — the rule for every query in this file:
#   filter on company_id, always, no exceptions.
# Team DNA is a property of the company's TEAM: colleagues share one model per
# role, contribute exemplars to the same pool, and calibrate it with each
# other's verdicts. user_id is still written to every row for audit (who added
# this exemplar, who gave this verdict) but never scopes a read.
# The tests assert both halves: a colleague SEES the model, another tenant does NOT.
# ============================================================
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
# Starlette's form parser yields starlette.datastructures.UploadFile.
# fastapi.UploadFile is a SUBCLASS of it, so isinstance(x, fastapi.UploadFile)
# is False for real uploads — check against the Starlette base.
from starlette.datastructures import UploadFile
from sqlalchemy.orm import Session

from app.db import (
    get_db,
    CandidateFeedbackORM,
    CompanyCandidateORM,
    CompanyRoleORM,
    TeamDNAModelORM,
    TeamDNAProfileORM,
)
import app.cv_extract as cv_extract
import app.team_dna as team_dna_engine
from app.team_dna import TeamDNAError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["team-dna"])

# ── Limits ───────────────────────────────────────────────
MAX_BULK_FILES = 200
BULK_CONCURRENCY = 5          # semaphore width, per the spec
MAX_PASTE_CHARS = 30_000

# The batch picks. Reading 200 CVs is the work this product removes, and
# handing back 200 ranked cards does not remove it.
SHORTLIST_MAX = 10            # more than this stops being a shortlist
SHORTLIST_MIN_SCORE = 85      # the silver floor; bronze means "adjacent"


def select_shortlist(results: List[dict], limit: int = SHORTLIST_MAX) -> List[dict]:
    """The few worth an interview, out of everything just scored.

    Only silver and gold qualify. Padding to a round number with people nobody
    should call would make the pick worthless — the whole value is that the
    list is short and every name on it earned its place. A batch with nothing
    good in it picks nobody, and says so.

    Returns the same dict objects the caller passed in, so marking them marks
    the originals.
    """
    qualified = [r for r in results
                 if (r.get("match_score") or 0) >= SHORTLIST_MIN_SCORE]
    qualified.sort(key=lambda r: r.get("match_score") or 0, reverse=True)
    return qualified[:max(0, limit)]


def shortlist_summary(results: List[dict], picked: List[dict]) -> str:
    """One honest line about the pick — never a fabricated silver lining."""
    total = len(results)
    if not total:
        return "Nothing in this batch could be scored."
    if not picked:
        best = max((r.get("match_score") or 0) for r in results)
        return (f"None of the {total} clear the bar for an interview — the "
                f"closest scored {best}. This batch is worth widening, not working.")
    if len(picked) == 1:
        return f"One of the {total} is worth your time."
    return f"{len(picked)} of the {total} are worth your time."


# ============================================================
# AUTH + SCOPE
# ============================================================

def _current(request: Request, db: Session):
    """Resolve (company_id, user_id) for the caller, or 401/403.

    Imported lazily from main so this module can be imported by tests without
    dragging in the whole app at import time.
    """
    from app.main import require_recruiter_or_admin
    user = require_recruiter_or_admin(request, db)
    return user.company_id, user.id


def _plan(db: Session, company_id: str) -> str:
    from app.db import CompanyORM
    company = db.query(CompanyORM).filter(CompanyORM.id == company_id).first()
    return (company.plan if company else "free") or "free"


def _check_role(db: Session, company_id: str, role_id: str) -> None:
    """Reject a role_id belonging to another tenant.

    Roles are optional in the current product (the scoring flow takes a free-form
    job_id), so an id with no matching row is accepted as an opaque scope key.
    But if the row DOES exist and belongs to someone else, that is a cross-tenant
    reference and it is refused.
    """
    if not role_id:
        raise HTTPException(status_code=400, detail="role_id is required")
    row = db.query(CompanyRoleORM).filter(CompanyRoleORM.id == role_id).first()
    if row is not None and row.company_id != company_id:
        raise HTTPException(status_code=404, detail="Role not found")


def _rate_limit(company_id: str, endpoint: str, max_calls: int, window: int = 60) -> None:
    from app.main import check_rate_limit
    if not check_rate_limit(company_id, endpoint, max_calls=max_calls, window_seconds=window):
        raise HTTPException(status_code=429, detail="Too many requests — please wait a minute.")


# ============================================================
# 0. EXTRACTOR HEALTH
# ============================================================

@router.get("/extractors/health")
async def extractor_health():
    """Which CV formats this deployment can actually read.

    Unauthenticated on purpose: it returns three booleans about file-format
    support and nothing else — no versions, no paths, no config. It exists
    because pdfplumber and python-docx are optional imports, so a deploy that
    silently failed to install them looks identical to a healthy one from the
    outside until a customer uploads a PDF and gets an error.
    """
    return JSONResponse({
        "ok": True,
        "extractors": {
            "pdf":  cv_extract.pdfplumber is not None,
            "docx": cv_extract.docx is not None,
            "txt":  True,          # stdlib only — always available
        },
    })


# ============================================================
# 1. PROFILES — upload / list / delete exemplars
# ============================================================

@router.post("/team-dna/profiles")
async def upload_team_dna_profiles(
    request: Request,
    db: Session = Depends(get_db),
):
    """Upload 2-5 exemplar profiles for a role. Accepts JSON text or multipart files.

    JSON:      {"role_id": "...", "profiles": [{"name": "...", "text": "..."}]}
    Multipart: role_id=<id> + files=<PDF/DOCX/TXT>...
    """
    company_id, user_id = _current(request, db)
    _rate_limit(company_id, "team_dna_upload", max_calls=20)

    role_id, incoming = await _read_profile_upload(request)
    _check_role(db, company_id, role_id)

    # Attaching exemplars is one of the two things that make a role "active".
    # The plan limit is enforced HERE, at activation, so nobody is ever stopped
    # part-way through a search they already started.
    import app.roles as roles_engine
    roles_engine.check_can_activate(db, company_id, _plan(db, company_id), role_id)

    if not incoming:
        raise HTTPException(status_code=400, detail="No readable profile text found in upload")

    existing = db.query(TeamDNAProfileORM).filter(
        TeamDNAProfileORM.company_id == company_id,
        TeamDNAProfileORM.role_id == role_id,
        TeamDNAProfileORM.is_deleted == False,   # noqa: E712
    ).count()

    room = team_dna_engine.MAX_PROFILES - existing
    if room <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"This role already has the maximum of {team_dna_engine.MAX_PROFILES} exemplar profiles "
                   f"for your team. Remove one before adding another.",
        )
    if len(incoming) > room:
        raise HTTPException(
            status_code=400,
            detail=f"That would exceed the maximum of {team_dna_engine.MAX_PROFILES} exemplar profiles "
                   f"— room for {room} more.",
        )

    saved = []
    for item in incoming:
        profile_id = str(uuid.uuid4())
        db.add(TeamDNAProfileORM(
            id=profile_id,
            company_id=company_id,
            user_id=user_id,
            role_id=role_id,
            name=item["name"][:200],
            raw_text=item["text"][:MAX_PASTE_CHARS],
            source=item.get("source", "paste"),
        ))
        saved.append({"id": profile_id, "name": item["name"][:200], "chars": len(item["text"])})
    db.commit()

    total = existing + len(saved)
    return JSONResponse({
        "ok": True,
        "role_id": role_id,
        "added": saved,
        "profile_count": total,
        "ready_to_build": total >= team_dna_engine.MIN_PROFILES,
        "errors": [e for e in (item.get("error") for item in incoming) if e],
    })


def _uploaded_files(form) -> List[UploadFile]:
    """Every uploaded file in the form, under any field name.

    Accepting any field name (not just "files") keeps the endpoint working with
    whatever the browser's FormData happens to use.
    """
    out = []
    for key in form.keys():
        for value in form.getlist(key):
            if isinstance(value, UploadFile):
                out.append(value)
    return out


async def _read_profile_upload(request: Request):
    """Pull (role_id, profiles) out of either a JSON body or a multipart form."""
    content_type = (request.headers.get("content-type") or "").lower()
    out: List[dict] = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        role_id = (form.get("role_id") or "").strip()
        uploads = _uploaded_files(form)
        for upload in uploads:
            data = await upload.read()
            text, error = cv_extract.extract_text(upload.filename or "", data)
            if error:
                out.append({"name": upload.filename or "file", "text": "", "error": error})
                continue
            out.append({
                "name": cv_extract.guess_name(upload.filename or "", text),
                "text": text,
                "source": (upload.filename or "").rsplit(".", 1)[-1].lower(),
            })
        # Drop the failures — they are reported back, not stored.
        return role_id, [p for p in out if p.get("text")]

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Expected a JSON body or a multipart upload")

    role_id = (body.get("role_id") or "").strip()
    for i, raw in enumerate(body.get("profiles") or []):
        if isinstance(raw, str) and raw.strip():
            out.append({"name": f"Team member {i + 1}", "text": raw.strip(), "source": "paste"})
        elif isinstance(raw, dict) and (raw.get("text") or "").strip():
            out.append({
                "name": (raw.get("name") or f"Team member {i + 1}").strip(),
                "text": raw["text"].strip(),
                "source": "paste",
            })
    return role_id, out


@router.get("/team-dna/{role_id}")
async def get_team_dna(role_id: str, request: Request, db: Session = Depends(get_db)):
    """Return the built model + summary for this recruiter's role.

    Builds on demand when enough profiles exist and no cached model matches;
    otherwise returns the cached one. Never fabricates traits.
    """
    company_id, user_id = _current(request, db)
    _check_role(db, company_id, role_id)

    profiles = db.query(TeamDNAProfileORM).filter(
        TeamDNAProfileORM.company_id == company_id,
        TeamDNAProfileORM.role_id == role_id,
        TeamDNAProfileORM.is_deleted == False,   # noqa: E712
    ).order_by(TeamDNAProfileORM.created_at.asc()).all()

    profile_list = [
        {"id": p.id, "name": p.name, "chars": len(p.raw_text or ""),
         "source": p.source, "created_at": p.created_at.isoformat()}
        for p in profiles
    ]

    if len(profiles) < team_dna_engine.MIN_PROFILES:
        return JSONResponse({
            "ok": True,
            "role_id": role_id,
            "built": False,
            "profiles": profile_list,
            "profile_count": len(profiles),
            "min_profiles": team_dna_engine.MIN_PROFILES,
            "message": f"Add {team_dna_engine.MIN_PROFILES - len(profiles)} more exemplar "
                       f"profile(s) to build this role's Team DNA.",
        })

    try:
        model = await run_in_threadpool(
            team_dna_engine.build_team_dna, user_id, role_id, db, company_id
        )
    except TeamDNAError as e:
        return JSONResponse({"ok": False, "role_id": role_id, "built": False,
                             "profiles": profile_list, "error": str(e)}, status_code=503)

    return JSONResponse({
        "ok": True,
        "role_id": role_id,
        "built": True,
        "profiles": profile_list,
        "profile_count": len(profiles),
        "cached": model.get("cached", False),
        "shared_traits": model.get("shared_traits", []),
        "career_patterns": model.get("career_patterns", []),
        "anti_signals": model.get("anti_signals", []),
        "summary": model.get("summary", ""),
        "traits_dropped": model.get("traits_dropped", 0),
    })


@router.delete("/team-dna/profiles/{profile_id}")
async def delete_team_dna_profile(profile_id: str, request: Request, db: Session = Depends(get_db)):
    """Soft-delete one exemplar profile and invalidate the cached model."""
    company_id, user_id = _current(request, db)

    profile = db.query(TeamDNAProfileORM).filter(
        TeamDNAProfileORM.id == profile_id,
        TeamDNAProfileORM.company_id == company_id,
        TeamDNAProfileORM.is_deleted == False,   # noqa: E712
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    role_id = profile.role_id
    profile.is_deleted = True

    # The profile set changed, so the cached model is stale. Clearing the
    # fingerprint forces a rebuild on next read rather than serving stale traits.
    cached = db.query(TeamDNAModelORM).filter(
        TeamDNAModelORM.company_id == company_id,
        TeamDNAModelORM.role_id == role_id,
    ).first()
    if cached:
        cached.source_fingerprint = None
    db.commit()

    remaining = db.query(TeamDNAProfileORM).filter(
        TeamDNAProfileORM.company_id == company_id,
        TeamDNAProfileORM.role_id == role_id,
        TeamDNAProfileORM.is_deleted == False,   # noqa: E712
    ).count()

    return JSONResponse({"ok": True, "deleted": profile_id, "role_id": role_id,
                         "profile_count": remaining,
                         "ready_to_build": remaining >= team_dna_engine.MIN_PROFILES})


# ============================================================
# 2. SCORING
# ============================================================

def _calibration(db: Session, company_id: str, user_id: str, role_id: str) -> str:
    """Everything the team has taught us about this role, as prompt context.

    Two sources, deliberately ordered: thumbs up/down first, then REAL hiring
    outcomes. Outcomes go last because they are the stronger signal and the
    prompt says so — a hire is a judgement someone backed with a job offer,
    a thumbs-up is a judgement someone backed with a click.
    """
    from app.outcomes import outcome_context

    parts = [
        team_dna_engine.feedback_context(db, company_id, user_id, role_id),
        outcome_context(db, company_id, role_id),
    ]
    return "\n\n".join(p for p in parts if p)


def _load_model(db: Session, company_id: str, user_id: str, role_id: str) -> dict:
    """Load the company's cached Team DNA model, or 409 telling them to build it.

    user_id is unused for scoping — kept in the signature so callers read
    consistently with the rest of the module.
    """
    cached = db.query(TeamDNAModelORM).filter(
        TeamDNAModelORM.company_id == company_id,
        TeamDNAModelORM.role_id == role_id,
    ).first()
    if not cached or not cached.source_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="No Team DNA model for this role yet — upload exemplar profiles and open the "
                   "Team DNA panel to build it first.",
        )
    try:
        return json.loads(cached.extracted_traits)
    except (json.JSONDecodeError, TypeError, ValueError):
        raise HTTPException(status_code=503,
                            detail="The stored Team DNA model is unreadable — rebuild it from the panel.")


@router.post("/team-dna/score")
async def score_one_against_team_dna(request: Request, db: Session = Depends(get_db)):
    """Score ONE candidate against this role's Team DNA model."""
    company_id, user_id = _current(request, db)
    _rate_limit(company_id, "team_dna_score", max_calls=30)

    body = await request.json()
    role_id = (body.get("role_id") or "").strip()
    candidate_text = (body.get("candidate_text") or body.get("text") or "").strip()
    candidate_name = (body.get("name") or "").strip() or None
    job_description = (body.get("job_description") or "").strip() or None

    _check_role(db, company_id, role_id)
    if not candidate_text:
        raise HTTPException(status_code=400, detail="candidate_text is required")

    model = _load_model(db, company_id, user_id, role_id)
    calibration = _calibration(db, company_id, user_id, role_id)

    from app.ai_engine import score_against_team_dna
    start = time.time()
    try:
        result = await run_in_threadpool(
            score_against_team_dna, candidate_text[:MAX_PASTE_CHARS], model,
            job_description, candidate_name, calibration,
        )
    except ValueError as e:
        # Unparseable model output — honest error, never a fabricated score.
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        raise HTTPException(status_code=503,
                            detail="AI scoring engine temporarily unavailable — please retry.")

    candidate_id = _persist_candidate(db, company_id, user_id, role_id, result)
    db.commit()

    return JSONResponse({
        "ok": True,
        "role_id": role_id,
        "scored_against": "team_dna",
        "result": {**result, "id": candidate_id},
        "latency_ms": round((time.time() - start) * 1000, 2),
    })


def _persist_candidate(db: Session, company_id: str, user_id: str,
                       role_id: str, result: dict) -> str:
    """Save a scored candidate so feedback can reference it by id."""
    candidate_id = str(uuid.uuid4())
    role_row = db.query(CompanyRoleORM).filter(CompanyRoleORM.id == role_id).first()
    db.add(CompanyCandidateORM(
        id=candidate_id,
        company_id=company_id,
        added_by=user_id,
        name=result.get("name") or "Candidate",
        role=(role_row.title if role_row else "Team DNA match"),
        tier=result.get("tier", "bronze"),
        match_score=result.get("match_score", 0),
        adaptability=result.get("adaptability", 0),
        focus_penalty=result.get("focus_penalty", 0),
        ai_analysis=result.get("ai_analysis", ""),
        silent_skill=result.get("silent_skill"),
        notes="",
        shortlisted=bool(result.get("shortlisted")),
        job_id=(role_row.id if role_row else None),
        partner_source="team_dna",
    ))
    return candidate_id


# ============================================================
# 3. BULK — up to 200 CVs, concurrency 5, poll for results
# ============================================================
#
# Design note: the spec says "stream or poll — do not block for minutes on one
# request". This uses poll. The POST parses + validates every file synchronously
# (fast, no AI), registers a job, and returns immediately with a job_id. Scoring
# runs in a background task behind an asyncio.Semaphore(5); the client polls
# GET /api/candidates/bulk/{job_id} for progress and ranked results.
#
# Jobs live in memory: a restart loses in-flight progress, which is the right
# trade for a feature with no queue infrastructure. Scored candidates are
# persisted to the DB as they complete, so nothing scored is ever lost.

_BULK_JOBS: dict = {}
_BULK_JOB_TTL_SECONDS = 3600


def _reap_bulk_jobs() -> None:
    cutoff = time.time() - _BULK_JOB_TTL_SECONDS
    for job_id in [k for k, v in _BULK_JOBS.items() if v.get("created_ts", 0) < cutoff]:
        _BULK_JOBS.pop(job_id, None)


@router.post("/candidates/bulk")
async def bulk_score_candidates(
    request: Request,
    db: Session = Depends(get_db),
):
    """Accept up to 200 CVs, parse them, and score all against this role's Team DNA.

    Returns a job_id immediately. Poll GET /api/candidates/bulk/{job_id}.
    """
    company_id, user_id = _current(request, db)
    _rate_limit(company_id, "candidates_bulk", max_calls=5)
    _reap_bulk_jobs()

    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" not in content_type:
        raise HTTPException(status_code=400,
                            detail="Bulk upload expects a multipart/form-data request with files")

    form = await request.form()
    role_id = (form.get("role_id") or "").strip()
    job_description = (form.get("job_description") or "").strip() or None
    uploads = _uploaded_files(form)

    _check_role(db, company_id, role_id)
    if not uploads:
        raise HTTPException(status_code=400, detail="No files received")
    if len(uploads) > MAX_BULK_FILES:
        raise HTTPException(status_code=400,
                            detail=f"Maximum {MAX_BULK_FILES} CVs per bulk upload — you sent {len(uploads)}")

    # Free-tier batch cap. Named tier, named limit — never a silent truncation.
    from app.main import PLANS
    plan_key = _plan(db, company_id)
    batch_cap = PLANS.get(plan_key, PLANS["free"]).get("bulk_batch_limit", MAX_BULK_FILES)
    if len(uploads) > batch_cap:
        raise HTTPException(status_code=402, detail=(
            f"The {PLANS.get(plan_key, PLANS['free'])['name']} plan scores {batch_cap} CVs "
            f"per batch and you sent {len(uploads)}. "
            f"Single (${PLANS['single']['price_monthly']}/mo) raises this to {MAX_BULK_FILES}."))

    # Model must exist BEFORE we accept the work, so we fail fast rather than
    # after the recruiter has waited on 200 files.
    model = _load_model(db, company_id, user_id, role_id)
    calibration = _calibration(db, company_id, user_id, role_id)

    parsed: List[dict] = []
    failed: List[dict] = []
    for upload in uploads:
        data = await upload.read()
        text, error = cv_extract.extract_text(upload.filename or "", data)
        if error:
            # One malformed file never fails the batch.
            failed.append({"filename": upload.filename or "unknown", "error": error})
            continue
        parsed.append({
            "filename": upload.filename or "unknown",
            "name": cv_extract.guess_name(upload.filename or "", text),
            "text": text,
        })

    if not parsed:
        raise HTTPException(
            status_code=400,
            detail=f"None of the {len(uploads)} file(s) could be read. "
                   f"First error: {failed[0]['error'] if failed else 'unknown'}",
        )

    job_id = str(uuid.uuid4())
    _BULK_JOBS[job_id] = {
        "job_id": job_id, "company_id": company_id, "user_id": user_id, "role_id": role_id,
        "status": "running", "total": len(parsed), "completed": 0,
        "results": [], "failed": list(failed),
        "picked_count": 0, "pick_summary": "",
        "created_ts": time.time(), "created_at": datetime.utcnow().isoformat(),
    }

    asyncio.create_task(_run_bulk_job(job_id, parsed, model, job_description, calibration))

    return JSONResponse({
        "ok": True, "job_id": job_id, "role_id": role_id,
        "accepted": len(parsed), "rejected": len(failed), "rejected_files": failed,
        "status": "running", "poll_url": f"/api/candidates/bulk/{job_id}",
    }, status_code=202)


async def _run_bulk_job(job_id: str, parsed: List[dict], model: dict,
                        job_description: Optional[str], calibration: str) -> None:
    """Score every parsed CV behind a semaphore of 5."""
    from app.ai_engine import score_against_team_dna
    from app.db import SessionLocal

    job = _BULK_JOBS.get(job_id)
    if not job:
        return
    semaphore = asyncio.Semaphore(BULK_CONCURRENCY)

    async def score_one(item: dict):
        async with semaphore:
            try:
                result = await run_in_threadpool(
                    score_against_team_dna, item["text"], model,
                    job_description, item["name"], calibration,
                )
                return {"ok": True, "filename": item["filename"], "result": result}
            except ValueError as e:
                return {"ok": False, "filename": item["filename"], "error": str(e)}
            except Exception as e:
                logger.warning("bulk %s: scoring failed for %s: %s", job_id, item["filename"], e)
                return {"ok": False, "filename": item["filename"],
                        "error": "AI scoring engine unavailable for this CV"}

    try:
        tasks = [asyncio.create_task(score_one(item)) for item in parsed]
        for coro in asyncio.as_completed(tasks):
            outcome = await coro
            live = _BULK_JOBS.get(job_id)
            if live is None:
                return                                   # job reaped mid-flight
            live["completed"] += 1
            if outcome["ok"]:
                live["results"].append({**outcome["result"], "filename": outcome["filename"]})
            else:
                live["failed"].append({"filename": outcome["filename"], "error": outcome["error"]})

        # Persist everything scored, in one session, ranked.
        live = _BULK_JOBS.get(job_id)
        if live is None:
            return
        live["results"].sort(key=lambda r: r.get("match_score", 0), reverse=True)

        # Pick before persisting, so the chosen rows are written shortlisted
        # rather than needing a second pass to update them.
        for result in live["results"]:
            result["shortlisted"] = False
        picked = select_shortlist(live["results"])
        for result in picked:
            result["shortlisted"] = True
        live["picked_count"] = len(picked)
        live["pick_summary"] = shortlist_summary(live["results"], picked)

        db = SessionLocal()
        try:
            for result in live["results"]:
                result["id"] = _persist_candidate(
                    db, live["company_id"], live["user_id"], live["role_id"], result
                )
            db.commit()
        except Exception as e:                            # pragma: no cover - defensive
            logger.warning("bulk %s: persist failed: %s", job_id, e)
            db.rollback()
        finally:
            db.close()

        live["status"] = "complete"
    except Exception as e:                                # pragma: no cover - defensive
        logger.exception("bulk %s: job crashed: %s", job_id, e)
        live = _BULK_JOBS.get(job_id)
        if live is not None:
            live["status"] = "failed"
            live["error"] = "The bulk scoring job failed — please retry."


@router.get("/candidates/bulk/{job_id}")
async def bulk_job_status(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Poll a bulk job. Scoped: a job is only visible to the tenant+user who made it."""
    company_id, user_id = _current(request, db)

    job = _BULK_JOBS.get(job_id)
    # Company-scoped like everything else, so a colleague can watch a batch a
    # teammate started. Same 404 whether the job is missing or another tenant's
    # — no existence oracle.
    if not job or job["company_id"] != company_id:
        raise HTTPException(status_code=404, detail="Job not found")

    return JSONResponse({
        "ok": True,
        "job_id": job_id,
        "role_id": job["role_id"],
        "status": job["status"],
        "total": job["total"],
        "completed": job["completed"],
        "progress": round(job["completed"] / job["total"] * 100, 1) if job["total"] else 0.0,
        "results": job["results"] if job["status"] == "complete" else [],
        "picked": ([r for r in job["results"] if r.get("shortlisted")]
                   if job["status"] == "complete" else []),
        "picked_count": job.get("picked_count", 0),
        "pick_summary": job.get("pick_summary", ""),
        "shortlist_max": SHORTLIST_MAX,
        "failed": job["failed"],
        "error": job.get("error"),
    })


# ============================================================
# 4. FEEDBACK
# ============================================================

@router.post("/candidates/feedback")
async def record_candidate_feedback(request: Request, db: Session = Depends(get_db)):
    """Record a good/bad verdict. Replayed into later prompts as calibration."""
    company_id, user_id = _current(request, db)

    body = await request.json()
    role_id = (body.get("role_id") or "").strip()
    candidate_id = (body.get("candidate_id") or "").strip()
    verdict = (body.get("verdict") or "").strip().lower()
    reason = (body.get("reason") or "").strip() or None

    _check_role(db, company_id, role_id)
    if verdict not in ("good", "bad"):
        raise HTTPException(status_code=400, detail="verdict must be 'good' or 'bad'")
    if not candidate_id:
        raise HTTPException(status_code=400, detail="candidate_id is required")

    # The candidate must belong to the caller's tenant.
    candidate = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.id == candidate_id,
        CompanyCandidateORM.company_id == company_id,
    ).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    feedback_id = str(uuid.uuid4())
    db.add(CandidateFeedbackORM(
        id=feedback_id,
        company_id=company_id,
        user_id=user_id,
        role_id=role_id,
        candidate_id=candidate_id,
        verdict=verdict,
        reason=(reason[:1000] if reason else None),
        candidate_name=candidate.name,
    ))
    db.commit()

    total = db.query(CandidateFeedbackORM).filter(
        CandidateFeedbackORM.company_id == company_id,
        CandidateFeedbackORM.role_id == role_id,
    ).count()

    return JSONResponse({
        "ok": True, "id": feedback_id, "verdict": verdict, "feedback_count": total,
        "message": "Noted — future scoring for this role is calibrated on your verdicts.",
    })


@router.get("/team-dna/{role_id}/feedback")
async def list_candidate_feedback(role_id: str, request: Request, db: Session = Depends(get_db)):
    """List this recruiter's verdicts for a role — the calibration set, made visible."""
    company_id, user_id = _current(request, db)
    _check_role(db, company_id, role_id)

    rows = db.query(CandidateFeedbackORM).filter(
        CandidateFeedbackORM.company_id == company_id,
        CandidateFeedbackORM.role_id == role_id,
    ).order_by(CandidateFeedbackORM.created_at.desc()).limit(
        team_dna_engine.MAX_FEEDBACK_EXAMPLES
    ).all()

    return JSONResponse({
        "ok": True, "role_id": role_id, "count": len(rows),
        "feedback": [{
            "id": r.id, "candidate_id": r.candidate_id, "candidate_name": r.candidate_name,
            "verdict": r.verdict, "reason": r.reason, "created_at": r.created_at.isoformat(),
        } for r in rows],
    })


# ============================================================
# 5. ROLES — minimal list/create so the panel has something to attach to
# ============================================================
#
# The workspace has no roles list UI today (roles exist as a table, but the
# scoring flow only takes an optional job_id). Team DNA is scoped per role, so
# the panel needs a role to hang off. These two endpoints are the smallest thing
# that makes the feature usable; neither touches an existing route.

@router.get("/team-dna-roles")
async def list_roles_for_team_dna(request: Request, db: Session = Depends(get_db)):
    company_id, user_id = _current(request, db)
    roles = db.query(CompanyRoleORM).filter(
        CompanyRoleORM.company_id == company_id,
        CompanyRoleORM.is_deleted == False,   # noqa: E712
    ).order_by(CompanyRoleORM.created_at.desc()).limit(100).all()

    out = []
    for role in roles:
        count = db.query(TeamDNAProfileORM).filter(
            TeamDNAProfileORM.company_id == company_id,
            TeamDNAProfileORM.role_id == role.id,
            TeamDNAProfileORM.is_deleted == False,   # noqa: E712
        ).count()
        out.append({"id": role.id, "title": role.title, "location": role.location,
                    "dna_profile_count": count})
    return JSONResponse({"ok": True, "roles": out})


@router.post("/team-dna-roles")
async def create_role_for_team_dna(request: Request, db: Session = Depends(get_db)):
    company_id, user_id = _current(request, db)
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    role_id = str(uuid.uuid4())
    db.add(CompanyRoleORM(
        id=role_id,
        company_id=company_id,
        created_by=user_id,
        title=title[:200],
        description=(body.get("description") or "").strip() or None,
        location=(body.get("location") or "").strip() or None,
    ))
    db.commit()
    return JSONResponse({"ok": True, "id": role_id, "title": title[:200]}, status_code=201)
