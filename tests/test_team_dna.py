"""Team DNA tests.

Three areas, as specified:
  1. Tenant isolation on every new endpoint
  2. Trait-extraction JSON parsing (including the bias guardrails)
  3. Bulk upload with a malformed file

The AI is never actually called: extraction and scoring are monkeypatched, so
these tests are deterministic and cost nothing to run.
"""
from __future__ import annotations

import io
import json
import uuid

import pytest


# ============================================================
# 1. TENANT ISOLATION
# ============================================================
# The rule: every Team DNA row is scoped to company_id ONLY.
# Two halves, and both matter:
#   - a colleague in the SAME company SHARES the model (it's the team's DNA)
#   - a user in a DIFFERENT company must never see any of it
# user_id stays on the rows for audit but must never scope a read.

class TestTenantIsolation:

    def test_get_team_dna_hides_another_tenants_role(self, as_globex, tenants,
                                                     seed_profiles, seed_model):
        """Globex must not read Acme's model, even knowing the exact role_id."""
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=3)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        res = as_globex.get(f"/api/team-dna/{tenants['acme_role']}")
        assert res.status_code == 404, "a cross-tenant role_id must 404, not leak"

    def test_a_colleague_shares_the_teams_model(self, as_acme_colleague, tenants,
                                                seed_profiles, seed_model):
        """Same company, different user: Team DNA is SHARED across the team.

        This is the case a user_id filter would silently break.
        """
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=3)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        res = as_acme_colleague.get(f"/api/team-dna/{tenants['acme_role']}")
        assert res.status_code == 200
        body = res.json()
        assert body["built"] is True, "a colleague must see the team's model"
        assert body["profile_count"] == 3
        assert len(body["profiles"]) == 3
        assert body["shared_traits"], "and the traits that come with it"

    def test_a_colleague_sees_exemplars_a_teammate_uploaded(self, as_acme, as_acme_colleague,
                                                            tenants):
        """Exemplars pool per company+role, whoever uploaded them."""
        posted = as_acme.post("/api/team-dna/profiles", json={
            "role_id": tenants["acme_role"],
            "profiles": [{"name": "Priya Raman", "text": "Owned billing end to end. " * 12}],
        })
        assert posted.status_code == 200

        seen = as_acme_colleague.get(f"/api/team-dna/{tenants['acme_role']}").json()
        assert [p["name"] for p in seen["profiles"]] == ["Priya Raman"]

    def test_the_profile_cap_is_per_company_not_per_user(self, as_acme_colleague, tenants,
                                                         seed_profiles):
        """Five exemplars is the team's budget — a colleague can't add a sixth."""
        from app.team_dna import MAX_PROFILES
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"],
                      n=MAX_PROFILES)
        res = as_acme_colleague.post("/api/team-dna/profiles", json={
            "role_id": tenants["acme_role"],
            "profiles": [{"name": "One too many", "text": "x" * 300}],
        })
        assert res.status_code == 400
        assert str(MAX_PROFILES) in res.json()["detail"]

    def test_owner_sees_their_own_profiles(self, as_acme, tenants, seed_profiles):
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)
        res = as_acme.get(f"/api/team-dna/{tenants['acme_role']}")
        assert res.status_code in (200, 503)
        assert res.json()["profiles"], "the owner must see their own exemplars"

    def test_upload_rejects_cross_tenant_role(self, as_globex, tenants):
        res = as_globex.post("/api/team-dna/profiles", json={
            "role_id": tenants["acme_role"],
            "profiles": [{"name": "A", "text": "x" * 200}, {"name": "B", "text": "y" * 200}],
        })
        assert res.status_code == 404

    def test_delete_cannot_touch_another_tenants_profile(self, as_globex, as_acme,
                                                         tenants, seed_profiles, session,
                                                         db_module):
        ids = seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=2)

        res = as_globex.delete(f"/api/team-dna/profiles/{ids[0]}")
        assert res.status_code == 404

        still_there = session.query(db_module.TeamDNAProfileORM).filter(
            db_module.TeamDNAProfileORM.id == ids[0]).first()
        session.refresh(still_there)
        assert still_there.is_deleted is False, "a foreign delete must not soft-delete the row"

    def test_a_colleague_can_remove_a_team_exemplar(self, as_acme_colleague, tenants,
                                                    seed_profiles, session, db_module):
        """Shared pool means shared editing — the team curates it together."""
        ids = seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=3)
        res = as_acme_colleague.delete(f"/api/team-dna/profiles/{ids[0]}")
        assert res.status_code == 200
        assert res.json()["profile_count"] == 2

    def test_score_rejects_cross_tenant_role(self, as_globex, tenants, seed_model):
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])
        res = as_globex.post("/api/team-dna/score", json={
            "role_id": tenants["acme_role"], "candidate_text": "Ten years of platform work.",
        })
        assert res.status_code == 404

    def test_a_colleague_can_score_against_the_team_model(self, as_acme_colleague, tenants,
                                                          seed_model, monkeypatch):
        """A colleague scores against the team's model without rebuilding it."""
        _stub_scorer(monkeypatch)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])
        res = as_acme_colleague.post("/api/team-dna/score", json={
            "role_id": tenants["acme_role"], "candidate_text": "Ten years of platform work.",
        })
        assert res.status_code == 200
        assert res.json()["result"]["match_score"] > 0

    def test_score_still_409s_when_the_company_has_no_model(self, as_acme, tenants,
                                                            monkeypatch):
        """The 409 must still fire — for the company, not the individual."""
        _stub_scorer(monkeypatch)
        res = as_acme.post("/api/team-dna/score", json={
            "role_id": tenants["acme_role"], "candidate_text": "Ten years of platform work.",
        })
        assert res.status_code == 409

    def test_bulk_rejects_cross_tenant_role(self, as_globex, tenants, seed_model):
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])
        res = as_globex.post(
            "/api/candidates/bulk",
            data={"role_id": tenants["acme_role"]},
            files=[("files", ("cv.txt", b"A" * 500, "text/plain"))],
        )
        assert res.status_code == 404

    def test_bulk_job_status_is_not_readable_cross_tenant(self, as_acme, as_globex,
                                                          tenants, seed_model, monkeypatch):
        _stub_scorer(monkeypatch)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        started = as_acme.post(
            "/api/candidates/bulk",
            data={"role_id": tenants["acme_role"]},
            files=[("files", ("cv.txt", _cv_bytes("Dana Reed"), "text/plain"))],
        )
        assert started.status_code == 202
        job_id = started.json()["job_id"]

        assert as_globex.get(f"/api/candidates/bulk/{job_id}").status_code == 404
        assert as_acme.get(f"/api/candidates/bulk/{job_id}").status_code == 200

    def test_a_colleague_can_watch_a_teammates_bulk_job(self, as_acme, as_acme_colleague,
                                                       as_globex, tenants, seed_model,
                                                       monkeypatch):
        """Bulk jobs follow the same rule: shared inside the company, invisible outside."""
        _stub_scorer(monkeypatch)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        started = as_acme.post(
            "/api/candidates/bulk",
            data={"role_id": tenants["acme_role"]},
            files=[("files", ("cv.txt", _cv_bytes("Dana Reed"), "text/plain"))],
        )
        job_id = started.json()["job_id"]

        assert as_acme_colleague.get(f"/api/candidates/bulk/{job_id}").status_code == 200
        assert as_globex.get(f"/api/candidates/bulk/{job_id}").status_code == 404

    def test_user_id_is_still_recorded_for_audit(self, as_acme, tenants, session, db_module):
        """Rows must still say WHO did it, even though nothing filters on it."""
        as_acme.post("/api/team-dna/profiles", json={
            "role_id": tenants["acme_role"],
            "profiles": [{"name": "Audited Upload", "text": "Owned billing end to end. " * 12}],
        })
        row = session.query(db_module.TeamDNAProfileORM).filter(
            db_module.TeamDNAProfileORM.name == "Audited Upload").first()
        assert row is not None
        assert row.user_id == tenants["acme_user"], "the uploader must be recorded"
        assert row.company_id == tenants["acme"]

    def test_feedback_rejects_another_tenants_candidate(self, as_globex, tenants,
                                                        seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        res = as_globex.post("/api/candidates/feedback", json={
            "role_id": tenants["globex_role"], "candidate_id": candidate_id, "verdict": "bad",
        })
        assert res.status_code == 404, "must not accept a verdict on a foreign candidate"

    def test_feedback_list_is_scoped(self, as_acme, as_acme_colleague, as_globex,
                                     tenants, seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        posted = as_acme.post("/api/candidates/feedback", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id,
            "verdict": "good", "reason": "Owned a platform end to end",
        })
        assert posted.status_code == 200

        assert as_acme.get(f"/api/team-dna/{tenants['acme_role']}/feedback").json()["count"] == 1
        # A colleague sees the team's verdicts — that is what calibrates shared scoring.
        assert as_acme_colleague.get(
            f"/api/team-dna/{tenants['acme_role']}/feedback").json()["count"] == 1
        # Another tenant sees nothing at all.
        assert as_globex.get(f"/api/team-dna/{tenants['acme_role']}/feedback").status_code == 404

    def test_roles_list_is_tenant_scoped(self, as_globex, tenants):
        ids = [r["id"] for r in as_globex.get("/api/team-dna-roles").json()["roles"]]
        assert tenants["acme_role"] not in ids
        assert tenants["globex_role"] in ids

    @pytest.mark.parametrize("method,path,kwargs", [
        ("get", "/api/team-dna/{role}", {}),
        ("post", "/api/team-dna/profiles", {"json": {"role_id": "{role}", "profiles": []}}),
        ("delete", "/api/team-dna/profiles/some-id", {}),
        ("post", "/api/team-dna/score", {"json": {"role_id": "{role}", "candidate_text": "x"}}),
        ("post", "/api/candidates/feedback",
         {"json": {"role_id": "{role}", "candidate_id": "x", "verdict": "good"}}),
        ("get", "/api/team-dna-roles", {}),
    ])
    def test_every_endpoint_requires_auth(self, client_factory, tenants, method, path, kwargs):
        anon = client_factory(None)
        path = path.replace("{role}", tenants["acme_role"])
        if "json" in kwargs:
            kwargs = {"json": json.loads(
                json.dumps(kwargs["json"]).replace("{role}", tenants["acme_role"]))}
        res = getattr(anon, method)(path, **kwargs)
        assert res.status_code == 401, f"{method.upper()} {path} must require auth"


# ============================================================
# 2. TRAIT EXTRACTION — JSON PARSING
# ============================================================

class TestTraitExtractionParsing:

    def test_parses_well_formed_json(self):
        from app.team_dna import _parse_dna_json
        out = _parse_dna_json(json.dumps({
            "shared_traits": [
                {"trait": "Platform ownership", "evidence": "Owned billing end to end", "weight": 9},
                {"trait": "Kafka in anger", "evidence": "ran Kafka in production", "weight": 6},
            ],
            "career_patterns": ["Long tenure in one domain"],
            "anti_signals": ["No agency backgrounds"],
            "summary": "Long-tenure platform owners.",
        }))
        assert len(out["shared_traits"]) == 2
        assert out["shared_traits"][0]["weight"] == 9, "traits must come back weight-sorted"
        assert out["summary"] == "Long-tenure platform owners."

    def test_strips_markdown_fence(self):
        from app.team_dna import _parse_dna_json
        fenced = "```json\n" + json.dumps({
            "shared_traits": [{"trait": "T", "evidence": "E", "weight": 5}],
            "summary": "s",
        }) + "\n```"
        assert _parse_dna_json(fenced)["shared_traits"][0]["trait"] == "T"

    def test_unparseable_json_raises_rather_than_fabricating(self):
        from app.team_dna import _parse_dna_json, TeamDNAError
        with pytest.raises(TeamDNAError) as excinfo:
            _parse_dna_json("Sure! Here are the traits I found: mostly senior folks.")
        assert "couldn't read" in str(excinfo.value).lower()

    def test_empty_response_raises(self):
        from app.team_dna import _parse_dna_json, TeamDNAError
        with pytest.raises(TeamDNAError):
            _parse_dna_json("")

    def test_non_object_json_raises(self):
        from app.team_dna import _parse_dna_json, TeamDNAError
        with pytest.raises(TeamDNAError):
            _parse_dna_json(json.dumps(["not", "an", "object"]))

    def test_traits_without_evidence_are_dropped(self):
        from app.team_dna import _parse_dna_json
        out = _parse_dna_json(json.dumps({
            "shared_traits": [
                {"trait": "Backed by evidence", "evidence": "shipped the migration", "weight": 8},
                {"trait": "Vibes", "evidence": "", "weight": 10},
                {"trait": "", "evidence": "orphaned evidence", "weight": 9},
            ],
            "summary": "s",
        }))
        assert [t["trait"] for t in out["shared_traits"]] == ["Backed by evidence"]
        assert out["traits_dropped"] == 2

    def test_all_traits_dropped_raises_rather_than_returning_empty(self):
        from app.team_dna import _parse_dna_json, TeamDNAError
        with pytest.raises(TeamDNAError) as excinfo:
            _parse_dna_json(json.dumps({
                "shared_traits": [{"trait": "Vibes", "evidence": "", "weight": 10}],
                "summary": "s",
            }))
        assert "no evidence-backed traits" in str(excinfo.value).lower()

    def test_weight_is_clamped_and_coerced(self):
        from app.team_dna import _parse_dna_json
        out = _parse_dna_json(json.dumps({
            "shared_traits": [
                {"trait": "A", "evidence": "e", "weight": 99},
                {"trait": "B", "evidence": "e", "weight": -4},
                {"trait": "C", "evidence": "e", "weight": "not a number"},
            ],
            "summary": "s",
        }))
        weights = {t["trait"]: t["weight"] for t in out["shared_traits"]}
        assert weights == {"A": 10, "B": 1, "C": 5}

    def test_malformed_trait_entries_do_not_crash(self):
        from app.team_dna import _parse_dna_json
        out = _parse_dna_json(json.dumps({
            "shared_traits": [
                "a bare string", 42, None,
                {"trait": "Real", "evidence": "real evidence", "weight": 7},
            ],
            "summary": "s",
        }))
        assert [t["trait"] for t in out["shared_traits"]] == ["Real"]

    @pytest.mark.parametrize("trait,evidence", [
        ("Young and energetic", "in his late twenties"),
        ("Ivy League pedigree", "graduated from an elite university"),
        ("Culture fit", "would fit our culture well"),
        ("Extrovert", "clearly an extrovert in the write-up"),
        ("Local candidate", "holds citizenship, no visa needed"),
    ])
    def test_bias_traits_are_dropped(self, trait, evidence):
        """A tool that learns from your team will learn its demographics unless stopped."""
        from app.team_dna import _parse_dna_json
        out = _parse_dna_json(json.dumps({
            "shared_traits": [
                {"trait": trait, "evidence": evidence, "weight": 10},
                {"trait": "Owned billing", "evidence": "ran the billing platform", "weight": 8},
            ],
            "summary": "s",
        }))
        names = [t["trait"] for t in out["shared_traits"]]
        assert trait not in names, f"bias guardrail let {trait!r} through"
        assert "Owned billing" in names, "the legitimate trait must survive"

    def test_bias_language_is_stripped_from_summary(self):
        from app.team_dna import _parse_dna_json
        out = _parse_dna_json(json.dumps({
            "shared_traits": [{"trait": "Ownership", "evidence": "owned billing", "weight": 8}],
            "career_patterns": ["Mostly young men from top schools", "Long tenure"],
            "summary": "The team is mostly young men from Ivy League schools.",
        }))
        assert out["summary"] == ""
        assert out["career_patterns"] == ["Long tenure"]

    def test_fingerprint_changes_only_when_the_profile_set_changes(self):
        from app.team_dna import fingerprint_profiles
        a = [{"id": "1", "raw_text": "alpha"}, {"id": "2", "raw_text": "beta"}]
        reordered = list(reversed(a))
        changed = [{"id": "1", "raw_text": "alpha"}, {"id": "2", "raw_text": "GAMMA"}]

        assert fingerprint_profiles(a) == fingerprint_profiles(reordered), "order must not matter"
        assert fingerprint_profiles(a) != fingerprint_profiles(changed)

    def test_extract_traits_rejects_out_of_range_profile_counts(self):
        from app.team_dna import extract_traits, TeamDNAError, MIN_PROFILES, MAX_PROFILES
        with pytest.raises(TeamDNAError):
            extract_traits([{"name": "solo", "raw_text": "x"}] * (MIN_PROFILES - 1))
        with pytest.raises(TeamDNAError):
            extract_traits([{"name": "many", "raw_text": "x"}] * (MAX_PROFILES + 1))

    def test_ai_backend_failure_is_an_honest_error(self, monkeypatch):
        import app.team_dna as team_dna
        def _boom():
            raise RuntimeError("no API key configured")
        monkeypatch.setattr(team_dna, "get_openai_client", _boom)

        with pytest.raises(team_dna.TeamDNAError) as excinfo:
            team_dna.extract_traits([{"name": "a", "raw_text": "x"}, {"name": "b", "raw_text": "y"}])
        assert "temporarily unavailable" in str(excinfo.value).lower()


# ============================================================
# 3. BULK UPLOAD — MALFORMED FILES
# ============================================================

def _cv_bytes(name: str) -> bytes:
    return (
        f"{name}\n\nStaff Engineer\n\nOwned the payments platform end to end for six years. "
        f"Led a team of five through a monolith-to-services migration. Python, Postgres, Kafka."
    ).encode("utf-8")


def _stub_scorer(monkeypatch, fail_on: str | None = None):
    """Replace the GPT-4o scorer with a deterministic stub."""
    import app.ai_engine as ai_engine

    def _fake(candidate_text, team_dna_model, job_description=None,
              candidate_name=None, calibration=""):
        if fail_on and fail_on in (candidate_text or ""):
            raise ValueError("The AI returned an unreadable response — no score was produced.")
        return {
            "name": candidate_name or "Candidate", "tier": "gold",
            "match_score": 90 + (len(candidate_text) % 10),
            "adaptability": 80, "focus_penalty": 10,
            "ai_analysis": "Shares the team's platform-ownership pattern.",
            "silent_skill": "Systems thinking",
            "dna_matches": [{"trait": "End-to-end platform ownership", "found": True,
                             "evidence": "Owned the payments platform end to end"}],
            "evidence": {}, "boolean_search": None, "linkedin_url": None,
            "profile_pic": None, "experience_summary": candidate_text[:200],
            "latency_ms": 12, "scored_against": "team_dna",
        }

    monkeypatch.setattr(ai_engine, "score_against_team_dna", _fake)
    import app.team_dna_routes as team_dna_routes
    monkeypatch.setattr(team_dna_routes, "_BULK_JOBS", team_dna_routes._BULK_JOBS)
    return _fake


def _drain(client, job_id, tries=60):
    """Poll a bulk job to completion."""
    import time
    for _ in range(tries):
        body = client.get(f"/api/candidates/bulk/{job_id}").json()
        if body["status"] in ("complete", "failed"):
            return body
        time.sleep(0.05)
    return body


class TestBulkUpload:

    def test_one_malformed_file_does_not_fail_the_batch(self, as_acme, tenants,
                                                        seed_model, monkeypatch):
        """The whole point: a corrupt CV in a batch of 200 must not lose the other 199."""
        _stub_scorer(monkeypatch)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        res = as_acme.post(
            "/api/candidates/bulk",
            data={"role_id": tenants["acme_role"]},
            files=[
                ("files", ("good_one.txt", _cv_bytes("Dana Reed"), "text/plain")),
                # Claims to be a PDF, is actually random bytes — pdfplumber will reject it.
                ("files", ("corrupt.pdf", b"%PDF-1.4\n\x00\x01\x02 not really a pdf",
                           "application/pdf")),
                ("files", ("good_two.txt", _cv_bytes("Sam Okoro"), "text/plain")),
            ],
        )
        assert res.status_code == 202
        body = res.json()
        assert body["accepted"] == 2, "the two readable CVs must be accepted"
        assert body["rejected"] == 1
        assert body["rejected_files"][0]["filename"] == "corrupt.pdf"
        assert body["rejected_files"][0]["error"], "the rejection must carry a reason"

        final = _drain(as_acme, body["job_id"])
        assert final["status"] == "complete"
        assert len(final["results"]) == 2
        assert any(f["filename"] == "corrupt.pdf" for f in final["failed"])

    def test_unsupported_extension_is_rejected_with_a_reason(self, as_acme, tenants,
                                                             seed_model, monkeypatch):
        _stub_scorer(monkeypatch)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        res = as_acme.post(
            "/api/candidates/bulk",
            data={"role_id": tenants["acme_role"]},
            files=[
                ("files", ("cv.txt", _cv_bytes("Dana Reed"), "text/plain")),
                ("files", ("headshot.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 200, "image/png")),
            ],
        )
        assert res.status_code == 202
        rejected = res.json()["rejected_files"]
        assert len(rejected) == 1
        assert "Unsupported file type" in rejected[0]["error"]

    def test_all_files_malformed_returns_an_honest_400(self, as_acme, tenants,
                                                       seed_model, monkeypatch):
        _stub_scorer(monkeypatch)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        res = as_acme.post(
            "/api/candidates/bulk",
            data={"role_id": tenants["acme_role"]},
            files=[("files", ("broken.pdf", b"not a pdf at all", "application/pdf"))],
        )
        assert res.status_code == 400
        assert "could be read" in res.json()["detail"].lower()

    def test_empty_file_is_rejected_not_scored(self, as_acme, tenants, seed_model, monkeypatch):
        _stub_scorer(monkeypatch)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        res = as_acme.post(
            "/api/candidates/bulk",
            data={"role_id": tenants["acme_role"]},
            files=[
                ("files", ("cv.txt", _cv_bytes("Dana Reed"), "text/plain")),
                ("files", ("empty.txt", b"", "text/plain")),
            ],
        )
        assert res.json()["rejected"] == 1

    def test_file_over_the_limit_is_rejected(self, as_acme, tenants, seed_model, monkeypatch):
        _stub_scorer(monkeypatch)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])
        import app.cv_extract as cv_extract

        res = as_acme.post(
            "/api/candidates/bulk",
            data={"role_id": tenants["acme_role"]},
            files=[
                ("files", ("cv.txt", _cv_bytes("Dana Reed"), "text/plain")),
                ("files", ("huge.txt", b"A" * (cv_extract.MAX_FILE_BYTES + 1), "text/plain")),
            ],
        )
        assert res.json()["rejected"] == 1
        assert "larger than" in res.json()["rejected_files"][0]["error"]

    def test_too_many_files_is_refused(self, as_acme, tenants, seed_model, monkeypatch):
        _stub_scorer(monkeypatch)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])
        from app.team_dna_routes import MAX_BULK_FILES

        files = [("files", (f"cv{i}.txt", _cv_bytes(f"P{i}"), "text/plain"))
                 for i in range(MAX_BULK_FILES + 1)]
        res = as_acme.post("/api/candidates/bulk",
                           data={"role_id": tenants["acme_role"]}, files=files)
        assert res.status_code == 400
        assert str(MAX_BULK_FILES) in res.json()["detail"]

    def test_bulk_without_a_model_fails_fast(self, as_acme, tenants, monkeypatch):
        """Fail before the recruiter waits on 200 files, not after."""
        _stub_scorer(monkeypatch)
        res = as_acme.post(
            "/api/candidates/bulk",
            data={"role_id": tenants["acme_role"]},
            files=[("files", ("cv.txt", _cv_bytes("Dana Reed"), "text/plain"))],
        )
        assert res.status_code == 409

    def test_results_come_back_ranked(self, as_acme, tenants, seed_model, monkeypatch):
        _stub_scorer(monkeypatch)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        files = [("files", (f"cv{i}.txt",
                            _cv_bytes("Person " + "x" * i), "text/plain")) for i in range(6)]
        res = as_acme.post("/api/candidates/bulk",
                           data={"role_id": tenants["acme_role"]}, files=files)
        final = _drain(as_acme, res.json()["job_id"])

        scores = [r["match_score"] for r in final["results"]]
        assert scores == sorted(scores, reverse=True), "results must be ranked best-first"
        assert all(r.get("id") for r in final["results"]), "each result needs a persisted id"

    def test_a_scoring_failure_is_reported_not_faked(self, as_acme, tenants,
                                                     seed_model, monkeypatch):
        _stub_scorer(monkeypatch, fail_on="Sam Okoro")
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        res = as_acme.post(
            "/api/candidates/bulk",
            data={"role_id": tenants["acme_role"]},
            files=[
                ("files", ("a.txt", _cv_bytes("Dana Reed"), "text/plain")),
                ("files", ("b.txt", _cv_bytes("Sam Okoro"), "text/plain")),
            ],
        )
        final = _drain(as_acme, res.json()["job_id"])
        assert len(final["results"]) == 1
        assert len(final["failed"]) == 1
        assert "unreadable" in final["failed"][0]["error"].lower()


