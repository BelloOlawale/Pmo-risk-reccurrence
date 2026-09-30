"""Deleting a risk from the Risk Register (PM / PMO Lead / System Admin)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models


def _headers(user_id: int | None, role: str) -> dict[str, str]:
    headers = {"X-User-Role": role}
    if user_id is not None:
        headers["X-User-Id"] = str(user_id)
    return headers


def _project(client: TestClient, user_id: int) -> dict:
    resp = client.post(
        "/api/projects",
        json={"name": f"P{user_id}", "department": "D", "project_type": "T", "customer": "C"},
        headers=_headers(user_id, "Project Manager"),
    )
    assert resp.status_code == 201
    return resp.json()


def _risk(client: TestClient, project: dict, user_id: int) -> dict:
    resp = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "Delete me",
            "likelihood": "Low",
            "impact": "Low",
        },
        headers=_headers(user_id, "Project Manager"),
    )
    assert resp.status_code == 201
    return resp.json()


def test_pm_can_delete_own_risk(client: TestClient) -> None:
    project = _project(client, 7)
    risk = _risk(client, project, 7)

    resp = client.delete(f"/api/risks/{risk['id']}", headers=_headers(7, "Project Manager"))
    assert resp.status_code == 204
    assert client.get(f"/api/risks/{risk['id']}").status_code == 404


def test_other_pm_cannot_delete(client: TestClient) -> None:
    project = _project(client, 7)
    risk = _risk(client, project, 7)

    resp = client.delete(f"/api/risks/{risk['id']}", headers=_headers(8, "Project Manager"))
    assert resp.status_code == 403
    assert client.get(f"/api/risks/{risk['id']}").status_code == 200


def test_delete_removes_related_issue_and_audit(client: TestClient, db_session: Session) -> None:
    project = _project(client, 7)
    risk = _risk(client, project, 7)

    # Materialize to create the single linked Issue.
    assert (
        client.patch(
            f"/api/risks/{risk['id']}",
            json={"status": "Event", "actor_user_id": 7},
            headers=_headers(7, "Project Manager"),
        ).status_code
        == 200
    )
    assert db_session.scalar(
        select(models.Issue).where(models.Issue.source_risk_id == risk["id"])
    ) is not None
    assert db_session.scalars(
        select(models.RiskAuditLog).where(models.RiskAuditLog.risk_id == risk["id"])
    ).all()

    resp = client.delete(f"/api/risks/{risk['id']}", headers=_headers(7, "Project Manager"))
    assert resp.status_code == 204

    assert db_session.scalar(
        select(models.Issue).where(models.Issue.source_risk_id == risk["id"])
    ) is None
    assert (
        db_session.scalars(
            select(models.RiskAuditLog).where(models.RiskAuditLog.risk_id == risk["id"])
        ).all()
        == []
    )


def test_system_admin_can_delete(client: TestClient) -> None:
    project = _project(client, 7)
    risk = _risk(client, project, 7)

    resp = client.delete(f"/api/risks/{risk['id']}", headers=_headers(None, "System Admin"))
    assert resp.status_code == 204
