"""Tests for the core association: adding a risk creates/reuses a catalog Risk
and links it to a project via a Project Risk instance."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models


def _project(client: TestClient, name: str) -> dict:
    return client.post(
        "/api/projects",
        json={"name": name, "department": "D", "project_type": "T"},
    ).json()


def _catalog_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(models.RiskCatalog)) or 0)


def _instances(db: Session) -> list[models.ProjectRisk]:
    return list(db.scalars(select(models.ProjectRisk)).all())


def test_add_brand_new_risk_creates_catalog_and_project_risk(
    client: TestClient, db_session: Session
) -> None:
    project = _project(client, "Alpha")

    resp = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "Vendor onboarding overdue",
            "category": "Operational",
            "likelihood": "High",
            "impact": "Medium",
        },
    )
    assert resp.status_code == 201

    catalogs = db_session.scalars(select(models.RiskCatalog)).all()
    assert len(catalogs) == 1
    assert catalogs[0].description == "Vendor onboarding overdue"
    assert catalogs[0].category == "Operational"

    instances = _instances(db_session)
    assert len(instances) == 1
    assert instances[0].project_id == project["id"]
    assert instances[0].risk_id == catalogs[0].id
    assert instances[0].status == "Suggested"


def test_add_same_concept_reuses_catalog_entry(client: TestClient, db_session: Session) -> None:
    """Re-adding the same normalized description + category dedups to one catalog entry."""
    p1 = _project(client, "Alpha")
    p2 = _project(client, "Beta")

    for pid in (p1["id"], p2["id"]):
        resp = client.post(
            "/api/risks",
            json={
                "project_id": pid,
                "description": "  Vendor onboarding overdue  ",
                "category": "operational",
                "likelihood": "Low",
                "impact": "Low",
            },
        )
        assert resp.status_code == 201

    assert _catalog_count(db_session) == 1
    instances = _instances(db_session)
    assert len(instances) == 2
    assert instances[0].risk_id == instances[1].risk_id


def test_attach_existing_catalog_risk_creates_only_link(
    client: TestClient, db_session: Session
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

    resp = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "catalog_risk_id": catalog["id"],
            "likelihood": "Low",
            "impact": "High",
        },
    )
    assert resp.status_code == 201

    # No new catalog entry was created — the existing one is reused.
    assert _catalog_count(db_session) == 1

    instances = _instances(db_session)
    assert len(instances) == 1
    assert instances[0].risk_id == catalog["id"]
    assert instances[0].project_id == project["id"]

    # The response carries the catalog's concept fields.
    assert resp.json()["description"] == "Vendor onboarding paperwork outstanding"


def test_attach_missing_catalog_risk_422(client: TestClient, db_session: Session) -> None:
    project = _project(client, "Alpha")

    resp = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "catalog_risk_id": 99999,
            "likelihood": "Low",
            "impact": "Low",
        },
    )
    assert resp.status_code == 422


def test_create_requires_catalog_or_description(client: TestClient, db_session: Session) -> None:
    project = _project(client, "Alpha")

    resp = client.post(
        "/api/risks",
        json={"project_id": project["id"], "likelihood": "Low", "impact": "Low"},
    )
    assert resp.status_code == 422
