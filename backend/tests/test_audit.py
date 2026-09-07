"""Issue #01: status transitions + append-only audit trail."""

from __future__ import annotations

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
        "impact": "Medium",
        **overrides,
    }
    return client.post("/api/risks", json=payload).json()


def test_transition_writes_audit(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"])
    assert risk["status"] == "Suggested"

    resp = client.patch(f"/api/risks/{risk['id']}", json={"status": "Open"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "Open"

    history = client.get(f"/api/risks/{risk['id']}/history").json()
    assert len(history) == 1
    assert history[0]["action"] == "status_change"
    assert history[0]["field"] == "status"
    assert history[0]["old_value"] == "Suggested"
    assert history[0]["new_value"] == "Open"


def test_invalid_transition_rejected(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"])
    resp = client.patch(f"/api/risks/{risk['id']}", json={"status": "Closed"})
    assert resp.status_code == 409


def test_field_edit_writes_audit(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"])
    resp = client.patch(f"/api/risks/{risk['id']}", json={"description": "updated"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "updated"

    history = client.get(f"/api/risks/{risk['id']}/history").json()
    assert any(e["action"] == "field_edit" and e["field"] == "description" for e in history)


def test_rating_recomputed_on_likelihood_change(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"])  # High x Medium -> High
    assert risk["risk_rating"] == "High"

    resp = client.patch(f"/api/risks/{risk['id']}", json={"likelihood": "Low"})
    assert resp.status_code == 200
    assert resp.json()["risk_rating"] == "Low"  # Low x Medium -> Low

    fields = [e["field"] for e in client.get(f"/api/risks/{risk['id']}/history").json()]
    assert "likelihood" in fields
    assert "risk_rating" in fields


def test_acknowledge_idempotent(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"])

    resp = client.post(f"/api/risks/{risk['id']}/acknowledge")
    assert resp.status_code == 200
    assert resp.json()["sla_acknowledged"] is True

    client.post(f"/api/risks/{risk['id']}/acknowledge")  # idempotent
    history = client.get(f"/api/risks/{risk['id']}/history").json()
    assert len([e for e in history if e["action"] == "acknowledge"]) == 1


def test_clear_nullable_field(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"], category="Technical")
    assert risk["category"] == "Technical"

    resp = client.patch(f"/api/risks/{risk['id']}", json={"category": None})
    assert resp.status_code == 200
    assert resp.json()["category"] is None


def test_cannot_clear_non_nullable_field(client: TestClient) -> None:
    project = _create_project(client)
    risk = _create_risk(client, project["id"])
    resp = client.patch(f"/api/risks/{risk['id']}", json={"description": None})
    assert resp.status_code == 422
