"""Tests for UPN -> user resolution and PM assignment wiring."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import schemas
from riskapp.config import settings
from riskapp.services import create_project, get_or_create_user


class TestGetOrCreateUser:
    def test_upserts_idempotently(self, db_session: Session) -> None:
        first = get_or_create_user(db_session, "alice@example.com", "Alice")
        second = get_or_create_user(db_session, "alice@example.com")
        assert first.id == second.id
        assert second.display_name == "Alice"

    def test_updates_display_name(self, db_session: Session) -> None:
        first = get_or_create_user(db_session, "bob@example.com", "Bob")
        second = get_or_create_user(db_session, "bob@example.com", "Robert")
        assert first.id == second.id
        assert second.display_name == "Robert"


class TestCreateProjectPm:
    def test_create_project_assigns_pm(self, db_session: Session) -> None:
        pm = get_or_create_user(db_session, "pm@example.com", "PM")
        project = create_project(
            db_session,
            schemas.ProjectCreate(name="P", department="D", project_type="T", customer="C"),
            pm_user_id=pm.id,
        )
        assert project.pm_user_id == pm.id


class TestAddProjectEndpoint:
    def test_creator_cannot_assign_another_pm_at_creation(self, client: TestClient) -> None:
        resp = client.post(
            "/api/projects",
            json={
                "name": "P",
                "department": "D",
                "project_type": "T",
                "customer": "C",
                "pm_upn": "someone-else@example.com",
            },
            headers={"X-User-Role": "Project Manager", "X-User-Id": "7"},
        )
        assert resp.status_code == 422

    def test_bearer_authenticated_pm_owns_and_sees_new_register(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "test_login_enabled", True)
        monkeypatch.setattr(settings, "test_login_code", "")
        monkeypatch.setattr(settings, "test_login_secret", "project-creation-test-signing-key-123")
        login = client.post(
            "/api/auth/test-login",
            json={"role": "Project Manager", "upn": "creator@example.com"},
        )
        assert login.status_code == 200
        monkeypatch.setattr(settings, "entra_tenant_id", "test-tenant")
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        me = client.get("/api/me", headers=headers).json()

        created = client.post(
            "/api/projects",
            json={"name": "Mine", "department": "D", "project_type": "T", "customer": "C"},
            headers=headers,
        )
        assert created.status_code == 201
        assert created.json()["pm_user_id"] == me["user_id"]
        assert client.get("/api/projects", headers=headers).json()[0]["id"] == created.json()["id"]
        directory = client.get("/api/users", headers=headers).json()
        assert any(user["id"] == me["user_id"] and user["upn"] == me["upn"] for user in directory)

    def test_existing_register_cannot_be_reassigned(self, client: TestClient) -> None:
        created = client.post(
            "/api/projects",
            json={"name": "Mine", "department": "D", "project_type": "T", "customer": "C"},
        )
        assert created.status_code == 201
        project = created.json()

        response = client.patch(
            f"/api/projects/{project['id']}",
            json={"pm_upn": "someone-else@example.com"},
        )
        assert response.status_code == 405
        current = client.get(f"/api/projects/{project['id']}").json()
        assert current["pm_user_id"] == project["pm_user_id"]

    def test_dev_pm_without_selected_user_can_see_created_register(
        self, client: TestClient
    ) -> None:
        headers = {"X-User-Role": "Project Manager"}
        created = client.post(
            "/api/projects",
            json={"name": "Mine", "department": "D", "project_type": "T", "customer": "C"},
            headers=headers,
        )
        assert created.status_code == 201
        me = client.get("/api/me", headers=headers).json()
        assert created.json()["pm_user_id"] == me["user_id"]
        assert me["user_id"] is not None
        assert client.get("/api/projects", headers=headers).json()[0]["id"] == created.json()["id"]

    def test_system_admin_is_recorded_as_pm_when_creating_register(
        self, client: TestClient
    ) -> None:
        created = client.post(
            "/api/projects",
            json={"name": "Admin", "department": "D", "project_type": "T", "customer": "C"},
        )
        assert created.status_code == 201
        pm_id = created.json()["pm_user_id"]
        assert pm_id is not None
        users = client.get("/api/users").json()
        assert any(user["id"] == pm_id and user["upn"] == "dev@local" for user in users)

    def test_pmo_lead_cannot_create_register(self, client: TestClient) -> None:
        created = client.post(
            "/api/projects",
            json={"name": "PMO", "department": "D", "project_type": "T", "customer": "C"},
            headers={"X-User-Role": "PMO Lead"},
        )
        assert created.status_code == 403