# ============================================================
# 4. CV EXTRACTION
# ============================================================

class TestCVExtraction:

    def test_plain_text_round_trips(self):
        import app.cv_extract as cv_extract
        text, error = cv_extract.extract_text("cv.txt", _cv_bytes("Dana Reed"))
        assert error is None
        assert "Dana Reed" in text

    def test_docx_is_read(self):
        pytest.importorskip("docx")
        import docx as docx_mod
        import app.cv_extract as cv_extract

        document = docx_mod.Document()
        document.add_paragraph("Priya Raman")
        document.add_paragraph("Staff Engineer, owned the billing platform end to end.")
        buffer = io.BytesIO()
        document.save(buffer)

        text, error = cv_extract.extract_text("priya.docx", buffer.getvalue())
        assert error is None
        assert "Priya Raman" in text

    def test_corrupt_pdf_returns_an_error_not_an_exception(self):
        import app.cv_extract as cv_extract
        text, error = cv_extract.extract_text("broken.pdf", b"%PDF-1.4 garbage")
        assert text is None
        assert error

    def test_text_below_the_useful_threshold_is_rejected(self):
        import app.cv_extract as cv_extract
        text, error = cv_extract.extract_text("tiny.txt", b"hi")
        assert text is None
        assert "no readable text" in error.lower()

    def test_guess_name_falls_back_to_the_filename(self):
        import app.cv_extract as cv_extract
        assert cv_extract.guess_name("dana_reed.txt", "1234\n5678") == "dana reed"

    def test_guess_name_prefers_the_first_real_line(self):
        import app.cv_extract as cv_extract
        assert cv_extract.guess_name("x.txt", "Dana Reed\nStaff Engineer") == "Dana Reed"


