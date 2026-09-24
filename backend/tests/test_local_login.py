"""Tests for local email + password sign-in (app-managed credentials)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.config import settings
from riskapp.security import hash_password, verify_password
from riskapp.services import get_or_create_user


class TestPasswordHashing:
    def test_roundtrip(self) -> None:
        stored = hash_password("correct horse battery staple")
        assert stored.startswith("scrypt$")
        assert verify_password("correct horse battery staple", stored)
        assert not verify_password("wrong", stored)

    def test_salt_is_random(self) -> None:
        assert hash_password("same") != hash_password("same")

    def test_empty_inputs_rejected(self) -> None:
        assert not verify_password("", hash_password("x"))
        assert not verify_password("x", None)
        assert not verify_password("x", "garbage")


@pytest.fixture()
def password_login_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "local_login_enabled", True)
    monkeypatch.setattr(settings, "test_login_secret", "unit-test-key-long-enough-000")


class TestLoginOptions:
    def test_reports_disabled_by_default(self, client: TestClient) -> None:
        body = client.get("/api/auth/login-options").json()
        assert body["password_enabled"] is False

    def test_reports_enabled(self, client: TestClient, password_login_on: None) -> None:
        assert client.get("/api/auth/login-options").json()["password_enabled"] is True


class TestPasswordLogin:
    def _seed_user(
        self, db: Session, upn: str = "pm@example.com", role: str = "PMO Lead"
    ) -> models.User:
        user = get_or_create_user(db, upn, "Pat Manager")
        user.password_hash = hash_password("Secret123!")
        user.role = role
        db.commit()
        return user

    def test_disabled_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/auth/login", json={"email": "pm@example.com", "password": "Secret123!"}
        )
        assert resp.status_code == 404

    def test_valid_credentials_issue_a_working_token(
        self, client: TestClient, db_session: Session, password_login_on: None
    ) -> None:
        self._seed_user(db_session)

        resp = client.post(
            "/api/auth/login", json={"email": "pm@example.com", "password": "Secret123!"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "PMO Lead"

        me = client.get("/api/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200
        assert me.json()["roles"] == ["PMO Lead"]
        assert me.json()["upn"] == "pm@example.com"

    def test_email_is_case_insensitive(
        self, client: TestClient, db_session: Session, password_login_on: None
    ) -> None:
        self._seed_user(db_session, upn="MixedCase@Example.com")
        resp = client.post(
            "/api/auth/login", json={"email": "mixedcase@example.com", "password": "Secret123!"}
        )
        assert resp.status_code == 200

    def test_wrong_password_is_401(
        self, client: TestClient, db_session: Session, password_login_on: None
    ) -> None:
        self._seed_user(db_session)
        resp = client.post(
            "/api/auth/login", json={"email": "pm@example.com", "password": "nope"}
        )
        assert resp.status_code == 401

    def test_unknown_user_is_401(
        self, client: TestClient, password_login_on: None
    ) -> None:
        resp = client.post(
            "/api/auth/login", json={"email": "nobody@example.com", "password": "Secret123!"}
        )
        assert resp.status_code == 401

    def test_user_without_password_cannot_log_in(
        self, client: TestClient, db_session: Session, password_login_on: None
    ) -> None:
        get_or_create_user(db_session, "entra-only@example.com", "Entra Only")
        db_session.commit()
        resp = client.post(
            "/api/auth/login",
            json={"email": "entra-only@example.com", "password": "whatever"},
        )
        assert resp.status_code == 401


class TestAdminOnboarding:
    def test_admin_sets_password_and_role_then_user_can_log_in(
        self, client: TestClient, db_session: Session, password_login_on: None
    ) -> None:
        user = get_or_create_user(db_session, "newbie@example.com", "Newbie")
        db_session.commit()

        resp = client.post(
            f"/api/users/{user.id}/credentials",
            json={"password": "BrandNew123", "role": "Project Manager"},
        )
        assert resp.status_code == 200

        login = client.post(
            "/api/auth/login",
            json={"email": "newbie@example.com", "password": "BrandNew123"},
        )
        assert login.status_code == 200
        assert login.json()["role"] == "Project Manager"

    def test_project_manager_cannot_set_credentials(
        self, client: TestClient, db_session: Session, password_login_on: None
    ) -> None:
        user = get_or_create_user(db_session, "x@example.com", "X")
        db_session.commit()
        resp = client.post(
            f"/api/users/{user.id}/credentials",
            json={"password": "BrandNew123", "role": "System Admin"},
            headers={"X-User-Role": "Project Manager"},
        )
        assert resp.status_code == 403


class TestChangePassword:
    def test_change_password_flow(
        self, client: TestClient, db_session: Session, password_login_on: None
    ) -> None:
        user = get_or_create_user(db_session, "changer@example.com", "Changer")
        user.password_hash = hash_password("OldPass123")
        user.role = "System Admin"
        db_session.commit()

        login = client.post(
            "/api/auth/login",
            json={"email": "changer@example.com", "password": "OldPass123"},
        ).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

        bad = client.post(
            "/api/auth/change-password",
            json={"current_password": "wrong", "new_password": "NewPass123"},
            headers=headers,
        )
        assert bad.status_code == 401

        ok = client.post(
            "/api/auth/change-password",
            json={"current_password": "OldPass123", "new_password": "NewPass123"},
            headers=headers,
        )
        assert ok.status_code == 200

        assert (
            client.post(
                "/api/auth/login",
                json={"email": "changer@example.com", "password": "OldPass123"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login",
                json={"email": "changer@example.com", "password": "NewPass123"},
            ).status_code
            == 200
        )


class TestMigrationColumns:
    def test_user_row_has_local_login_columns(self, db_session: Session) -> None:
        user = get_or_create_user(db_session, "cols@example.com", "Cols")
        db_session.commit()
        row = db_session.scalar(select(models.User).where(models.User.upn == "cols@example.com"))
        assert row is not None
        assert row.password_hash is None
        assert row.role is None
        assert user.password_hash is None
