"""Per-role pricing and active-role accounting.

Covers the rules that make the pricing model honest:
  - a role only counts once it has real work attached
  - archiving frees the slot and keeps the data
  - the limit bites at ACTIVATION, never mid-search
  - the Free tier's monthly candidate cap, and no cap on paid plans
  - every refusal names the limit hit and the tier that removes it
"""
from __future__ import annotations

import uuid

import pytest


def _role(db_module, session, company_id, user_id, title="Extra role"):
    rid = str(uuid.uuid4())
    session.add(db_module.CompanyRoleORM(
        id=rid, company_id=company_id, created_by=user_id,
        title=title, is_active=True, is_deleted=False,
    ))
    session.commit()
    return rid


def _set_plan(session, db_module, company_id, plan):
    c = session.query(db_module.CompanyORM).filter(
        db_module.CompanyORM.id == company_id).first()
    c.plan = plan
    session.commit()


class TestPlanShape:

    def test_no_per_candidate_caps_survive(self):
        from app.main import PLANS
        for key, plan in PLANS.items():
            assert "candidates_per_search" not in plan, f"{key} still has a per-search cap"
            joined = " ".join(plan["features"]).lower()
            assert "candidate / search" not in joined
            assert "candidates/search" not in joined

    def test_new_tiers_match_the_agreed_prices(self):
        from app.main import PLANS
        assert PLANS["free"]["price_monthly"] == 0
        assert PLANS["single"]["price_monthly"] == 39
        assert PLANS["team"]["price_monthly"] == 149
        assert PLANS["agency"]["price_monthly"] == 399

    def test_active_role_allowances(self):
        from app.main import PLANS, UNLIMITED
        assert PLANS["free"]["active_roles"] == 1
        assert PLANS["single"]["active_roles"] == 1
        assert PLANS["team"]["active_roles"] == 5
        assert PLANS["agency"]["active_roles"] >= UNLIMITED

    def test_only_free_is_seat_limited(self):
        from app.main import PLANS, UNLIMITED
        assert PLANS["free"]["seat_limit"] == 1
        for key in ("single", "team", "agency"):
            assert PLANS[key]["seat_limit"] >= UNLIMITED, f"{key} must allow unlimited users"

    def test_free_is_the_only_capped_tier(self):
        from app.main import PLANS, UNLIMITED
        assert PLANS["free"]["candidates_per_month"] == 100
        for key in ("single", "team", "agency"):
            assert PLANS[key]["candidates_per_month"] >= UNLIMITED

    def test_legacy_plans_still_resolve(self):
        """Existing subscribers on the old Stripe prices must not break."""
        from app.main import PLANS
        for key in ("business", "corporate", "enterprise"):
            assert key in PLANS, f"{key} was removed — existing subscribers would break"
            assert PLANS[key]["price_monthly"] > 0

    def test_only_the_four_new_tiers_are_offered(self):
        from app.main import NEW_PLAN_KEYS
        assert NEW_PLAN_KEYS == ["free", "single", "team", "agency"]