# ============================================================
# 5. PROFILE LIFECYCLE
# ============================================================

class TestProfileLifecycle:

    def test_upload_enforces_the_maximum(self, as_acme, tenants, seed_profiles):
        from app.team_dna import MAX_PROFILES
        seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"],
                      n=MAX_PROFILES)
        res = as_acme.post("/api/team-dna/profiles", json={
            "role_id": tenants["acme_role"],
            "profiles": [{"name": "One too many", "text": "x" * 300}],
        })
        assert res.status_code == 400
        assert str(MAX_PROFILES) in res.json()["detail"]

    def test_upload_reports_readiness(self, as_acme, tenants):
        from app.team_dna import MIN_PROFILES
        res = as_acme.post("/api/team-dna/profiles", json={
            "role_id": tenants["acme_role"],
            "profiles": [{"name": "Only one", "text": "x" * 300}],
        })
        assert res.status_code == 200
        assert res.json()["ready_to_build"] is (1 >= MIN_PROFILES)

    def test_deleting_a_profile_invalidates_the_cached_model(self, as_acme, tenants,
                                                             seed_profiles, seed_model,
                                                             session, db_module):
        ids = seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=3)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])

        assert as_acme.delete(f"/api/team-dna/profiles/{ids[0]}").status_code == 200

        model = session.query(db_module.TeamDNAModelORM).filter(
            db_module.TeamDNAModelORM.role_id == tenants["acme_role"],
            db_module.TeamDNAModelORM.user_id == tenants["acme_user"],
        ).first()
        session.refresh(model)
        assert model.source_fingerprint is None, "stale traits must not survive a profile change"

    def test_scoring_refuses_an_invalidated_model(self, as_acme, tenants,
                                                  seed_profiles, seed_model):
        ids = seed_profiles(tenants["acme"], tenants["acme_user"], tenants["acme_role"], n=3)
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])
        as_acme.delete(f"/api/team-dna/profiles/{ids[0]}")

        res = as_acme.post("/api/team-dna/score", json={
            "role_id": tenants["acme_role"], "candidate_text": "Ten years of platform work.",
        })
        assert res.status_code == 409

    def test_upload_rejects_an_empty_payload(self, as_acme, tenants):
        res = as_acme.post("/api/team-dna/profiles",
                           json={"role_id": tenants["acme_role"], "profiles": []})
        assert res.status_code == 400


