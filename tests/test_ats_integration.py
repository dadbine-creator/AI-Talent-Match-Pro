"""ATS integration — Greenhouse and Lever, for real.

The thing being prevented here is what the old UI did: report a successful
connection and a successful push without making any request at all.

Covers: only implemented partners are offered, the API key is stored
encrypted and never returned, tenant isolation, and that a push failure
surfaces as a failure rather than a green toast.
"""
from __future__ import annotations

import uuid

import pytest


class TestOnlyRealPartnersOffered:
    """The old modal offered Salesforce, HubSpot, Workday, Greenhouse, Lever
    and BambooHR. Four of those had no server-side code whatsoever."""

    def test_only_implemented_partners_are_listed(self, as_acme, tenants):
        res = as_acme.get("/api/ats/partners")
        assert res.status_code == 200
        names = {p["partner"] for p in res.json()["partners"]}
        assert names == {"greenhouse", "lever"}

    def test_the_four_fictional_ones_are_gone(self, as_acme, tenants):
        names = {p["partner"] for p in as_acme.get("/api/ats/partners").json()["partners"]}
        for gone in ("salesforce", "hubspot", "workday", "bamboo"):
            assert gone not in names, f"{gone} has no implementation and must not be offered"

    def test_the_second_fake_catalog_is_gone(self, as_acme, tenants):
        """A competing catalog lived at /api/partners/* and contradicted this
        one: it offered Indeed, Zapier and Make as "available", and its
        install wrote a row and answered "installed successfully" while
        connecting to nothing. /api/ats/partners is the only catalog now."""
        for path in ("/api/partners/catalog", "/api/partners/installed"):
            assert as_acme.get(path).status_code == 404, f"{path} must not exist"
        res = as_acme.post("/api/partners/install",
                           json={"partner_key": "indeed", "config": {}})
        assert res.status_code == 404, "installing a fictional partner must not be possible"

    def test_readiness_does_not_claim_unbuilt_partners_are_ready(self, as_acme, tenants):
        """The readiness sheet listed zapier and make as "ready" alongside the
        two that genuinely are. Inbound Zapier webhooks do work, but nothing
        made either one a ready *partner integration*."""
        body = as_acme.get("/api/partners/readiness").json()["partners"]
        ready = {k for k, v in body.items() if v.get("status") == "ready"}
        assert ready == {"greenhouse", "lever"}, f"unexpected ready partners: {ready}"

    def test_connecting_an_unsupported_partner_is_refused(self, as_acme, tenants):
        res = as_acme.post("/api/ats/salesforce/connect",
                           json={"api_key": "x" * 24, "account_ref": "acme"})
        assert res.status_code == 400
        assert "isn't supported" in res.json()["detail"]

    def test_pushing_to_an_unsupported_partner_is_refused(self, as_acme, tenants,
                                                          seed_candidate):
        cid = seed_candidate(tenants["acme"], tenants["acme_user"])
        res = as_acme.post(f"/api/ats/hubspot/push/{cid}")
        assert res.status_code == 400


class TestCredentialSafety:

    def test_the_key_is_never_returned_to_the_browser(self, as_acme, tenants):
        secret = "gh_" + uuid.uuid4().hex
        res = as_acme.post("/api/ats/greenhouse/connect",
                           json={"api_key": secret, "account_ref": "acmeco"})
        assert res.status_code == 200
        blob = res.text
        assert secret not in blob, "the API key must never be echoed back"
        # and not on a later read either
        assert secret not in as_acme.get("/api/ats/partners").text

    def test_only_a_four_char_hint_is_exposed(self, as_acme, tenants):
        secret = "gh_live_" + uuid.uuid4().hex
        as_acme.post("/api/ats/greenhouse/connect",
                     json={"api_key": secret, "account_ref": "acmeco"})
        p = next(x for x in as_acme.get("/api/ats/partners").json()["partners"]
                 if x["partner"] == "greenhouse")
        assert p["connected"] is True
        assert p["key_hint"] == "…" + secret[-4:]
        assert len(p["key_hint"]) <= 5

    def test_stored_value_is_encrypted_at_rest(self, as_acme, tenants, session, db_module):
        secret = "gh_" + uuid.uuid4().hex
        as_acme.post("/api/ats/greenhouse/connect", json={"api_key": secret})
        row = session.query(db_module.PartnerCredentialORM).filter(
            db_module.PartnerCredentialORM.company_id == tenants["acme"],
            db_module.PartnerCredentialORM.partner == "greenhouse").first()
        assert row is not None
        assert secret not in row.secret_enc, "the key must not be stored in plaintext"

    def test_it_round_trips_for_server_side_use(self, as_acme, tenants, session):
        import app.partner_credentials as creds
        secret = "gh_" + uuid.uuid4().hex
        as_acme.post("/api/ats/greenhouse/connect", json={"api_key": secret})
        assert creds.read_key(session, tenants["acme"], "greenhouse") == secret

    def test_a_too_short_key_is_rejected(self, as_acme, tenants):
        res = as_acme.post("/api/ats/greenhouse/connect", json={"api_key": "abc"})
        assert res.status_code == 400
        assert "too short" in res.json()["detail"]

    def test_reconnecting_replaces_rather_than_duplicates(self, as_acme, tenants,
                                                          session, db_module):
        as_acme.post("/api/ats/greenhouse/connect", json={"api_key": "gh_" + "a" * 20})
        as_acme.post("/api/ats/greenhouse/connect", json={"api_key": "gh_" + "b" * 20})
        n = session.query(db_module.PartnerCredentialORM).filter(
            db_module.PartnerCredentialORM.company_id == tenants["acme"],
            db_module.PartnerCredentialORM.partner == "greenhouse").count()
        assert n == 1

    def test_disconnect_deletes_the_key(self, as_acme, tenants, session, db_module):
        as_acme.post("/api/ats/greenhouse/connect", json={"api_key": "gh_" + "c" * 20})
        assert as_acme.delete("/api/ats/greenhouse").status_code == 200
        n = session.query(db_module.PartnerCredentialORM).filter(
            db_module.PartnerCredentialORM.company_id == tenants["acme"]).count()
        assert n == 0


