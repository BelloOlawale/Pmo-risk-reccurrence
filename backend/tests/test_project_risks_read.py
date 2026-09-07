"""Tests for the project-level risk read path: the risks list and count now
join through the Project Risk entity to the catalog Risk."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _project(client: TestClient, name: str) -> dict:
    return client.post(
        "/api/projects",
        json={"name": name, "department": "D", "project_type": "T"},
    ).json()


def test_project_risks_list_joins_catalog_with_short_name(
    client: TestClient,
) -> None:
    project = _project(client, "Alpha")
    catalog = client.post(
        "/api/catalog",
        json={
            "name": "Vendor onboarding",
            "description": "Vendor onboarding paperwork outstanding",
            "category": "Operational",
        },
    ).json()

    client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "catalog_risk_id": catalog["id"],
            "likelihood": "High",
            "impact": "Medium",
        },
    )

    resp = client.get(f"/api/projects/{project['id']}/risks")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Vendor onboarding"
    assert rows[0]["description"] == "Vendor onboarding paperwork outstanding"
    assert rows[0]["category"] == "Operational"
    assert rows[0]["risk_id"] == catalog["id"]
    assert rows[0]["project_id"] == project["id"]
    assert rows[0]["status"] == "Suggested"
    assert rows[0]["risk_rating"] == "High"


def test_project_risks_list_returns_multiple_instances(
    client: TestClient,
) -> None:
    project = _project(client, "Alpha")
    for desc in ("Vendor delay", "Budget variance"):
        client.post(
            "/api/risks",
            json={
                "project_id": project["id"],
                "description": desc,
                "likelihood": "Low",
                "impact": "Low",
            },
        )

    resp = client.get(f"/api/projects/{project['id']}/risks")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert {r["description"] for r in rows} == {"Vendor delay", "Budget variance"}
    # Brand-new risks have no short name until renamed in the catalog.
    assert all(r["name"] is None for r in rows)


def test_project_risk_count_reflects_project_risks(
    client: TestClient,
) -> None:
    project = _project(client, "Alpha")
    for desc in ("r1", "r2", "r3"):
        client.post(
            "/api/risks",
            json={
                "project_id": project["id"],
                "description": desc,
                "likelihood": "Medium",
                "impact": "Medium",
            },
        )

    resp = client.get(f"/api/projects/{project['id']}")
    assert resp.status_code == 200
    assert resp.json()["risk_count"] == 3

    # The list endpoint reflects the same count.
    listing = client.get("/api/projects").json()
    match = [x for x in listing if x["id"] == project["id"]]
    assert match[0]["risk_count"] == 3