# ============================================================
# 6. FEEDBACK LOOP
# ============================================================

class TestFeedbackLoop:

    def test_verdict_must_be_good_or_bad(self, as_acme, tenants, seed_candidate):
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"])
        res = as_acme.post("/api/candidates/feedback", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id, "verdict": "maybe",
        })
        assert res.status_code == 400

    def test_feedback_reaches_the_prompt_context(self, as_acme, tenants, seed_candidate,
                                                 session, db_module):
        from app.team_dna import feedback_context
        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"], name="Dana Reed")
        as_acme.post("/api/candidates/feedback", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id,
            "verdict": "bad", "reason": "Only ever worked on internal tools",
        })

        context = feedback_context(session, tenants["acme"], tenants["acme_user"],
                                   tenants["acme_role"])
        assert "REJECTED" in context
        assert "Dana Reed" in context
        assert "internal tools" in context

    def test_feedback_context_is_empty_for_a_fresh_role(self, session, tenants):
        from app.team_dna import feedback_context
        assert feedback_context(session, tenants["acme"], tenants["acme_user"],
                                tenants["globex_role"]) == ""

    def test_feedback_is_actually_passed_into_the_scorer(self, as_acme, tenants,
                                                        seed_model, seed_candidate,
                                                        monkeypatch):
        """The calibration must reach the prompt, not just exist.

        feedback_context() being correct and score_against_team_dna() being
        correct still leaves the wiring between them untested — this closes it.
        """
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

        candidate_id = seed_candidate(tenants["acme"], tenants["acme_user"], name="Rejected Person")
        as_acme.post("/api/candidates/feedback", json={
            "role_id": tenants["acme_role"], "candidate_id": candidate_id,
            "verdict": "bad", "reason": "Only ever worked on internal tools",
        })

        res = as_acme.post("/api/team-dna/score", json={
            "role_id": tenants["acme_role"], "candidate_text": "Ten years of platform work.",
        })
        assert res.status_code == 200
        assert "Rejected Person" in seen["calibration"]
        assert "internal tools" in seen["calibration"]
        assert "REJECTED" in seen["calibration"]

    def test_feedback_context_is_capped(self, session, db_module, tenants):
        from app.team_dna import feedback_context, MAX_FEEDBACK_EXAMPLES
        for i in range(MAX_FEEDBACK_EXAMPLES + 8):
            session.add(db_module.CandidateFeedbackORM(
                id=str(uuid.uuid4()), company_id=tenants["acme"], user_id=tenants["acme_user"],
                role_id=tenants["acme_role"], candidate_id=str(uuid.uuid4()),
                verdict="good", reason=f"reason {i}", candidate_name=f"P{i}",
            ))
        session.commit()

        context = feedback_context(session, tenants["acme"], tenants["acme_user"],
                                   tenants["acme_role"])
        assert context.count("\n- ") <= MAX_FEEDBACK_EXAMPLES


