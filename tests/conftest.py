"""Test fixtures for the Team DNA feature.

Builds a real FastAPI app against a throwaway SQLite file, with two separate
tenants (Acme / Globex) plus a second user inside Acme. That second user is the
one that catches the subtle tenancy bug: filtering on company_id alone looks
correct until a colleague reads your Team DNA.

The AI backend is never called — every test either stubs it or asserts on paths
that fail before reaching it.
"""
from __future__ import annotations

import os
import sys
import uuid
import tempfile
from pathlib import Path

import pytest

# The app is imported as the `app` PACKAGE (main.py does `from app.db import ...`,
# and production runs `uvicorn app.main:app`). Only the project root goes on the
# path — putting app/ itself on the path too would import db.py twice under two
# names, giving two SQLAlchemy Bases bound to two engines.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def _db_path():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="teamdna_test_")
    os.close(fd)
    os.environ["DATABASE_PATH"] = path
    # Keep the real engine well away from any live key.
    os.environ.pop("AZURE_OPENAI_API_KEY", None)
    os.environ.pop("AZURE_OPENAI_ENDPOINT", None)
    os.environ.pop("OPENAI_API_KEY", None)
    # main.py refuses to boot without a session secret unless ENV=development.
    os.environ["ENV"] = "development"
    os.environ.setdefault("SESSION_SECRET_KEY", "test-only-secret-not-a-real-one")
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture(scope="session")
def app_module(_db_path):
    """Import the app AFTER DATABASE_PATH is set so it binds to the temp DB."""
    from app import db as db_module
    db_module.init_db()
    from app import main
    return main


@pytest.fixture(scope="session")
def db_module(app_module):
    from app import db as db_module
    return db_module


@pytest.fixture
def session(db_module):
    s = db_module.SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _make_company(db_module, session, name: str):
    company_id = str(uuid.uuid4())
    session.add(db_module.CompanyORM(
        id=company_id, name=name, domain=f"{name.lower()}.test",
        api_key=f"key_{uuid.uuid4().hex}",          # NOT NULL in the real schema
        plan="business", is_active=True, is_deleted=False,
    ))
    session.commit()
    return company_id


def _make_user(db_module, session, company_id: str, email: str, role: str = "admin"):
    user_id = str(uuid.uuid4())
    session.add(db_module.CompanyUserORM(
        id=user_id, company_id=company_id, email=email, name=email.split("@")[0],
        password="not-a-real-hash", role=role, is_active=True, is_deleted=False,
        email_verified=True,
    ))
    session.commit()
    return user_id


def _make_role(db_module, session, company_id: str, user_id: str, title: str):
    role_id = str(uuid.uuid4())
    session.add(db_module.CompanyRoleORM(
        id=role_id, company_id=company_id, created_by=user_id,
        title=title, is_active=True, is_deleted=False,
    ))
    session.commit()
    return role_id


@pytest.fixture
def tenants(db_module, session):
    """Two tenants + a second user inside the first one.

    acme_user  / acme_role   — the "owner" in most tests
    acme_user2 / same company — a colleague; must NOT see acme_user's Team DNA
    globex_user/ globex_role  — a different tenant entirely
    """
    acme = _make_company(db_module, session, f"Acme{uuid.uuid4().hex[:6]}")
    globex = _make_company(db_module, session, f"Globex{uuid.uuid4().hex[:6]}")

    acme_user = _make_user(db_module, session, acme, f"owner-{uuid.uuid4().hex[:6]}@acme.test")
    acme_user2 = _make_user(db_module, session, acme, f"colleague-{uuid.uuid4().hex[:6]}@acme.test")
    globex_user = _make_user(db_module, session, globex, f"rival-{uuid.uuid4().hex[:6]}@globex.test")

    return {
        "acme": acme,
        "globex": globex,
        "acme_user": acme_user,
        "acme_user2": acme_user2,
        "globex_user": globex_user,
        "acme_role": _make_role(db_module, session, acme, acme_user, "Senior ML Engineer"),
        "globex_role": _make_role(db_module, session, globex, globex_user, "Senior ML Engineer"),
    }


