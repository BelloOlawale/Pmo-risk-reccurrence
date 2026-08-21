"""Issue #02: SLA deadline assignment + manual override."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient


def _create_project(client: TestClient) -> Any:
    return client.post(
        "/api/projects", json={"name": "P", "department": "D", "project_type": "T"}
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


def test_default_deadline_by_rating(client: TestClient) -> None:
    project = _create_project(client)
    high = _create_risk(client, project["id"], likelihood="High", impact="High")
    medium = _create_risk(client, project["id"], likelihood="Medium", impact="Medium")
    low = _create_risk(client, project["id"], likelihood="Low", impact="Low")

    assert _dt(high["sla_deadline"]) - _dt(high["created_at"]) == timedelta(hours=24)
    assert _dt(medium["sla_deadline"]) - _dt(medium["created_at"]) == timedelta(hours=48)
    assert _dt(low["sla_deadline"]) - _dt(low["created_at"]) == timedelta(hours=120)


def test_manual_override_sets_flag(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"])
    assert risk["sla_manual_override"] is False

    resp = client.patch(
        f"/api/risks/{risk['id']}", json={"sla_deadline": "2026-12-31T23:59:59"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sla_manual_override"] is True
    assert body["sla_deadline"].startswith("2026-12-31")


def test_rating_change_recomputes_deadline(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"], likelihood="High", impact="High")  # 24h

    resp = client.patch(f"/api/risks/{risk['id']}", json={"likelihood": "Low"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_rating"] == "Medium"  # Low x High -> Medium
    assert _dt(body["sla_deadline"]) - _dt(body["created_at"]) == timedelta(hours=48)


def test_override_blocks_recompute(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"], likelihood="High", impact="High")

    client.patch(f"/api/risks/{risk['id']}", json={"sla_deadline": "2026-12-31T23:59:59"})
    resp = client.patch(f"/api/risks/{risk['id']}", json={"likelihood": "Low"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_rating"] == "Medium"  # rating changed...
    assert body["sla_deadline"].startswith("2026-12-31")  # ...but deadline untouched


def test_reset_override_recomputes(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"], likelihood="High", impact="High")

    client.patch(f"/api/risks/{risk['id']}", json={"sla_deadline": "2026-12-31T23:59:59"})
    resp = client.patch(f"/api/risks/{risk['id']}", json={"reset_sla_deadline": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sla_manual_override"] is False
    assert _dt(body["sla_deadline"]) - _dt(body["created_at"]) == timedelta(hours=24)


def test_deadline_from_start_date(client: TestClient) -> None:
    project = _create_project(client)
    # High x High -> High -> 24h from midnight 2026-08-25 Africa/Lagos (= 23:00 UTC on the 24th).
    risk = _create_risk(client, project["id"], risk_start_date="2026-08-25")
    assert _dt(risk["sla_deadline"]) == datetime(2026, 8, 25, 23, 0, 0)


def test_deadline_falls_back_to_created_at_when_no_start_date(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"], likelihood="High", impact="High")
    assert _dt(risk["sla_deadline"]) - _dt(risk["created_at"]) == timedelta(hours=24)


def test_start_date_change_recomputes_deadline(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"], risk_start_date="2026-08-25")
    assert _dt(risk["sla_deadline"]) == datetime(2026, 8, 25, 23, 0, 0)

    resp = client.patch(f"/api/risks/{risk['id']}", json={"risk_start_date": "2026-08-30"})
    assert resp.status_code == 200
    assert _dt(resp.json()["sla_deadline"]) == datetime(2026, 8, 30, 23, 0, 0)


def test_override_blocks_start_date_recompute(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"], risk_start_date="2026-08-25")

    client.patch(f"/api/risks/{risk['id']}", json={"sla_deadline": "2026-12-31T23:59:59"})
    resp = client.patch(f"/api/risks/{risk['id']}", json={"risk_start_date": "2026-08-30"})
    assert resp.status_code == 200
    assert resp.json()["sla_deadline"].startswith("2026-12-31")


def test_clearing_start_date_falls_back_to_created_at(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"], risk_start_date="2026-08-25")

    resp = client.patch(f"/api/risks/{risk['id']}", json={"risk_start_date": None})
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_start_date"] is None
    assert _dt(body["sla_deadline"]) - _dt(body["created_at"]) == timedelta(hours=24)