# ============================================================
# 7. SCORING OUTPUT SHAPE — must stay drop-in for the existing card
# ============================================================

class TestScoringShape:

    def _model(self):
        return {"shared_traits": [
            {"trait": "End-to-end platform ownership", "evidence": "owned billing", "weight": 9}]}

    def _stub_client(self, monkeypatch, payload):
        import app.ai_engine as ai_engine

        class _Message:
            content = json.dumps(payload) if isinstance(payload, dict) else payload

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        class _Completions:
            def create(self, **kwargs):
                return _Response()

        class _Chat:
            completions = _Completions()

        class _Client:
            chat = _Chat()

        monkeypatch.setattr(ai_engine, "get_openai_client", lambda: (_Client(), "gpt-4o"))

    def test_returns_the_same_keys_as_the_existing_scorer(self, monkeypatch):
        from app.ai_engine import score_against_team_dna
        self._stub_client(monkeypatch, {
            "tier": "gold", "match_score": 96, "adaptability": 88, "focus_penalty": 8,
            "silent_skill": "Systems thinking", "ai_analysis": "Shares platform ownership.",
            "dna_matches": [{"trait": "End-to-end platform ownership", "found": True,
                             "evidence": "owned the payments platform"}],
        })
        out = score_against_team_dna("Owned the payments platform.", self._model())

        # These are exactly the keys the existing gold/silver/bronze card reads.
        for key in ("name", "tier", "match_score", "adaptability", "focus_penalty",
                    "ai_analysis", "silent_skill", "evidence", "linkedin_url", "latency_ms"):
            assert key in out, f"missing {key} — the existing card would break"
        assert out["dna_matches"][0]["found"] is True

    def test_unparseable_output_raises_rather_than_scoring(self, monkeypatch):
        from app.ai_engine import score_against_team_dna
        self._stub_client(monkeypatch, "I think this candidate is pretty good honestly")
        with pytest.raises(ValueError) as excinfo:
            score_against_team_dna("Some CV text.", self._model())
        assert "no score was produced" in str(excinfo.value).lower()

    def test_unknown_traits_are_not_echoed_back(self, monkeypatch):
        """The model must not invent traits that were never in the Team DNA."""
        from app.ai_engine import score_against_team_dna
        self._stub_client(monkeypatch, {
            "tier": "silver", "match_score": 88, "adaptability": 70, "focus_penalty": 20,
            "ai_analysis": "ok", "silent_skill": "x",
            "dna_matches": [
                {"trait": "End-to-end platform ownership", "found": True, "evidence": "yes"},
                {"trait": "Invented trait nobody asked for", "found": True, "evidence": "no"},
            ],
        })
        out = score_against_team_dna("CV text.", self._model())
        assert [m["trait"] for m in out["dna_matches"]] == ["End-to-end platform ownership"]

    def test_biased_analysis_is_withheld(self, monkeypatch):
        from app.ai_engine import score_against_team_dna
        self._stub_client(monkeypatch, {
            "tier": "gold", "match_score": 96, "adaptability": 88, "focus_penalty": 8,
            "silent_skill": "Good culture fit",
            "ai_analysis": "A young man from an Ivy League school, great culture fit.",
            "dna_matches": [],
        })
        out = score_against_team_dna("CV text.", self._model())
        assert "Ivy League" not in out["ai_analysis"]
        assert "withheld" in out["ai_analysis"]
        assert out["silent_skill"] is None

    def test_scores_are_clamped(self, monkeypatch):
        from app.ai_engine import score_against_team_dna
        self._stub_client(monkeypatch, {
            "tier": "not a tier", "match_score": 9000, "adaptability": -5,
            "focus_penalty": "nonsense", "ai_analysis": "ok", "dna_matches": [],
        })
        out = score_against_team_dna("CV text.", self._model())
        assert out["tier"] == "bronze"
        assert out["match_score"] == 100
        assert out["adaptability"] == 0
        assert out["focus_penalty"] == 20

    def test_requires_a_model_with_traits(self):
        from app.ai_engine import score_against_team_dna
        with pytest.raises(ValueError):
            score_against_team_dna("CV text.", {"shared_traits": []})
        with pytest.raises(ValueError):
            score_against_team_dna("", {"shared_traits": [{"trait": "t"}]})