class TestTenantIsolation:

    def test_another_tenant_cannot_see_your_connection(self, as_acme, as_globex, tenants):
        as_acme.post("/api/ats/greenhouse/connect",
                     json={"api_key": "gh_" + "d" * 20, "account_ref": "acmeco"})
        theirs = as_globex.get("/api/ats/partners").json()["partners"]
        assert all(p["connected"] is False for p in theirs)
        assert all(p["account_ref"] is None for p in theirs)

    def test_another_tenant_cannot_read_your_key(self, as_acme, tenants, session):
        import app.partner_credentials as creds
        as_acme.post("/api/ats/greenhouse/connect", json={"api_key": "gh_" + "e" * 20})
        assert creds.read_key(session, tenants["globex"], "greenhouse") is None

    def test_another_tenant_cannot_disconnect_yours(self, as_acme, as_globex, tenants,
                                                    session, db_module):
        as_acme.post("/api/ats/greenhouse/connect", json={"api_key": "gh_" + "f" * 20})
        assert as_globex.delete("/api/ats/greenhouse").status_code == 404
        assert session.query(db_module.PartnerCredentialORM).filter(
            db_module.PartnerCredentialORM.company_id == tenants["acme"]).count() == 1

    def test_cannot_push_another_tenants_candidate(self, as_acme, as_globex, tenants,
                                                   seed_candidate):
        as_globex.post("/api/ats/greenhouse/connect", json={"api_key": "gh_" + "g" * 20})
        cid = seed_candidate(tenants["acme"], tenants["acme_user"])
        assert as_globex.post(f"/api/ats/greenhouse/push/{cid}").status_code == 404

    @pytest.mark.parametrize("method,path", [
        ("get", "/api/ats/partners"),
        ("post", "/api/ats/greenhouse/connect"),
        ("delete", "/api/ats/greenhouse"),
        ("post", "/api/ats/greenhouse/push/some-id"),
    ])
    def test_every_endpoint_requires_auth(self, client_factory, method, path):
        anon = client_factory(None)
        kw = {"json": {"api_key": "x" * 20}} if method == "post" else {}
        assert getattr(anon, method)(path, **kw).status_code == 401


class TestPushHonesty:
    """The old push showed 'added to Greenhouse!' unconditionally. These
    assert that never happens again."""

    def test_push_without_a_connection_is_a_409_not_a_success(self, as_acme, tenants,
                                                              seed_candidate):
        cid = seed_candidate(tenants["acme"], tenants["acme_user"])
        res = as_acme.post(f"/api/ats/greenhouse/push/{cid}")
        assert res.status_code == 409
        assert "isn't connected" in res.json()["detail"]

    def test_a_partner_api_failure_surfaces_as_a_failure(self, as_acme, tenants,
                                                         seed_candidate, monkeypatch):
        import app.integrations_routes as routes

        async def _fails(**kwargs):
            return {"ok": False, "error": "Greenhouse rejected: unknown candidate",
                    "http_status": 502, "not_connected": False}

        monkeypatch.setattr("app.integrations_engine.push_to_partner", _fails)
        as_acme.post("/api/ats/greenhouse/connect", json={"api_key": "gh_" + "h" * 20})
        cid = seed_candidate(tenants["acme"], tenants["acme_user"])

        res = as_acme.post(f"/api/ats/greenhouse/push/{cid}")
        assert res.status_code >= 400, "a failed push must not return 200"
        assert "rejected" in res.json()["detail"].lower()

    def test_a_real_success_reports_success(self, as_acme, tenants, seed_candidate,
                                            monkeypatch):
        async def _works(**kwargs):
            return {"ok": True, "latency_ms": 42, "status": "success"}

        monkeypatch.setattr("app.integrations_engine.push_to_partner", _works)
        as_acme.post("/api/ats/greenhouse/connect", json={"api_key": "gh_" + "i" * 20})
        cid = seed_candidate(tenants["acme"], tenants["acme_user"])

        res = as_acme.post(f"/api/ats/greenhouse/push/{cid}")
        assert res.status_code == 200
        assert res.json()["ok"] is True
