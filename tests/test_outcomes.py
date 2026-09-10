"""Hiring outcome tests.

Four areas, as specified:
  1. Tenant isolation on all three endpoints
  2. score_at_time immutability
  3. The under-5 suppression rule
  4. Stage transitions

Plus the honesty rules that make the dataset worth having: no percentage is
ever derived from a suppressed band, and retention is never inferred from
unanswered checks.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest


# ============================================================
# 1. TENANT ISOLATION
# ============================================================

class TestTenantIsolation:

    def test_post_rejects_another_tenants_candidate(self, as_globex, tenants, seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        res = as_globex.post("/api/outcomes", json={
            "role_id": tenants["globex_role"], "candidate_id": candidate_id, "stage": "hired",
        })
        assert res.status_code == 404, "must not record an outcome for a foreign candidate"

    def test_post_rejects_another_tenants_role(self, as_globex, tenants, seed_candidate):
        candidate_id = seed_candidate(tenants["globex"], tenants["globex_user"])
        res = as_globex.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "hired",
        })
        assert res.status_code == 404

    def test_get_by_role_rejects_another_tenant(self, as_globex, as_acme, tenants,
                                                seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "interviewed",
        })
        assert as_globex.get(f"/api/outcomes/{tenants['acme_role']}").status_code == 404
        assert as_acme.get(f"/api/outcomes/{tenants['acme_role']}").json()["count"] == 1

    def test_a_colleague_sees_the_teams_outcomes(self, as_acme, as_acme_colleague,
                                                 tenants, seed_candidate):
        """Company-scoped, matching Team DNA — the funnel belongs to the team."""
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "offered",
        })
        seen = as_acme_colleague.get(f"/api/outcomes/{tenants['acme_role']}").json()
        assert seen["count"] == 1
        assert seen["outcomes"][0]["stage"] == "offered"

    def test_stats_never_include_another_tenants_rows(self, as_acme, as_globex, tenants,
                                                      seed_candidate):
        # Acme records enough for a full band.
        for _ in range(6):
            cid = seed_candidate(tenants["acme"], tenants["acme_user"])
            as_acme.post("/api/outcomes", json={
                "role_id": tenants["acme_role"], "candidate_id": cid, "stage": "hired",
            })

        globex_stats = as_globex.get("/api/outcomes/stats").json()
        assert globex_stats["total_outcomes"] == 0, "another tenant's rows must be invisible"
        for band in globex_stats["bands"]:
            assert band["insufficient_data"] is True

        acme_stats = as_acme.get("/api/outcomes/stats").json()
        assert acme_stats["total_outcomes"] == 6

    def test_stats_role_filter_rejects_another_tenants_role(self, as_globex, tenants):
        res = as_globex.get("/api/outcomes/stats", params={"role_id": tenants["acme_role"]})
        assert res.status_code == 404

    def test_retention_patch_rejects_another_tenant(self, as_acme, as_globex, tenants,
                                                    seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        created = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "hired",
        }).json()
        outcome_id = created["outcome"]["id"]

        assert as_globex.patch(f"/api/outcomes/{outcome_id}/retention",
                               json={"still_employed": True}).status_code == 404
        assert as_acme.patch(f"/api/outcomes/{outcome_id}/retention",
                             json={"still_employed": True}).status_code == 200

    @pytest.mark.parametrize("method,path,kwargs", [
        ("post", "/api/outcomes", {"json": {"role_id": "{role}", "candidate_id": "x",
                                            "stage": "hired"}}),
        ("get", "/api/outcomes/{role}", {}),
        ("get", "/api/outcomes/stats", {}),
        ("patch", "/api/outcomes/some-id/retention", {"json": {"still_employed": True}}),
    ])
    def test_every_endpoint_requires_auth(self, client_factory, tenants, method, path, kwargs):
        import json as _json
        anon = client_factory(None)
        path = path.replace("{role}", tenants["acme_role"])
        if "json" in kwargs:
            kwargs = {"json": _json.loads(
                _json.dumps(kwargs["json"]).replace("{role}", tenants["acme_role"]))}
        res = getattr(anon, method)(path, **kwargs)
        assert res.status_code == 401, f"{method.upper()} {path} must require auth"


# ============================================================
# 2. score_at_time IMMUTABILITY
# ============================================================
# The single most important property in this file. If the score can drift after
# the fact, every correlation the table exists to support is worthless.

class TestScoreSnapshot:

    def test_score_is_snapshotted_on_first_write(self, as_acme, tenants, seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])   # scored 96 / gold
        created = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "contacted",
        }).json()
        assert created["outcome"]["score_at_time"] == 96
        assert created["outcome"]["tier_at_time"] == "gold"

    def test_rescoring_the_candidate_does_not_rewrite_history(self, as_acme, tenants,
                                                              seed_candidate, session,
                                                              db_module):
        """Re-scoring later must not retroactively change the recorded score."""
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "contacted",
        })

        # The candidate is re-scored much lower afterwards.
        candidate = session.query(db_module.CompanyCandidateORM).filter(
            db_module.CompanyCandidateORM.id == candidate_id).first()
        candidate.match_score = 42
        candidate.tier = "bronze"
        session.commit()

        # Advancing the stage must not pick up the new score.
        updated = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "hired",
        }).json()
        assert updated["outcome"]["score_at_time"] == 96, "the ORIGINAL score must survive"
        assert updated["outcome"]["tier_at_time"] == "gold"
        assert updated["outcome"]["stage"] == "hired"

    def test_score_at_time_is_not_client_settable(self, as_acme, tenants, seed_candidate):
        """A caller must not be able to inject a score of their choosing."""
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        created = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id,
            "stage": "hired", "score_at_time": 12, "tier_at_time": "bronze",
        }).json()
        assert created["outcome"]["score_at_time"] == 96, "score comes from the candidate row only"
        assert created["outcome"]["tier_at_time"] == "gold"

    def test_second_write_updates_not_duplicates(self, as_acme, tenants, seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        first = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "contacted"})
        second = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "screened"})
        assert first.status_code == 201 and first.json()["created"] is True
        assert second.status_code == 200 and second.json()["created"] is False
        assert first.json()["outcome"]["id"] == second.json()["outcome"]["id"]
        assert as_acme.get(f"/api/outcomes/{tenants['acme_role']}").json()["count"] == 1


# ============================================================
# 3. THE UNDER-5 SUPPRESSION RULE
# ============================================================

class TestSuppressionRule:

    def _record(self, client, role_id, seed_candidate, tenants, n, stage,
                score=96, tier="gold"):
        for _ in range(n):
            cid = seed_candidate(tenants["acme"], tenants["acme_user"],
                                 score=score, tier=tier)
            client.post("/api/outcomes", json={
                "role_id": role_id, "candidate_id": cid, "stage": stage})

    def test_a_band_under_five_reports_insufficient_data(self, as_acme, tenants,
                                                         seed_candidate):
        self._record(as_acme, tenants["acme_role"], seed_candidate, tenants, 4, "hired")
        band = self._band(as_acme, "90_100")
        assert band["candidates"] == 4
        assert band["insufficient_data"] is True

    def test_a_suppressed_band_carries_no_percentages_at_all(self, as_acme, tenants,
                                                             seed_candidate):
        """Not zeroed — ABSENT. A key that isn't there can't be rendered by mistake."""
        self._record(as_acme, tenants["acme_role"], seed_candidate, tenants, 3, "hired")
        band = self._band(as_acme, "90_100")
        for key in ("hired_pct", "reached_interview_pct", "still_employed_pct",
                    "hired", "reached_interview"):
            assert key not in band, f"{key} must be absent from a suppressed band"

    def test_the_fifth_candidate_unlocks_the_band(self, as_acme, tenants, seed_candidate):
        self._record(as_acme, tenants["acme_role"], seed_candidate, tenants, 4, "hired")
        assert self._band(as_acme, "90_100")["insufficient_data"] is True

        self._record(as_acme, tenants["acme_role"], seed_candidate, tenants, 1, "hired")
        band = self._band(as_acme, "90_100")
        assert band["insufficient_data"] is False
        assert band["candidates"] == 5
        assert band["hired_pct"] == 100.0

    def test_percentages_are_real_ratios(self, as_acme, tenants, seed_candidate):
        self._record(as_acme, tenants["acme_role"], seed_candidate, tenants, 3, "hired")
        self._record(as_acme, tenants["acme_role"], seed_candidate, tenants, 2, "rejected")
        band = self._band(as_acme, "90_100")
        assert band["candidates"] == 5
        assert band["hired"] == 3
        assert band["hired_pct"] == 60.0

    def test_bands_are_independent(self, as_acme, tenants, seed_candidate):
        """A full band must not unlock a thin one."""
        self._record(as_acme, tenants["acme_role"], seed_candidate, tenants, 6, "hired",
                     score=95, tier="gold")
        self._record(as_acme, tenants["acme_role"], seed_candidate, tenants, 2, "hired",
                     score=75, tier="bronze")
        assert self._band(as_acme, "90_100")["insufficient_data"] is False
        assert self._band(as_acme, "70_79")["insufficient_data"] is True

    def test_all_four_bands_are_always_present(self, as_acme, tenants):
        bands = {b["band"] for b in as_acme.get("/api/outcomes/stats").json()["bands"]}
        assert bands == {"90_100", "80_89", "70_79", "below_70"}

    def test_stats_carry_the_disclaimer(self, as_acme, tenants):
        body = as_acme.get("/api/outcomes/stats").json()
        assert body["min_band_sample"] == 5
        assert "extrapolated" in body["disclaimer"]

    def test_retention_is_not_inferred_from_unanswered_checks(self, as_acme, tenants,
                                                              seed_candidate):
        """An unanswered 12-month check is not a departure and not a retention."""
        self._record(as_acme, tenants["acme_role"], seed_candidate, tenants, 5, "hired")
        band = self._band(as_acme, "90_100")
        assert band["retention_checked"] == 0
        assert band["still_employed_pct"] is None
        assert "No 12-month checks answered yet" in band["retention_note"]

    def test_retention_pct_uses_answered_checks_only(self, as_acme, tenants, seed_candidate):
        ids = []
        for _ in range(5):
            cid = seed_candidate(tenants["acme"], tenants["acme_user"])
            created = as_acme.post("/api/outcomes", json={
                "role_id": tenants["acme_role"], "candidate_id": cid, "stage": "hired"}).json()
            ids.append(created["outcome"]["id"])

        # Answer two of five: one stayed, one left.
        as_acme.patch(f"/api/outcomes/{ids[0]}/retention", json={"still_employed": True})
        as_acme.patch(f"/api/outcomes/{ids[1]}/retention", json={"still_employed": False})

        band = self._band(as_acme, "90_100")
        assert band["retention_checked"] == 2
        assert band["still_employed"] == 1
        assert band["still_employed_pct"] == 50.0, "denominator is answered checks, not hires"

    def _band(self, client, key):
        body = client.get("/api/outcomes/stats").json()
        return next(b for b in body["bands"] if b["band"] == key)


# ============================================================
# 4. STAGE TRANSITIONS
# ============================================================

class TestStageTransitions:

    def test_rejects_an_unknown_stage(self, as_acme, tenants, seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        res = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "ghosted"})
        assert res.status_code == 400
        assert "stage must be one of" in res.json()["detail"]

    @pytest.mark.parametrize("stage", [
        "sourced", "contacted", "screened", "interviewed", "offered", "hired",
        "rejected", "withdrawn",
    ])
    def test_every_documented_stage_is_accepted(self, as_acme, tenants, seed_candidate, stage):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        res = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": stage})
        assert res.status_code == 201
        assert res.json()["outcome"]["stage"] == stage

    def test_furthest_stage_advances_with_progress(self, as_acme, tenants, seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        for stage in ("contacted", "screened", "interviewed"):
            body = as_acme.post("/api/outcomes", json={
                "role_id": tenants["acme_role"], "candidate_id": candidate_id,
                "stage": stage}).json()
        assert body["outcome"]["furthest_stage"] == "interviewed"

    def test_rejection_after_interview_keeps_the_interview_on_record(self, as_acme, tenants,
                                                                     seed_candidate):
        """The case that makes furthest_stage necessary.

        Without it, everyone who was interviewed and then rejected would vanish
        from "% reached interview" — understating the funnel for exactly the
        candidates it is meant to measure.
        """
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id,
            "stage": "interviewed"})
        body = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id,
            "stage": "rejected", "rejected_reason": "Stronger candidate in the pool"}).json()

        assert body["outcome"]["stage"] == "rejected"
        assert body["outcome"]["furthest_stage"] == "interviewed"
        assert body["outcome"]["rejected_reason"] == "Stronger candidate in the pool"

    def test_a_rejected_interviewee_still_counts_toward_reached_interview(self, as_acme,
                                                                          tenants,
                                                                          seed_candidate):
        for _ in range(5):
            cid = seed_candidate(tenants["acme"], tenants["acme_user"])
            as_acme.post("/api/outcomes", json={
                "role_id": tenants["acme_role"], "candidate_id": cid, "stage": "interviewed"})
            as_acme.post("/api/outcomes", json={
                "role_id": tenants["acme_role"], "candidate_id": cid, "stage": "rejected"})

        body = as_acme.get("/api/outcomes/stats").json()
        band = next(b for b in body["bands"] if b["band"] == "90_100")
        assert band["reached_interview"] == 5
        assert band["reached_interview_pct"] == 100.0
        assert band["hired"] == 0

    def test_moving_backwards_does_not_lower_furthest_stage(self, as_acme, tenants,
                                                            seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "offered"})
        body = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id,
            "stage": "screened"}).json()
        assert body["outcome"]["stage"] == "screened"
        assert body["outcome"]["furthest_stage"] == "offered"

    def test_hired_sets_hired_at_once(self, as_acme, tenants, seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        first = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id,
            "stage": "hired"}).json()
        assert first["outcome"]["hired_at"] is not None

        as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "stage": "hired"})
        again = as_acme.get(f"/api/outcomes/{tenants['acme_role']}").json()["outcomes"][0]
        assert again["hired_at"] == first["outcome"]["hired_at"], "hire date must not drift"

    def test_retention_check_only_applies_to_hires(self, as_acme, tenants, seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        created = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id,
            "stage": "interviewed"}).json()
        res = as_acme.patch(f"/api/outcomes/{created['outcome']['id']}/retention",
                            json={"still_employed": True})
        assert res.status_code == 400

    def test_follow_up_flag_fires_at_twelve_months(self, as_acme, tenants, seed_candidate,
                                                   session, db_module):
        from app.outcomes import RETENTION_FOLLOW_UP_DAYS
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        created = as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id,
            "stage": "hired"}).json()

        fresh = as_acme.get(f"/api/outcomes/{tenants['acme_role']}").json()["outcomes"][0]
        assert fresh["follow_up_due"] is False, "not due on the day of hire"
        assert fresh["follow_up_date"] is not None

        # Backdate the hire past the window.
        row = session.query(db_module.CandidateOutcomeORM).filter(
            db_module.CandidateOutcomeORM.id == created["outcome"]["id"]).first()
        row.hired_at = datetime.utcnow() - timedelta(days=RETENTION_FOLLOW_UP_DAYS + 1)
        session.commit()

        due = as_acme.get(f"/api/outcomes/{tenants['acme_role']}").json()["outcomes"][0]
        assert due["follow_up_due"] is True

        as_acme.patch(f"/api/outcomes/{created['outcome']['id']}/retention",
                      json={"still_employed": True})
        answered = as_acme.get(f"/api/outcomes/{tenants['acme_role']}").json()["outcomes"][0]
        assert answered["follow_up_due"] is False, "an answered check must stop nagging"


# ============================================================
# 5. PURE UNITS
# ============================================================

class TestOutcomeUnits:

    @pytest.mark.parametrize("score,expected", [
        (100, "90_100"), (96.0, "90_100"), (90, "90_100"),
        (89.9, "80_89"), (80, "80_89"),
        (79.9, "70_79"), (70, "70_79"),
        (69.9, "below_70"), (0, "below_70"),
        (None, None),
    ])
    def test_band_boundaries(self, score, expected):
        from app.outcomes import band_for_score
        assert band_for_score(score) == expected

    def test_unscored_outcomes_are_excluded_not_dumped_in_below_70(self):
        from app.outcomes import compute_band_stats

        class Row:
            score_at_time = None
            furthest_stage = "hired"
            still_employed = None

        stats = compute_band_stats([Row() for _ in range(6)])
        assert stats["unscored_outcomes"] == 6
        below = next(b for b in stats["bands"] if b["band"] == "below_70")
        assert below["candidates"] == 0
        assert below["insufficient_data"] is True

    def test_advance_furthest_never_regresses(self):
        from app.outcomes import advance_furthest
        assert advance_furthest("interviewed", "offered") == "offered"
        assert advance_furthest("offered", "screened") == "offered"
        assert advance_furthest("interviewed", "rejected") == "interviewed"
        assert advance_furthest("sourced", "withdrawn") == "sourced"
        assert advance_furthest("", "contacted") == "contacted"

    def test_empty_stats_are_all_suppressed(self):
        from app.outcomes import compute_band_stats
        stats = compute_band_stats([])
        assert stats["total_outcomes"] == 0
        assert all(b["insufficient_data"] for b in stats["bands"])


# ============================================================
# 6. FEEDING BACK INTO TEAM DNA
# ============================================================

class TestOutcomeCalibration:

    def test_outcome_context_is_empty_with_no_data(self, session, tenants):
        from app.outcomes import outcome_context
        assert outcome_context(session, tenants["acme"], tenants["acme_role"]) == ""

    def test_hires_are_marked_as_the_stronger_signal(self, as_acme, tenants,
                                                     seed_candidate, session):
        from app.outcomes import outcome_context
        cid = seed_candidate(tenants["acme"], tenants["acme_user"])
        as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": cid, "stage": "hired"})

        context = outcome_context(session, tenants["acme"], tenants["acme_role"])
        assert "HIRED" in context
        assert "stronger positive signal than a thumbs-up" in context

    def test_rejections_carry_how_far_they_got(self, as_acme, tenants, seed_candidate,
                                               session):
        from app.outcomes import outcome_context
        cid = seed_candidate(tenants["acme"], tenants["acme_user"])
        as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": cid, "stage": "interviewed"})
        as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": cid, "stage": "rejected",
            "rejected_reason": "Shallow systems depth"})

        context = outcome_context(session, tenants["acme"], tenants["acme_role"])
        assert "REJECTED at interviewed" in context
        assert "Shallow systems depth" in context

    def test_outcomes_reach_the_scorer_alongside_thumbs(self, as_acme, tenants, seed_model,
                                                        seed_candidate, monkeypatch):
        """Both calibration sources must arrive in the same prompt."""
        import app.ai_engine as ai_engine
        seen = {}

        def _capture(candidate_text, team_dna_model, job_description=None,
                     candidate_name=None, calibration=""):
            seen["calibration"] = calibration
            return {
                "name": candidate_name or "C", "tier": "gold", "match_score": 96,
                "adaptability": 80, "focus_penalty": 10, "ai_analysis": "ok",
                "silent_skill": None, "dna_matches": [], "evidence": {},
                "boolean_search": None, "linkedin_url": None, "profile_pic": None,
                "experience_summary": "", "latency_ms": 1, "scored_against": "team_dna",
            }

        monkeypatch.setattr(ai_engine, "score_against_team_dna", _capture)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        thumbs_cid = seed_candidate(tenants["acme"], tenants["acme_user"], name="Thumbed Person")
        as_acme.post("/api/candidates/feedback", json={
            "role_id": tenants["acme_role"], "candidate_id": thumbs_cid,
            "verdict": "bad", "reason": "Only internal tools"})

        hired_cid = seed_candidate(tenants["acme"], tenants["acme_user"], name="Hired Person")
        as_acme.post("/api/outcomes", json={
            "role_id": tenants["acme_role"], "candidate_id": hired_cid, "stage": "hired"})

        res = as_acme.post("/api/team-dna/score", json={
            "role_id": tenants["acme_role"], "candidate_text": "Ten years of platform work."})
        assert res.status_code == 200

        calibration = seen["calibration"]
        assert "Thumbed Person" in calibration, "thumbs feedback must still be there"
        assert "REAL HIRING OUTCOMES" in calibration, "outcomes must be there too"
        assert calibration.index("RECRUITER CALIBRATION") < calibration.index("REAL HIRING OUTCOMES")
