"""Tests for the local (non-Microsoft) test login.

Enabled only when ``RISKAPP_TEST_LOGIN_ENABLED`` is set; the endpoint must be
invisible otherwise, and honour the shared access code when configured.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riskapp.config import settings


@pytest.fixture()
def test_login_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "test_login_enabled", True)
    monkeypatch.setattr(settings, "test_login_code", "")
    monkeypatch.setattr(settings, "test_login_secret", "unit-test-key")


class TestTestLoginDisabled:
    def test_status_reports_disabled(self, client: TestClient) -> None:
        resp = client.get("/api/auth/test-login/status")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False, "code_required": False}

    def test_endpoint_is_hidden(self, client: TestClient) -> None:
        resp = client.post("/api/auth/test-login", json={"role": "System Admin"})
        assert resp.status_code == 404


class TestTestLoginEnabled:
    def test_status_reports_enabled(self, client: TestClient, test_login_on: None) -> None:
        resp = client.get("/api/auth/test-login/status")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_issues_token_and_token_authenticates(
        self, client: TestClient, test_login_on: None
    ) -> None:
        resp = client.post(
            "/api/auth/test-login", json={"role": "PMO Lead", "upn": "tester@test.local"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "PMO Lead"
        assert body["upn"] == "tester@test.local"

        # The issued token must work as a bearer token.
        me = client.get("/api/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200
        assert me.json()["roles"] == ["PMO Lead"]
        assert me.json()["upn"] == "tester@test.local"

    def test_defaults_to_a_role_specific_identity(
        self, client: TestClient, test_login_on: None
    ) -> None:
        body = client.post("/api/auth/test-login", json={"role": "System Admin"}).json()
        assert body["upn"] == "test.system_admin@test.local"

    def test_unknown_role_rejected(self, client: TestClient, test_login_on: None) -> None:
        resp = client.post("/api/auth/test-login", json={"role": "Wizard"})
        assert resp.status_code == 422

    def test_code_is_required_when_configured(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "test_login_enabled", True)
        monkeypatch.setattr(settings, "test_login_code", "letmein")
        monkeypatch.setattr(settings, "test_login_secret", "unit-test-key")

        assert (
            client.post("/api/auth/test-login", json={"role": "System Admin"}).status_code == 403
        )
        assert (
            client.post(
                "/api/auth/test-login", json={"role": "System Admin", "code": "wrong"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/auth/test-login", json={"role": "System Admin", "code": "letmein"}
            ).status_code
            == 200
        )

    def test_test_token_does_not_leak_into_entra_mode(
        self, client: TestClient, test_login_on: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With Entra enabled, a bogus bearer token must still be rejected.
        monkeypatch.setattr(settings, "entra_tenant_id", "some-tenant")
        resp = client.get("/api/me", headers={"Authorization": "Bearer not-a-real-token"})
        assert resp.status_code == 401
