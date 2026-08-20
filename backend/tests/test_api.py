"""End-to-end API tests (tracer bullet): project + risk creation."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_project(client: TestClient) -> None:
    resp = client.post(
        "/api/projects",
        json={
            "name": "NHIA Cloud Migration",
            "department": "Digital Advisory",
            "project_type": "Cloud Migration",
            "customer": "NHIA",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["project_code"].startswith("PRJ-")
    assert data["department_name"] == "Digital Advisory"
    assert data["project_type_name"] == "Cloud Migration"
    assert data["status"] == "Active"


def test_get_project(client: TestClient) -> None:
    created = client.post(
        "/api/projects",
        json={"name": "X", "department": "D", "project_type": "T"},
    ).json()

    resp = client.get(f"/api/projects/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["project_code"] == created["project_code"]


def test_get_missing_project_404(client: TestClient) -> None:
    resp = client.get("/api/projects/99999")
    assert resp.status_code == 404


def test_create_risk_computes_rating(client: TestClient) -> None:
    project = client.post(
        "/api/projects",
        json={"name": "P", "department": "D", "project_type": "T"},
    ).json()

    resp = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "Delay in AWS account provisioning",
            "likelihood": "High",
            "impact": "Medium",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["risk_rating"] == "High"  # High x Medium -> High (3x3 matrix)
    assert data["status"] == "Suggested"
    assert data["risk_code"].startswith("RSK-")


def test_create_risk_rejects_invalid_rating(client: TestClient) -> None:
    project = client.post(
        "/api/projects",
        json={"name": "P2", "department": "D", "project_type": "T"},
    ).json()

    resp = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "x",
            "likelihood": "Critical",
            "impact": "High",
        },
    )
    assert resp.status_code == 422  # Literal validation rejects "Critical"
