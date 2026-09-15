"""Signing up, signing in, and reaching the workspace.

This file exists because of a specific outage. Removing LinkedIn also deleted
`is_hr_professional()` — a function that sits beside the LinkedIn code but is
called by /api/company/register on every signup. Registration raised NameError
and returned 500 for everybody, and it shipped to production, because nothing
in the suite ever registered an account.

Every other test file patches authentication away so it can get at the feature
under test. That is what left this hole: the one path no test walked was the
path every customer walks first. These tests deliberately use a plain client
and go through the real endpoints, with real session cookies.

The single most valuable assertion here is the dullest one: that a valid
signup does not return 500.
"""
from __future__ import annotations

import uuid

import pytest


@pytest.fixture
def raw(app_module):
    """A client with NO auth patching — the real flow, real cookies."""
    from fastapi.testclient import TestClient
    return TestClient(app_module.app)


def _payload(**over):
    tag = uuid.uuid4().hex[:10]
    body = {
        "name":         f"Example {tag}",
        "domain":       f"ex-{tag}.test",
        "admin_email":  f"person@ex-{tag}.test",
        "admin_name":   "Dana Reed",
        "password":     "a-long-enough-password",
        "job_title":    "Head of Talent",
        "linkedin_url": "https://www.linkedin.com/in/dana-reed",
    }
    body.update(over)
    return body


class TestSignupWorksAtAll:
    """The regression guard. If registration is broken, this fails first."""

    def test_a_valid_signup_does_not_500(self, raw):
        res = raw.post("/api/company/register", json=_payload())
        assert res.status_code != 500, (
            "registration raised — this is exactly how is_hr_professional() "
            f"went missing and took signup down: {res.text[:300]}"
        )
        assert res.status_code == 200, res.text
        assert res.json()["ok"] is True

    def test_the_new_account_can_sign_in_and_reach_the_workspace(self, raw):
        body = _payload()
        assert raw.post("/api/company/register", json=body).status_code == 200

        res = raw.post("/api/company/login",
                       json={"email": body["admin_email"], "password": body["password"]})
        assert res.status_code == 200, res.text
        assert res.json()["ok"] is True

        # the session cookie the login set must actually open the workspace
        page = raw.get("/workspace", follow_redirects=False)
        assert page.status_code == 200, (
            f"signed in but the workspace refused: {page.status_code}")

    def test_signed_out_visitors_are_sent_to_login(self, app_module):
        from fastapi.testclient import TestClient
        anon = TestClient(app_module.app)
        page = anon.get("/workspace", follow_redirects=False)
        assert page.status_code == 302
        assert "/login" in page.headers.get("location", "")


class TestSignupRefusesBadInput:
    """Each refusal must be a 4xx with a reason, never a 500."""

    @pytest.mark.parametrize("missing", ["name", "domain", "admin_email", "admin_name", "password"])
    def test_a_missing_field_is_a_400(self, raw, missing):
        res = raw.post("/api/company/register", json=_payload(**{missing: ""}))
        assert res.status_code == 400
        assert "required" in res.json()["detail"].lower()

    def test_a_short_password_is_refused(self, raw):
        res = raw.post("/api/company/register", json=_payload(password="short"))
        assert res.status_code == 400
        assert "8 characters" in res.json()["detail"]

    def test_a_non_hr_job_title_is_refused(self, raw):
        """The HR gate is the thing that broke. Prove it still runs."""
        res = raw.post("/api/company/register", json=_payload(job_title="Plumber"))
        assert res.status_code == 400
        assert "HR" in res.json()["detail"]

    def test_the_same_domain_cannot_register_twice(self, raw):
        body = _payload()
        assert raw.post("/api/company/register", json=body).status_code == 200
        again = raw.post("/api/company/register", json=_payload(
            domain=body["domain"], admin_email=f"other@{body['domain']}"))
        assert again.status_code == 400
        assert "already registered" in again.json()["detail"].lower()


class TestLoginRefusesBadCredentials:

    def test_a_wrong_password_does_not_sign_you_in(self, raw):
        body = _payload()
        raw.post("/api/company/register", json=body)
        res = raw.post("/api/company/login",
                       json={"email": body["admin_email"], "password": "not-the-password"})
        assert res.status_code >= 400
        assert res.status_code != 500

    def test_an_unknown_email_does_not_sign_you_in(self, raw):
        res = raw.post("/api/company/login",
                       json={"email": "nobody@nowhere.test", "password": "a-long-enough-password"})
        assert res.status_code >= 400
        assert res.status_code != 500


class TestTheAuthPagesRender:
    """A 500 on any of these is a broken front door."""

    @pytest.mark.parametrize("path", ["/", "/login", "/register", "/plans",
                                      "/privacy", "/terms", "/accessibility"])
    def test_the_page_loads(self, raw, path):
        res = raw.get(path, follow_redirects=False)
        assert res.status_code == 200, f"{path} returned {res.status_code}"

    @pytest.mark.parametrize("path", ["/", "/login", "/register", "/plans", "/accessibility"])
    def test_the_accessibility_control_is_on_it(self, raw, path):
        """It has to be everywhere, not just where someone remembered."""
        assert "a11y.js" in raw.get(path).text, f"{path} has no accessibility control"

    def test_linkedin_sign_in_reports_whether_it_is_configured(self, raw):
        """The button hides itself when there are no credentials, so this
        endpoint must keep answering."""
        res = raw.get("/api/auth/linkedin/config")
        assert res.status_code == 200
        assert isinstance(res.json()["configured"], bool)
