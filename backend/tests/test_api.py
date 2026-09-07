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
    assert data["name"] is None  # brand-new risk has no catalog short name yet
    assert data["risk_id"] is not None


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


def test_list_all_risks_across_projects(client: TestClient) -> None:
    """The global register returns risks from every project, regardless of project."""
    p1 = client.post(
        "/api/projects", json={"name": "Alpha", "department": "D", "project_type": "T"}
    ).json()
    p2 = client.post(
        "/api/projects", json={"name": "Beta", "department": "D", "project_type": "T"}
    ).json()
    r1 = client.post(
        "/api/risks",
        json={"project_id": p1["id"], "description": "r1", "likelihood": "Low", "impact": "Low"},
    ).json()
    r2 = client.post(
        "/api/risks",
        json={"project_id": p2["id"], "description": "r2", "likelihood": "High", "impact": "High"},
    ).json()

    resp = client.get("/api/risks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {r["id"] for r in data} == {r1["id"], r2["id"]}


def test_projects_list_includes_risk_count(client: TestClient) -> None:
    """The projects table's risk count reflects Project Risk rows."""
    p = client.post(
        "/api/projects", json={"name": "P", "department": "D", "project_type": "T"}
    ).json()
    for desc in ("r1", "r2"):
        client.post(
            "/api/risks",
            json={"project_id": p["id"], "description": desc, "likelihood": "Low", "impact": "Low"},
        )

    resp = client.get("/api/projects")
    assert resp.status_code == 200
    match = [x for x in resp.json() if x["id"] == p["id"]]
    assert len(match) == 1
    assert match[0]["risk_count"] == 2
    assert len(match[0]["risk_ids"]) == 2
    assert len(match[0]["risk_names"]) == 2