class TestActiveRoleCounting:

    def test_an_empty_role_does_not_count(self, as_acme, tenants, db_module, session):
        """A role you created and never used is free."""
        import app.roles as roles
        _role(db_module, session, tenants["acme"], tenants["acme_user"])
        assert roles.active_role_count(session, tenants["acme"]) == 0

    def test_team_dna_exemplars_activate_a_role(self, as_acme, tenants, seed_profiles, session):
        import app.roles as roles
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)
        assert roles.role_is_active(session, tenants["acme"], tenants["acme_role"]) is True

    def test_scored_candidates_activate_a_role(self, as_acme, tenants, session, db_module):
        import app.roles as roles
        cid = str(uuid.uuid4())
        session.add(db_module.CompanyCandidateORM(
            id=cid, company_id=tenants["acme"], added_by=tenants["acme_user"],
            name="Scored", role="R", tier="gold", match_score=90,
            job_id=tenants["acme_role"], shortlisted=False,
        ))
        session.commit()
        assert roles.role_is_active(session, tenants["acme"], tenants["acme_role"]) is True

    def test_archiving_frees_the_slot(self, as_acme, tenants, seed_profiles, session):
        import app.roles as roles
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)
        assert roles.active_role_count(session, tenants["acme"]) == 1

        assert as_acme.post(f"/api/roles/{tenants['acme_role']}/archive").status_code == 200
        session.expire_all()
        assert roles.active_role_count(session, tenants["acme"]) == 0

    def test_archiving_keeps_the_data(self, as_acme, tenants, seed_profiles, session,
                                      db_module):
        """The whole point of archive-vs-delete."""
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=3)
        as_acme.post(f"/api/roles/{tenants['acme_role']}/archive")

        kept = session.query(db_module.TeamDNAProfileORM).filter(
            db_module.TeamDNAProfileORM.role_id == tenants["acme_role"],
            db_module.TeamDNAProfileORM.is_deleted == False,   # noqa: E712
        ).count()
        assert kept == 3, "archiving must not delete exemplars"

    def test_unarchive_restores_the_slot(self, as_acme, tenants, seed_profiles, session):
        import app.roles as roles
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)
        as_acme.post(f"/api/roles/{tenants['acme_role']}/archive")
        assert as_acme.post(f"/api/roles/{tenants['acme_role']}/unarchive").status_code == 200
        session.expire_all()
        assert roles.active_role_count(session, tenants["acme"]) == 1

    def test_roles_list_is_tenant_scoped(self, as_globex, tenants):
        ids = [r["id"] for r in as_globex.get("/api/roles").json()["roles"]]
        assert tenants["acme_role"] not in ids

    def test_archive_rejects_another_tenants_role(self, as_globex, tenants):
        assert as_globex.post(f"/api/roles/{tenants['acme_role']}/archive").status_code == 404


class TestActivationLimit:

    def test_free_allows_one_active_role(self, as_acme, tenants, seed_profiles,
                                         session, db_module):
        _set_plan(session, db_module, tenants["acme"], "free")
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)

        second = _role(db_module, session, tenants["acme"], tenants["acme_user"], "Second role")
        res = as_acme.post("/api/team-dna/profiles", json={
            "role_id": second, "profiles": [{"name": "X", "text": "Owned billing. " * 20}],
        })
        assert res.status_code == 402

    def test_the_refusal_names_the_limit_and_the_tier(self, as_acme, tenants, seed_profiles,
                                                      session, db_module):
        """'Upgrade your plan' is not an explanation."""
        _set_plan(session, db_module, tenants["acme"], "free")
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)
        second = _role(db_module, session, tenants["acme"], tenants["acme_user"], "Second")

        detail = as_acme.post("/api/team-dna/profiles", json={
            "role_id": second, "profiles": [{"name": "X", "text": "Owned billing. " * 20}],
        }).json()["detail"]

        assert "1 active role" in detail
        assert "Archive" in detail, "must offer the free way out first"
        # Single also allows only ONE active role, so it would not solve this
        # problem — the suggestion must be the cheapest tier that actually
        # raises the ROLE limit, which is Team. (The candidate-cap message
        # names Single, because that IS the tier that fixes that limit.)
        assert "Team" in detail and "$149" in detail
        assert "Single" not in detail, "must not suggest a tier that doesn't help"

    def test_working_on_an_ALREADY_active_role_is_never_blocked(self, as_acme, tenants,
                                                                seed_profiles, session,
                                                                db_module):
        """Never stop someone part-way through what they already started."""
        _set_plan(session, db_module, tenants["acme"], "free")
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)

        res = as_acme.post("/api/team-dna/profiles", json={
            "role_id": tenants["acme_role"],
            "profiles": [{"name": "Third", "text": "Owned billing end to end. " * 20}],
        })
        assert res.status_code == 200, "the role is already active — adding to it must work"

    def test_team_allows_five(self, as_acme, tenants, seed_profiles, session, db_module):
        _set_plan(session, db_module, tenants["acme"], "team")
        import app.roles as roles
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)
        for i in range(4):
            rid = _role(db_module, session, tenants["acme"], tenants["acme_user"], f"R{i}")
            seed_profiles(tenants["acme"], tenants["acme_user"], rid, n=2)
        session.expire_all()
        assert roles.active_role_count(session, tenants["acme"]) == 5

        sixth = _role(db_module, session, tenants["acme"], tenants["acme_user"], "Sixth")
        res = as_acme.post("/api/team-dna/profiles", json={
            "role_id": sixth, "profiles": [{"name": "X", "text": "Owned billing. " * 20}]})
        assert res.status_code == 402
        assert "5 active roles" in res.json()["detail"]

    def test_agency_is_unlimited(self, as_acme, tenants, seed_profiles, session, db_module):
        _set_plan(session, db_module, tenants["acme"], "agency")
        for i in range(7):
            rid = _role(db_module, session, tenants["acme"], tenants["acme_user"], f"A{i}")
            seed_profiles(tenants["acme"], tenants["acme_user"], rid, n=2)
        eighth = _role(db_module, session, tenants["acme"], tenants["acme_user"], "Eighth")
        res = as_acme.post("/api/team-dna/profiles", json={
            "role_id": eighth, "profiles": [{"name": "X", "text": "Owned billing. " * 20}]})
        assert res.status_code == 200

    def test_unarchiving_beyond_the_limit_is_refused(self, as_acme, tenants, seed_profiles,
                                                     session, db_module):
        _set_plan(session, db_module, tenants["acme"], "free")
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)
        as_acme.post(f"/api/roles/{tenants['acme_role']}/archive")

        second = _role(db_module, session, tenants["acme"], tenants["acme_user"], "Second")
        seed_profiles(tenants["acme"], tenants["acme_user"], second, n=2)

        res = as_acme.post(f"/api/roles/{tenants['acme_role']}/unarchive")
        assert res.status_code == 402


