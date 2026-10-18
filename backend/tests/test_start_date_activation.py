"""Start-date driven activation: ``Open -> In Progress``.

Owner assignment and acknowledgement never advance a risk on their own; the
status advances only when the Risk Start Date arrives. The scheduled path is
covered in ``test_scheduler.py``; here we exercise the API/service path.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient


def _headers(user_id: int | None = None, role: str = "System Admin") -> dict[str, str]:
    headers = {"X-User-Role": role}
    if user_id is not None:
        headers["X-User-Id"] = str(user_id)
    return headers


def _project(client: TestClient) -> dict:
    resp = client.post(
        "/api/projects",
        json={
            "name": "Activation project",
            "department": "D",
            "project_type": "T",
            "customer": "C",
        },
        headers=_headers(1, "Project Manager"),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _owner(client: TestClient) -> dict:
    resp = client.post(
        "/api/external-owners",
        json={"full_name": "Activation Owner", "email": "activation-owner@ext.com"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _risk(client: TestClient, project: dict, **extra: object) -> dict:
    payload: dict[str, object] = {
        "project_id": project["id"],
        "description": "Activation risk",
        "likelihood": "High",
        "impact": "High",
    }
    payload.update(extra)
    resp = client.post("/api/risks", json=payload, headers=_headers(1, "Project Manager"))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _past() -> str:
    return (dt.date.today() - dt.timedelta(days=1)).isoformat()


def _future() -> str:
    return (dt.date.today() + dt.timedelta(days=5)).isoformat()


class TestCreateActivation:
    def test_past_start_date_activates_immediately(self, client: TestClient) -> None:
        project = _project(client)
        risk = _risk(client, project, risk_start_date=_past())
        assert risk["status"] == "In Progress"

    def test_future_start_date_stays_open(self, client: TestClient) -> None:
        project = _project(client)
        risk = _risk(client, project, risk_start_date=_future())
        assert risk["status"] == "Open"

    def test_no_start_date_stays_open_even_with_owner(self, client: TestClient) -> None:
        project = _project(client)
        owner = _owner(client)
        risk = _risk(client, project, owner_user_id=owner["id"])
        assert risk["status"] == "Open"
        assert risk["owner_user_id"] == owner["id"]


class TestEditActivation:
    def test_setting_past_start_date_activates(self, client: TestClient) -> None:
        project = _project(client)
        risk = _risk(client, project)
        assert risk["status"] == "Open"

        resp = client.patch(
            f"/api/risks/{risk['id']}",
            json={"risk_start_date": _past()},
            headers=_headers(1, "Project Manager"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "In Progress"

    def test_setting_future_start_date_keeps_open(self, client: TestClient) -> None:
        project = _project(client)
        risk = _risk(client, project)

        resp = client.patch(
            f"/api/risks/{risk['id']}",
            json={"risk_start_date": _future()},
            headers=_headers(1, "Project Manager"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "Open"
