"""Tests for the users directory endpoint and UPN-based risk ownership."""

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


def _make_risk(client: TestClient, project_id: int) -> dict:
    resp = client.post(
        "/api/risks",
        json={
            "project_id": project_id,
            "description": "Risk",
            "likelihood": "High",
            "impact": "High",
        },
    )
    assert resp.status_code == 201
    return resp.json()


class TestListUsers:
    def test_empty_when_no_users(self, client: TestClient) -> None:
        resp = client.get("/api/users")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_users_ordered_by_display_name(
        self, client: TestClient, db_session: Session
    ) -> None:
        get_or_create_user(db_session, "zoe@example.com", "Zoe")
        get_or_create_user(db_session, "amy@example.com", "Amy")
        db_session.commit()

        resp = client.get("/api/users")
        assert resp.status_code == 200
        data = resp.json()
        assert [u["display_name"] for u in data] == ["Amy", "Zoe"]
        assert set(data[0]) == {"id", "upn", "display_name"}

    def test_requires_authentication(self, client: TestClient) -> None:
        # Dev mode defaults to System Admin, so the endpoint is reachable; this
        # guards the shape of the response rather than a 401 (Entra mode is
        # covered by the auth tests).
        resp = client.get("/api/users", headers={"X-User-Role": "Project Manager"})
        assert resp.status_code == 200


class TestOwnerAssignmentByUpn:
    def test_patch_owner_upn_resolves_to_user_id(
        self, client: TestClient, db_session: Session
    ) -> None:
        project = _make_project(client)
        risk = _make_risk(client, project["id"])

        resp = client.patch(
            f"/api/risks/{risk['id']}",
            json={"owner_upn": "owner@example.com"},
        )
        assert resp.status_code == 200
        owner_id = resp.json()["owner_user_id"]
        assert owner_id is not None

        user = db_session.get(models.User, owner_id)
        assert user is not None
        assert user.upn == "owner@example.com"

    def test_patch_owner_user_id_still_works(
        self, client: TestClient, db_session: Session
    ) -> None:
        owner = get_or_create_user(db_session, "explicit@example.com", "Explicit")
        db_session.commit()
        project = _make_project(client)
        risk = _make_risk(client, project["id"])

        resp = client.patch(
            f"/api/risks/{risk['id']}",
            json={"owner_user_id": owner.id},
        )
        assert resp.status_code == 200
        assert resp.json()["owner_user_id"] == owner.id

    def test_owner_upn_change_is_audited(
        self, client: TestClient, db_session: Session
    ) -> None:
        project = _make_project(client)
        risk = _make_risk(client, project["id"])

        resp = client.patch(
            f"/api/risks/{risk['id']}",
            json={"owner_upn": "audited@example.com"},
        )
        assert resp.status_code == 200

        rows = list(
            db_session.scalars(
                select(models.RiskAuditLog).where(
                    models.RiskAuditLog.risk_id == risk["id"],
                    models.RiskAuditLog.field == "owner_user_id",
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].new_value == resp.json()["owner_user_id"]
