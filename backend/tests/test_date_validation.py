"""Server-side project/risk date validation.

The UI validates too, but the API must reject invalid dates regardless of
client, so these tests exercise the backend directly.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import models


def _headers(user_id: int | None = None, role: str = "System Admin") -> dict[str, str]:
    headers = {"X-User-Role": role}
    if user_id is not None:
        headers["X-User-Id"] = str(user_id)
    return headers


def _project(client: TestClient, *, start: str | None, end: str | None) -> dict:
    payload: dict[str, object] = {
        "name": "Date project",
        "department": "D",
        "project_type": "T",
        "customer": "C",
    }
    if start is not None:
        payload["start_date"] = start
    if end is not None:
        payload["end_date"] = end
    resp = client.post("/api/projects", json=payload, headers=_headers(7, "Project Manager"))
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestProjectDates:
    def test_end_before_start_is_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/api/projects",
            json={
                "name": "Bad dates",
                "department": "D",
                "project_type": "T",
                "customer": "C",
                "start_date": "2026-10-20",
                "end_date": "2026-10-10",
            },
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 422
        assert "end date cannot be earlier" in resp.text.lower()

    def test_valid_order_is_accepted(self, client: TestClient) -> None:
        project = _project(client, start="2026-10-10", end="2026-10-20")
        assert project["start_date"] == "2026-10-10"
        assert project["end_date"] == "2026-10-20"

    def test_pm_identity_recorded_on_project(
        self, client: TestClient, db_session: Session
    ) -> None:
        pm = models.User(upn="pm7@wragby.com", display_name="PM Seven")
        db_session.add(pm)
        db_session.commit()
        db_session.refresh(pm)
        resp = client.post(
            "/api/projects",
            json={
                "name": "PM identity",
                "department": "D",
                "project_type": "T",
                "customer": "C",
            },
            headers=_headers(pm.id, "Project Manager"),
        )
        assert resp.status_code == 201, resp.text
        project = resp.json()
        assert project["pm_user_id"] == pm.id
        assert project["pm_name"] == "PM Seven"
        assert project["pm_email"] == "pm7@wragby.com"


class TestRiskDates:
    def test_risk_start_before_project_start_is_rejected(self, client: TestClient) -> None:
        project = _project(client, start="2026-10-20", end=None)
        resp = client.post(
            "/api/risks",
            json={
                "project_id": project["id"],
                "description": "Too early",
                "likelihood": "High",
                "impact": "High",
                "risk_start_date": "2026-10-10",
            },
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 422
        assert "project start" in resp.text.lower()

    def test_risk_start_equal_to_project_start_is_allowed(self, client: TestClient) -> None:
        project = _project(client, start="2026-10-20", end=None)
        resp = client.post(
            "/api/risks",
            json={
                "project_id": project["id"],
                "description": "On time",
                "likelihood": "High",
                "impact": "High",
                "risk_start_date": "2026-10-20",
            },
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 201, resp.text

    def test_risk_start_after_project_start_is_allowed(self, client: TestClient) -> None:
        project = _project(client, start="2026-10-20", end=None)
        resp = client.post(
            "/api/risks",
            json={
                "project_id": project["id"],
                "description": "Later",
                "likelihood": "High",
                "impact": "High",
                "risk_start_date": "2026-10-25",
            },
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 201, resp.text

    def test_risk_end_before_start_is_rejected(self, client: TestClient) -> None:
        project = _project(client, start="2026-10-20", end=None)
        resp = client.post(
            "/api/risks",
            json={
                "project_id": project["id"],
                "description": "Backwards",
                "likelihood": "High",
                "impact": "High",
                "risk_start_date": "2026-10-25",
                "risk_end_date": "2026-10-21",
            },
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 422

    def test_editing_risk_start_before_project_start_is_rejected(
        self, client: TestClient
    ) -> None:
        project = _project(client, start="2026-10-20", end=None)
        risk = client.post(
            "/api/risks",
            json={
                "project_id": project["id"],
                "description": "Editable",
                "likelihood": "High",
                "impact": "High",
                "risk_start_date": "2026-10-25",
            },
            headers=_headers(7, "Project Manager"),
        ).json()
        resp = client.patch(
            f"/api/risks/{risk['id']}",
            json={"risk_start_date": "2026-10-01"},
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 422
        assert "project start" in resp.text.lower()

    def test_risk_read_exposes_project_dates(self, client: TestClient) -> None:
        project = _project(client, start="2026-10-20", end=None)
        risk = client.post(
            "/api/risks",
            json={
                "project_id": project["id"],
                "description": "Context",
                "likelihood": "Low",
                "impact": "Low",
                "risk_start_date": "2026-10-20",
            },
            headers=_headers(7, "Project Manager"),
        ).json()
        assert risk["project_name"] == project["name"]
        assert risk["project_start_date"] == "2026-10-20"
