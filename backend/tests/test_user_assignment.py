"""Tests for UPN -> user resolution and PM assignment wiring."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models, schemas
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
            schemas.ProjectCreate(name="P", department="D", project_type="T"),
            pm_user_id=pm.id,
        )
        assert project.pm_user_id == pm.id


class TestAddProjectEndpoint:
    def test_pm_upn_is_resolved_to_user_id(self, client: TestClient, db_session: Session) -> None:
        resp = client.post(
            "/api/projects",
            json={
                "name": "P",
                "department": "D",
                "project_type": "T",
                "pm_upn": "pm@example.com",
            },
            headers={"X-User-Role": "Project Manager"},
        )
        assert resp.status_code == 201

        project = db_session.scalar(
            select(models.Project).where(models.Project.id == resp.json()["id"])
        )
        assert project is not None
        assert project.pm_user_id is not None
        user = db_session.get(models.User, project.pm_user_id)
        assert user.upn == "pm@example.com"
