"""Tests for explicit project reopen and its guardrails."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
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


def test_reopen_returns_project_to_active(client: TestClient, db_session: Session) -> None:
    project = _project(db_session, "PRJ-1", status="Closed")
    db_session.commit()

    resp = client.post(f"/api/projects/{project.id}/reopen")
    assert resp.status_code == 200
    assert resp.json()["status"] == "Active"
    assert db_session.get(models.Project, project.id).status == "Active"


def test_reopen_missing_project_404(client: TestClient) -> None:
    resp = client.post("/api/projects/99999/reopen")
    assert resp.status_code == 404


def test_add_risk_to_closed_project_is_blocked(
    client: TestClient, db_session: Session
) -> None:
    project = _project(db_session, "PRJ-2", status="Closed")
    db_session.commit()

    resp = client.post(
        "/api/risks",
        json={
            "project_id": project.id,
            "description": "New risk",
            "likelihood": "Low",
            "impact": "Low",
        },
    )
    assert resp.status_code == 409

    # The project stays Closed and no Project Risk was created — adding a risk
    # never auto-reopens a Closed project.
    assert db_session.get(models.Project, project.id).status == "Closed"
    count = db_session.scalar(select(func.count()).select_from(models.ProjectRisk))
    assert count == 0


def test_resolving_all_risks_does_not_auto_close(
    client: TestClient, db_session: Session
) -> None:
    """Resolving risks only changes the risks; the project stays Active."""
    project = _project(db_session, "PRJ-3", status="Active")
    catalog = models.RiskCatalog(description="Vendor delay")
    db_session.add(catalog)
    db_session.flush()
    instance = models.ProjectRisk(
        project_id=project.id,
        risk_id=catalog.id,
        likelihood="Low",
        impact="Low",
        risk_rating="Low",
        status="Open",
    )
    db_session.add(instance)
    db_session.commit()

    # Simulate resolving the risk (the lifecycle lives on the Project Risk).
    instance.status = "Resolved"
    db_session.commit()

    assert db_session.get(models.Project, project.id).status == "Active"