@pytest.fixture
def client_factory(app_module, db_module):
    """Return a TestClient authenticated as a given user id.

    The Team DNA routes call require_recruiter_or_admin(request, db) directly
    (the codebase's convention) rather than through Depends(), so
    dependency_overrides does not intercept them. Instead we patch the function
    on app.main — team_dna_routes imports it lazily inside _current(), so the
    patch is picked up per call. Auth identity travels in an X-Test-User header
    so several differently-authenticated clients can coexist in one test.
    """
    from fastapi.testclient import TestClient
    from fastapi import HTTPException

    real = app_module.require_recruiter_or_admin

    def _patched(request=None, db=None):
        user_id = None
        if request is not None:
            try:
                user_id = request.headers.get("X-Test-User")
            except Exception:
                user_id = None
        if not user_id:
            raise HTTPException(status_code=401, detail="Not authenticated")
        s = db_module.SessionLocal()
        try:
            user = s.query(db_module.CompanyUserORM).filter(
                db_module.CompanyUserORM.id == user_id
            ).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found")
            s.expunge(user)
            return user
        finally:
            s.close()

    app_module.require_recruiter_or_admin = _patched

    def _make(user_id):
        headers = {"X-Test-User": user_id} if user_id else {}
        return TestClient(app_module.app, headers=headers)

    yield _make

    app_module.require_recruiter_or_admin = real
    app_module.app.dependency_overrides.clear()


@pytest.fixture
def as_acme(client_factory, tenants):
    return client_factory(tenants["acme_user"])


@pytest.fixture
def as_acme_colleague(client_factory, tenants):
    return client_factory(tenants["acme_user2"])


@pytest.fixture
def as_globex(client_factory, tenants):
    return client_factory(tenants["globex_user"])


@pytest.fixture
def seed_profiles(db_module, session):
    """Insert exemplar profiles directly, bypassing the upload endpoint."""
    def _seed(company_id, user_id, role_id, n=2):
        ids = []
        for i in range(n):
            pid = str(uuid.uuid4())
            session.add(db_module.TeamDNAProfileORM(
                id=pid, company_id=company_id, user_id=user_id, role_id=role_id,
                name=f"Exemplar {i + 1}",
                raw_text=f"Staff engineer {i + 1}. Owned the billing platform end to end, "
                         f"led a team of six, migrated it from a monolith to services. "
                         f"Python, Postgres, Kafka. Ten years, all in payments infrastructure.",
                source="paste",
            ))
            ids.append(pid)
        session.commit()
        return ids
    return _seed


@pytest.fixture
def seed_model(db_module, session):
    """Insert a ready-built Team DNA model so scoring paths can be exercised.

    The fingerprint is computed from whatever exemplars are actually in the DB
    for this company+role, so the model reads as a genuine CACHE HIT. A fixed
    string here would look fine but silently force a rebuild — and a rebuild
    calls the AI, which tests must never do.
    """
    import json
    from app.team_dna import fingerprint_profiles

    def _seed(company_id, user_id, role_id):
        payload = {
            "shared_traits": [
                {"trait": "End-to-end platform ownership",
                 "evidence": "Owned the billing platform end to end", "weight": 9},
                {"trait": "Monolith-to-services migration",
                 "evidence": "migrated it from a monolith to services", "weight": 7},
            ],
            "career_patterns": ["Long tenure inside one problem domain"],
            "anti_signals": ["No one here came from agency consulting"],
            "summary": "This team is built from long-tenure platform owners in payments.",
        }
        rows = session.query(db_module.TeamDNAProfileORM).filter(
            db_module.TeamDNAProfileORM.company_id == company_id,
            db_module.TeamDNAProfileORM.role_id == role_id,
            db_module.TeamDNAProfileORM.is_deleted == False,   # noqa: E712
        ).order_by(db_module.TeamDNAProfileORM.created_at.asc()).all()
        fingerprint = fingerprint_profiles(
            [{"id": r.id, "raw_text": r.raw_text} for r in rows]
        ) if rows else "no-profiles-fingerprint"

        mid = str(uuid.uuid4())
        session.add(db_module.TeamDNAModelORM(
            id=mid, company_id=company_id, user_id=user_id, role_id=role_id,
            extracted_traits=json.dumps(payload), summary=payload["summary"],
            source_fingerprint=fingerprint, profile_count=len(rows) or 2,
        ))
        session.commit()
        return mid, payload
    return _seed


@pytest.fixture
def seed_candidate(db_module, session):
    def _seed(company_id, user_id, name="Scored Person", score=96, tier="gold"):
        cid = str(uuid.uuid4())
        session.add(db_module.CompanyCandidateORM(
            id=cid, company_id=company_id, added_by=user_id, name=name,
            role="Senior ML Engineer", tier=tier, match_score=score,
            adaptability=88, focus_penalty=10, ai_analysis="…",
            shortlisted=False, partner_source="team_dna",
        ))
        session.commit()
        return cid
    return _seed
