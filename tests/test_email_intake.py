"""Candidates arriving by email.

The dangerous part of an inbound webhook is that a mail provider has no
session cookie, so it cannot be protected the way every other endpoint is.
These tests pin the things that would otherwise let a stranger inject
candidates into someone else's account.
"""
from __future__ import annotations

import hashlib
import hmac
import io as _io
import json
import uuid

import pytest


def _sig(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _cv(name: str) -> str:
    return (f"{name}\n\nStaff Engineer\n\nOwned the payments platform end to end for six "
            f"years. Led a team of five through a monolith-to-services migration. "
            f"Python, Postgres, Kafka. Ten years in payments infrastructure.")


@pytest.fixture
def intake_on(monkeypatch):
    """Switch intake on with a known secret."""
    import app.email_intake as intake
    monkeypatch.setattr(intake, "INTAKE_SECRET", "test-intake-secret")
    monkeypatch.setattr(intake, "INTAKE_DOMAIN", "apply.aitmp.io")
    return "test-intake-secret"


class TestWebhookSecurity:

    def test_fails_closed_when_no_secret_is_configured(self, client_factory, monkeypatch):
        """An unauthenticated intake endpoint would let anyone inject candidates."""
        import app.email_intake as intake
        monkeypatch.setattr(intake, "INTAKE_SECRET", "")
        anon = client_factory(None)
        res = anon.post("/api/intake/email", json={"to": "role-abc@apply.aitmp.io"})
        assert res.status_code == 503
        assert "not configured" in res.json()["detail"]

    def test_rejects_a_missing_signature(self, client_factory, intake_on):
        anon = client_factory(None)
        res = anon.post("/api/intake/email", json={"to": "role-abc@apply.aitmp.io"})
        assert res.status_code == 401

    def test_rejects_a_wrong_signature(self, client_factory, intake_on):
        anon = client_factory(None)
        body = json.dumps({"to": "role-abc@apply.aitmp.io"}).encode()
        res = anon.post("/api/intake/email", content=body,
                        headers={"X-Intake-Signature": _sig(body, "wrong-secret"),
                                 "Content-Type": "application/json"})
        assert res.status_code == 401

    def test_accepts_a_correct_signature(self, client_factory, intake_on):
        anon = client_factory(None)
        body = json.dumps({"to": "nobody@example.test"}).encode()
        res = anon.post("/api/intake/email", content=body,
                        headers={"X-Intake-Signature": _sig(body, intake_on),
                                 "Content-Type": "application/json"})
        assert res.status_code == 200

    def test_a_tampered_body_fails(self, client_factory, intake_on):
        """Signature must cover the body, not just exist."""
        anon = client_factory(None)
        signed = json.dumps({"to": "role-aaa@apply.aitmp.io"}).encode()
        tampered = json.dumps({"to": "role-bbb@apply.aitmp.io"}).encode()
        res = anon.post("/api/intake/email", content=tampered,
                        headers={"X-Intake-Signature": _sig(signed, intake_on),
                                 "Content-Type": "application/json"})
        assert res.status_code == 401


class TestAddressing:

    def test_token_is_not_derived_from_the_role_id(self, as_acme, tenants):
        """The address leaks — into job-board settings and mail headers. It
        must not be reversible to anything."""
        res = as_acme.get(f"/api/intake/address/{tenants['acme_role']}")
        assert res.status_code == 200
        addr = res.json()["address"]
        assert tenants["acme_role"] not in addr
        assert tenants["acme"] not in addr

    def test_address_is_stable_across_reads(self, as_acme, tenants):
        a = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()["address"]
        b = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()["address"]
        assert a == b

    def test_rotation_changes_it(self, as_acme, tenants):
        a = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()["address"]
        r = as_acme.post(f"/api/intake/address/{tenants['acme_role']}/rotate")
        assert r.status_code == 200
        assert r.json()["address"] != a

    def test_another_tenant_cannot_read_your_address(self, as_globex, tenants):
        assert as_globex.get(f"/api/intake/address/{tenants['acme_role']}").status_code == 404

    def test_another_tenant_cannot_rotate_yours(self, as_globex, tenants):
        assert as_globex.post(f"/api/intake/address/{tenants['acme_role']}/rotate").status_code == 404

    @pytest.mark.parametrize("to_field,expected", [
        ("role-abc123@apply.aitmp.io", "abc123"),
        ('"HR Team" <role-xyz789@apply.aitmp.io>', "xyz789"),
        ("someone@x.com, role-def456@apply.aitmp.io", "def456"),
        ("ROLE-UPPER1@apply.aitmp.io", "upper1"),
        ("nobody@example.com", None),
        ("", None),
    ])
    def test_recipient_parsing(self, to_field, expected):
        from app.email_intake import parse_recipient
        assert parse_recipient(to_field) == expected


class TestDelivery:

    def _send(self, client, secret, to, attachments=None, text="", frm="a@b.test"):
        payload = {"to": to, "from": frm, "subject": "Application", "text": text,
                   "attachments": attachments or []}
        body = json.dumps(payload).encode()
        return client.post("/api/intake/email", content=body,
                           headers={"X-Intake-Signature": _sig(body, secret),
                                    "Content-Type": "application/json"})

    def _b64(self, filename, text):
        import base64
        return {"Name": filename, "Content": base64.b64encode(text.encode()).decode()}

    def test_a_cv_attachment_becomes_a_candidate(self, as_acme, client_factory,
                                                 tenants, intake_on, seed_model):
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])
        addr = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()["address"]

        res = self._send(client_factory(None), intake_on, addr,
                         [self._b64("dana_reed.txt", _cv("Dana Reed"))])
        assert res.status_code == 200
        body = res.json()
        assert body["accepted"] == 1
        assert body["role_id"] == tenants["acme_role"]

    def test_unknown_address_is_ignored_not_an_error(self, client_factory, intake_on):
        """A revoked address must not make the provider retry forever."""
        res = self._send(client_factory(None), intake_on,
                         "role-doesnotexist@apply.aitmp.io",
                         [self._b64("cv.txt", _cv("Nobody"))])
        assert res.status_code == 200
        assert "ignored" in res.json()

    def test_an_image_attachment_is_skipped_with_a_reason(self, as_acme, client_factory,
                                                          tenants, intake_on):
        addr = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()["address"]
        import base64
        png = {"Name": "signature.png", "Content": base64.b64encode(b"\x89PNG\r\n").decode()}
        res = self._send(client_factory(None), intake_on, addr, [png])
        assert res.status_code == 200
        assert res.json()["accepted"] == 0
        assert res.json()["skipped"][0]["filename"] == "signature.png"

    def test_one_bad_attachment_does_not_lose_the_good_one(self, as_acme, client_factory,
                                                           tenants, intake_on, seed_model):
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])
        addr = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()["address"]
        import base64
        bad = {"Name": "broken.pdf", "Content": base64.b64encode(b"not a pdf").decode()}
        good = self._b64("good.txt", _cv("Sam Okoro"))
        res = self._send(client_factory(None), intake_on, addr, [bad, good])
        assert res.json()["accepted"] == 1
        assert len(res.json()["skipped"]) == 1

    def test_a_pasted_cv_in_the_body_is_accepted(self, as_acme, client_factory,
                                                 tenants, intake_on, seed_model):
        seed_model(tenants["acme"], tenants["acme_user"], tenants["acme_role"])
        addr = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()["address"]
        res = self._send(client_factory(None), intake_on, addr, [], text=_cv("Inline Person") * 4)
        assert res.json()["accepted"] == 1

    def test_a_short_body_with_no_attachment_is_not_a_candidate(self, as_acme, client_factory,
                                                                tenants, intake_on):
        addr = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()["address"]
        res = self._send(client_factory(None), intake_on, addr, [], text="Hi, see attached")
        assert res.json()["accepted"] == 0

    def test_unscored_when_the_role_has_no_team_dna(self, as_acme, client_factory,
                                                    tenants, intake_on, session, db_module):
        """No model means no score — never a fabricated number."""
        addr = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()["address"]
        res = self._send(client_factory(None), intake_on, addr,
                         [self._b64("cv.txt", _cv("Unscored Person"))])
        assert res.json()["accepted"] == 1
        assert res.json()["candidates"][0]["scored"] is False

        row = session.query(db_module.CompanyCandidateORM).filter(
            db_module.CompanyCandidateORM.name == "Unscored Person").first()
        assert row.match_score == 0
        assert "no Team DNA" in row.ai_analysis

    def test_free_plan_quota_still_applies_to_email(self, as_acme, client_factory,
                                                    tenants, intake_on, session, db_module):
        """Email must not be a way around the plan limits."""
        c = session.query(db_module.CompanyORM).filter(
            db_module.CompanyORM.id == tenants["acme"]).first()
        c.plan = "free"
        for _ in range(100):
            session.add(db_module.CompanyCandidateORM(
                id=str(uuid.uuid4()), company_id=tenants["acme"],
                added_by=tenants["acme_user"], name="filler", role="R",
                tier="bronze", match_score=70, shortlisted=False))
        session.commit()

        addr = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()["address"]
        res = self._send(client_factory(None), intake_on, addr,
                         [self._b64("cv.txt", _cv("Over Quota"))])
        assert res.status_code == 200
        assert res.json()["accepted"] == 0
        assert res.json()["over_quota"] is True


class TestSetupHonesty:

    def test_status_says_what_is_still_needed(self, as_acme, tenants, monkeypatch):
        import app.email_intake as intake
        monkeypatch.setattr(intake, "INTAKE_SECRET", "")
        body = as_acme.get("/api/intake/status").json()
        assert body["configured"] is False
        assert any("MX record" in s for s in body["steps"])
        # Resend cannot receive mail — say so rather than let someone assume.
        assert "does not receive mail" in body["note"]

    def test_address_endpoint_flags_unconfigured(self, as_acme, tenants, monkeypatch):
        import app.email_intake as intake
        monkeypatch.setattr(intake, "INTAKE_SECRET", "")
        body = as_acme.get(f"/api/intake/address/{tenants['acme_role']}").json()
        assert body["configured"] is False
        assert body["setup"] is not None
