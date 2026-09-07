"""Tests for the guarded project close action."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import models


def _project(db: Session, code: str) -> models.Project:
    department = models.Department(name=f"D-{code}")
    project_type = models.ProjectType(name=f"T-{code}")
    db.add_all([department, project_type])
    db.flush()
    project = models.Project(
        name=f"P {code}",
        project_code=code,
        status="Active",
        department_id=department.id,
        project_type_id=project_type.id,
    )
    db.add(project)
    db.flush()
    return project


def _risk(
    db: Session, project: models.Project, description: str, status: str
) -> models.ProjectRisk:
    catalog = models.RiskCatalog(description=description)
    db.add(catalog)
    db.flush()
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


def test_close_blocked_when_open_risks_exist(client: TestClient, db_session: Session) -> None:
    project = _project(db_session, "PRJ-1")
    _risk(db_session, project, "Vendor onboarding overdue", "Open")
    _risk(db_session, project, "Budget variance", "Resolved")
    db_session.commit()

    resp = client.post(f"/api/projects/{project.id}/close")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "Vendor onboarding overdue" in detail

    # The project remains Active.
    assert db_session.get(models.Project, project.id).status == "Active"


def test_close_succeeds_when_all_resolved_or_closed(
    client: TestClient, db_session: Session
) -> None:
    project = _project(db_session, "PRJ-2")
    _risk(db_session, project, "Vendor onboarding overdue", "Resolved")
    _risk(db_session, project, "Budget variance", "Closed")
    db_session.commit()

    resp = client.post(f"/api/projects/{project.id}/close")
    assert resp.status_code == 200
    assert resp.json()["status"] == "Closed"
    assert db_session.get(models.Project, project.id).status == "Closed"


def test_close_empty_project_succeeds(client: TestClient, db_session: Session) -> None:
    project = _project(db_session, "PRJ-3")
    db_session.commit()

    resp = client.post(f"/api/projects/{project.id}/close")
    assert resp.status_code == 200
    assert resp.json()["status"] == "Closed"


def test_close_missing_project_404(client: TestClient) -> None:
    resp = client.post("/api/projects/99999/close")
    assert resp.status_code == 404
