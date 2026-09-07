"""Tests for the backend-derived Active Risk Register."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import models


def _project(db: Session, code: str, status: str = "Active") -> models.Project:
    department = models.Department(name=f"D-{code}")
    project_type = models.ProjectType(name=f"T-{code}")
    db.add_all([department, project_type])
    db.flush()
    project = models.Project(
        name=f"P {code}",
        project_code=code,
        status=status,
        department_id=department.id,
        project_type_id=project_type.id,
    )
    db.add(project)
    db.flush()
    return project


def _catalog(db: Session, description: str) -> models.RiskCatalog:
    catalog = models.RiskCatalog(description=description)
    db.add(catalog)
    db.flush()
    return catalog


def _instance(
    db: Session,
    project: models.Project,
    catalog: models.RiskCatalog,
    status: str,
) -> models.ProjectRisk:
    instance = models.ProjectRisk(
        project_id=project.id,
        risk_id=catalog.id,
        likelihood="Low",
        impact="Low",
        risk_rating="Low",
        status=status,
    )
    db.add(instance)
    db.flush()
    return instance


def test_active_register_derivation_rule(client: TestClient, db_session: Session) -> None:
    """The four project/risk combinations: only Active project + non-finished risk shows."""
    active = _project(db_session, "PRJ-ACTIVE", status="Active")
    closed_project = _project(db_session, "PRJ-CLOSED", status="Closed")

    open_risk = _catalog(db_session, "Open risk")
    resolved_risk = _catalog(db_session, "Resolved risk")
    closed_risk = _catalog(db_session, "Closed risk")
    dismissed_risk = _catalog(db_session, "Dismissed risk")
    on_closed_project = _catalog(db_session, "Risk on a closed project")

    # Active project: Open is included; Resolved/Closed/Dismissed are excluded.
    _instance(db_session, active, open_risk, "Open")
    _instance(db_session, active, resolved_risk, "Resolved")
    _instance(db_session, active, closed_risk, "Closed")
    _instance(db_session, active, dismissed_risk, "Dismissed")
    # Closed project: even an Open risk is excluded.
    _instance(db_session, closed_project, on_closed_project, "Open")
    db_session.commit()

    resp = client.get("/api/active-register")
    assert resp.status_code == 200
    rows = resp.json()

    assert [r["description"] for r in rows] == ["Open risk"]

    row = rows[0]
    assert row["status"] == "Open"
    assert row["project_id"] == active.id
    assert row["project_code"] == "PRJ-ACTIVE"
    assert row["project_name"] == "P PRJ-ACTIVE"
    assert row["department_name"] == "D-PRJ-ACTIVE"
    assert row["project_type_name"] == "T-PRJ-ACTIVE"
    assert row["name"] is None  # catalog short name not yet assigned


def test_active_register_includes_short_name(client: TestClient, db_session: Session) -> None:
    project = _project(db_session, "PRJ-1")
    catalog = models.RiskCatalog(
        name="Vendor onboarding", description="Vendor onboarding overdue"
    )
    db_session.add(catalog)
    db_session.flush()
    _instance(db_session, project, catalog, "Open")
    db_session.commit()

    resp = client.get("/api/active-register")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Vendor onboarding"
    assert rows[0]["description"] == "Vendor onboarding overdue"


def test_active_register_empty_when_no_active_risks(
    client: TestClient, db_session: Session
) -> None:
    project = _project(db_session, "PRJ-1")
    catalog = _catalog(db_session, "Resolved risk")
    _instance(db_session, project, catalog, "Resolved")
    db_session.commit()

    resp = client.get("/api/active-register")
    assert resp.status_code == 200
    assert resp.json() == []
