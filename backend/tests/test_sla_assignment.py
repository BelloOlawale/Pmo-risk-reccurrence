"""SLA dates are set manually by the PM, never derived from the risk rating.

The Risk Start Date is the SLA start and the Risk End Date *is* the SLA
deadline. Both dates may be backdated; the only rule is that the end date must
not be earlier than the start date.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient


def _create_project(client: TestClient) -> Any:
    return client.post(
        "/api/projects", json={"name": "P", "department": "D", "project_type": "T", "customer": "C"}
    ).json()


def _create_risk(client: TestClient, project_id: int, **overrides: object) -> Any:
    payload = {
        "project_id": project_id,
        "description": "a risk",
        "likelihood": "High",
        "impact": "High",
        **overrides,
    }
    return client.post("/api/risks", json=payload).json()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_rating_does_not_determine_the_deadline(client: TestClient) -> None:
    """High / Medium / Low with identical dates get identical deadlines."""
    project = _create_project(client)
    kwargs = {"risk_start_date": "2099-08-25", "risk_end_date": "2099-09-05"}
    high = _create_risk(client, project["id"], likelihood="High", impact="High", **kwargs)
    medium = _create_risk(
        client, project["id"], likelihood="Medium", impact="Medium", **kwargs
    )
    low = _create_risk(client, project["id"], likelihood="Low", impact="Low", **kwargs)

    assert high["sla_deadline"] == medium["sla_deadline"] == low["sla_deadline"]
    assert high["risk_end_date"] == "2099-09-05"


def test_deadline_is_end_of_the_risk_end_date_in_business_tz(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(
        client,
        project["id"],
        risk_start_date="2099-08-25",
        risk_end_date="2099-08-30",
    )
    # End of 2099-08-30 in Africa/Lagos (UTC+1) == 2099-08-30 22:59:59.999999 UTC.
    assert _dt(risk["sla_deadline"]) == datetime(2099, 8, 30, 22, 59, 59, 999999)


def test_no_end_date_means_no_deadline(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"], risk_start_date="2099-08-25")
    assert risk["risk_end_date"] is None
    assert risk["sla_deadline"] is None


def test_risk_end_date_is_client_settable(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"], risk_end_date="2099-09-05")
    assert risk["risk_end_date"] == "2099-09-05"

    resp = client.patch(f"/api/risks/{risk['id']}", json={"risk_end_date": "2099-09-10"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_end_date"] == "2099-09-10"
    assert _dt(body["sla_deadline"]) == datetime(2099, 9, 10, 22, 59, 59, 999999)


def test_end_before_start_rejected_on_create(client: TestClient) -> None:
    project = _create_project(client)
    resp = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "bad dates",
            "likelihood": "High",
            "impact": "High",
            "risk_start_date": "2099-09-10",
            "risk_end_date": "2099-09-05",
        },
    )
    assert resp.status_code == 422


def test_end_before_start_rejected_on_update(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(
        client,
        project["id"],
        risk_start_date="2099-09-05",
        risk_end_date="2099-09-10",
    )
    resp = client.patch(f"/api/risks/{risk['id']}", json={"risk_end_date": "2099-09-01"})
    assert resp.status_code == 422


def test_backdated_risk_start_date_allowed(client: TestClient) -> None:
    project = _create_project(client)
    resp = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "historical risk",
            "likelihood": "High",
            "impact": "High",
            "risk_start_date": "2000-01-01",
            "risk_end_date": "2000-02-01",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["risk_start_date"] == "2000-01-01"


def test_backdated_project_start_date_allowed(client: TestClient) -> None:
    resp = client.post(
        "/api/projects",
        json={
            "name": "Backdated",
            "department": "D",
            "project_type": "T",
            "customer": "C",
            "start_date": "2000-01-01",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["start_date"] == "2000-01-01"


def test_project_end_before_start_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/projects",
        json={
            "name": "Bad dates",
            "department": "D",
            "project_type": "T",
            "customer": "C",
            "start_date": "2099-09-10",
            "end_date": "2099-09-05",
        },
    )
    assert resp.status_code == 422
    assert "end date cannot be earlier" in str(resp.json()).lower()
