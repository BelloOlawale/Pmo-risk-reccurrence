"""API tests for the shared Risk catalog read and write endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from riskapp import models


def test_list_catalog(client: TestClient, db_session: Session) -> None:
    db_session.add(
        models.RiskCatalog(
            name="Vendor onboarding",
            description="Vendor onboarding paperwork outstanding",
            category="Operational",
        )
    )
    db_session.add(
        models.RiskCatalog(
            description="Budget variance",
            category="Financial",
        )
    )
    db_session.commit()

    resp = client.get("/api/catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    by_description = {r["description"]: r for r in data}
    assert by_description["Vendor onboarding paperwork outstanding"]["name"] == "Vendor onboarding"
    assert by_description["Vendor onboarding paperwork outstanding"]["category"] == "Operational"
    assert by_description["Budget variance"]["name"] is None


def test_get_catalog(client: TestClient, db_session: Session) -> None:
    catalog = models.RiskCatalog(description="Scope creep", category="Schedule")
    db_session.add(catalog)
    db_session.commit()

    resp = client.get(f"/api/catalog/{catalog.id}")
    assert resp.status_code == 200
    assert resp.json()["description"] == "Scope creep"
    assert resp.json()["category"] == "Schedule"


def test_get_missing_catalog_404(client: TestClient) -> None:
    resp = client.get("/api/catalog/99999")
    assert resp.status_code == 404


def test_create_catalog(client: TestClient, db_session: Session) -> None:
    resp = client.post(
        "/api/catalog",
        json={
            "name": "Vendor onboarding",
            "description": "Vendor onboarding paperwork outstanding",
            "category": "Operational",
            "subcategory": "Procurement",
            "risk_source": "Human",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Vendor onboarding"
    assert data["description"] == "Vendor onboarding paperwork outstanding"
    assert data["category"] == "Operational"
    assert data["subcategory"] == "Procurement"
    assert data["risk_source"] == "Human"

    # Persisted and now listed.
    listed = client.get("/api/catalog").json()
    assert [r["id"] for r in listed] == [data["id"]]


def test_create_catalog_requires_description(client: TestClient) -> None:
    resp = client.post("/api/catalog", json={"name": "Missing description"})
    assert resp.status_code == 422


def test_rename_catalog(client: TestClient, db_session: Session) -> None:
    catalog = models.RiskCatalog(description="Scope creep", category="Schedule")
    db_session.add(catalog)
    db_session.commit()

    resp = client.patch(f"/api/catalog/{catalog.id}", json={"name": "Scope creep"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Scope creep"
    # Untouched fields remain.
    assert data["description"] == "Scope creep"
    assert data["category"] == "Schedule"


def test_rename_catalog_missing_404(client: TestClient) -> None:
    resp = client.patch("/api/catalog/99999", json={"name": "x"})
    assert resp.status_code == 404


def _project_with_risk(
    db_session: Session,
    catalog: models.RiskCatalog,
) -> models.ProjectRisk:
    department = models.Department(name="D")
    project_type = models.ProjectType(name="T")
    db_session.add_all([department, project_type])
    db_session.flush()
    project = models.Project(
        name="P",
        project_code="PRJ-1",
        status="Active",
        department_id=department.id,
        project_type_id=project_type.id,
    )
    db_session.add(project)
    db_session.flush()
    instance = models.ProjectRisk(
        project_id=project.id,
        risk_id=catalog.id,
        likelihood="High",
        impact="High",
        risk_rating="High",
        status="Suggested",
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)
    return instance


def test_merge_catalog_repoints_project_risks(
    client: TestClient, db_session: Session
) -> None:
    survivor = models.RiskCatalog(
        name="Vendor onboarding",
        description="Vendor onboarding paperwork",
        category="Operational",
    )
    absorbed = models.RiskCatalog(
        description="vendor onboarding overdue", category="Operational"
    )
    db_session.add_all([survivor, absorbed])
    db_session.commit()

    instance = _project_with_risk(db_session, absorbed)

    resp = client.post(
        "/api/catalog/merge",
        json={"survivor_id": survivor.id, "absorbed_id": absorbed.id},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == survivor.id

    # The absorbed entry is gone.
    remaining = db_session.scalar(
        text("SELECT COUNT(*) FROM risk_catalog WHERE id = :id"), {"id": absorbed.id}
    )
    assert remaining == 0

    # The Project Risk is re-pointed at the survivor.
    risk_id = db_session.scalar(
        text("SELECT risk_id FROM project_risks WHERE id = :id"), {"id": instance.id}
    )
    assert risk_id == survivor.id


def test_merge_catalog_missing_404(client: TestClient, db_session: Session) -> None:
    survivor = models.RiskCatalog(description="a")
    db_session.add(survivor)
    db_session.commit()

    resp = client.post(
        "/api/catalog/merge",
        json={"survivor_id": survivor.id, "absorbed_id": 99999},
    )
    assert resp.status_code == 404


def test_merge_catalog_rejects_self(client: TestClient, db_session: Session) -> None:
    catalog = models.RiskCatalog(description="a")
    db_session.add(catalog)
    db_session.commit()

    resp = client.post(
        "/api/catalog/merge",
        json={"survivor_id": catalog.id, "absorbed_id": catalog.id},
    )
    assert resp.status_code == 422