class TestFreeCandidateCap:

    def _candidates(self, session, db_module, company_id, user_id, n):
        for _ in range(n):
            session.add(db_module.CompanyCandidateORM(
                id=str(uuid.uuid4()), company_id=company_id, added_by=user_id,
                name="C", role="R", tier="bronze", match_score=70, shortlisted=False))
        session.commit()

    def test_free_is_capped_at_100_a_month(self, tenants, session, db_module):
        from fastapi import HTTPException
        import app.roles as roles
        _set_plan(session, db_module, tenants["acme"], "free")
        self._candidates(session, db_module, tenants["acme"], tenants["acme_user"], 100)

        with pytest.raises(HTTPException) as e:
            roles.check_candidate_quota(session, tenants["acme"], "free", adding=1)
        assert e.value.status_code == 402
        assert "100 candidates" in e.value.detail
        assert "$39" in e.value.detail, "must name the tier that removes the cap"

    def test_under_the_cap_is_allowed(self, tenants, session, db_module):
        import app.roles as roles
        _set_plan(session, db_module, tenants["acme"], "free")
        self._candidates(session, db_module, tenants["acme"], tenants["acme_user"], 40)
        roles.check_candidate_quota(session, tenants["acme"], "free", adding=10)   # no raise

    def test_paid_plans_have_no_cap(self, tenants, session, db_module):
        import app.roles as roles
        self._candidates(session, db_module, tenants["acme"], tenants["acme_user"], 500)
        for plan in ("single", "team", "agency"):
            roles.check_candidate_quota(session, tenants["acme"], plan, adding=1000)

    def test_window_anchors_to_the_signup_day(self):
        from app.roles import month_window_start
        from datetime import datetime
        start = month_window_start(datetime(2024, 3, 17, 9, 30))
        assert start.day == 17
        assert start <= datetime.utcnow()

    def test_window_handles_a_31st_signup(self):
        from app.roles import month_window_start
        from datetime import datetime
        start = month_window_start(datetime(2024, 1, 31))
        assert start.day == 28, "clamped so every month is a valid date"


class TestUsageSummary:

    def test_reports_what_is_used_and_allowed(self, as_acme, tenants, seed_profiles,
                                              session, db_module):
        _set_plan(session, db_module, tenants["acme"], "free")
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)

        usage = as_acme.get("/api/plan/usage").json()
        assert usage["plan"] == "free"
        assert usage["active_roles"]["used"] == 1
        assert usage["active_roles"]["limit"] == 1
        assert usage["candidates_this_month"]["limit"] == 100

    def test_unlimited_is_explicit_not_a_huge_number(self, as_acme, tenants,
                                                     session, db_module):
        _set_plan(session, db_module, tenants["acme"], "agency")
        usage = as_acme.get("/api/plan/usage").json()
        assert usage["active_roles"]["unlimited"] is True
        assert usage["active_roles"]["limit"] is None
        assert usage["candidates_this_month"]["unlimited"] is True

    def test_usage_requires_auth(self, client_factory):
        assert client_factory(None).get("/api/plan/usage").status_code == 401
