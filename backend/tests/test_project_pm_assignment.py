"""Tests for (re)assigning a project's Project Manager after creation.

Each register (project) has its own PM, so the PM must be changeable without
recreating the project. Only PMO Lead / System Admin may reassign.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.services import get_or_create_user


def _make_project(client: TestClient) -> dict:
    resp = client.post(
        "/api/projects",
        json={"name": "P", "department": "D", "project_type": "T", "customer": "C"},
    )
    assert resp.status_code == 201
    return resp.json()


class TestAssignProjectManager:
    def test_assign_by_upn(self, client: TestClient, db_session: Session) -> None:
        project = _make_project(client)

        resp = client.patch(
            f"/api/projects/{project['id']}",
            json={"pm_upn": "pm1@example.com"},
        )
        assert resp.status_code == 200
        pm_id = resp.json()["pm_user_id"]
        assert pm_id is not None

        user = db_session.get(models.User, pm_id)
        assert user is not None and user.upn == "pm1@example.com"

    def test_reassign_to_a_different_pm(self, client: TestClient, db_session: Session) -> None:
        first = get_or_create_user(db_session, "pm1@example.com", "PM One")
        second = get_or_create_user(db_session, "pm2@example.com", "PM Two")
        db_session.commit()
        project = _make_project(client)

        client.patch(f"/api/projects/{project['id']}", json={"pm_user_id": first.id})
        resp = client.patch(f"/api/projects/{project['id']}", json={"pm_user_id": second.id})

        assert resp.status_code == 200
        assert resp.json()["pm_user_id"] == second.id
        refreshed = db_session.scalar(
            select(models.Project).where(models.Project.id == project["id"])
        )
        assert refreshed is not None and refreshed.pm_user_id == second.id

    def test_different_projects_can_have_different_pms(
        self, client: TestClient, db_session: Session
    ) -> None:
        pm_a = get_or_create_user(db_session, "a@example.com", "A")
        pm_b = get_or_create_user(db_session, "b@example.com", "B")
        db_session.commit()
        p1 = _make_project(client)
        p2 = _make_project(client)

        client.patch(f"/api/projects/{p1['id']}", json={"pm_user_id": pm_a.id})
        client.patch(f"/api/projects/{p2['id']}", json={"pm_user_id": pm_b.id})

        assert (
            db_session.get(models.Project, p1["id"]).pm_user_id  # type: ignore[union-attr]
            == pm_a.id
        )
        assert (
            db_session.get(models.Project, p2["id"]).pm_user_id  # type: ignore[union-attr]
            == pm_b.id
        )

    def test_clear_pm(self, client: TestClient, db_session: Session) -> None:
        pm = get_or_create_user(db_session, "pm@example.com", "PM")
        db_session.commit()
        project = _make_project(client)
        client.patch(f"/api/projects/{project['id']}", json={"pm_user_id": pm.id})

        resp = client.patch(f"/api/projects/{project['id']}", json={"pm_user_id": None})
        assert resp.status_code == 200
        assert resp.json()["pm_user_id"] is None

    def test_project_manager_role_is_forbidden(self, client: TestClient) -> None:
        project = _make_project(client)
        resp = client.patch(
            f"/api/projects/{project['id']}",
            json={"pm_upn": "x@example.com"},
            headers={"X-User-Role": "Project Manager"},
        )
        assert resp.status_code == 403

    def test_missing_project_returns_404(self, client: TestClient) -> None:
        resp = client.patch("/api/projects/999999", json={"pm_upn": "x@example.com"})
        assert resp.status_code == 404
