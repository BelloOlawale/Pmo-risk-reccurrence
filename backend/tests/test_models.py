"""ORM model round-trip tests."""

from __future__ import annotations

from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.scoring import compute_risk_rating


def test_entity_round_trip(db_session: Session) -> None:
    dept = models.Department(name="Digital Advisory")
    ptype = models.ProjectType(name="Cloud Migration")
    db_session.add_all([dept, ptype])
    db_session.flush()

    project = models.Project(
        name="NHIA Cloud Migration",
        project_code="PRJ-2026-001",
        customer="NHIA",
        status="Active",
    )
    project.department = dept
    project.project_type = ptype
    db_session.add(project)
    db_session.flush()

    risk = models.Risk(
        project_id=project.id,
        risk_code="RSK-001",
        description="Delay in AWS account provisioning",
        likelihood="High",
        impact="Medium",
        risk_rating=compute_risk_rating("High", "Medium"),
        status="Suggested",
    )
    db_session.add(risk)
    db_session.flush()

    assert risk.risk_rating == "High"
    assert risk.project is project
    assert project.department_name == "Digital Advisory"
    assert project.project_type_name == "Cloud Migration"
    assert len(project.risks) == 1


def test_audit_log_round_trip(db_session: Session) -> None:
    dept = models.Department(name="D")
    ptype = models.ProjectType(name="T")
    db_session.add_all([dept, ptype])
    db_session.flush()

    project = models.Project(name="P", project_code="PRJ-1", status="Active")
    project.department = dept
    project.project_type = ptype
    db_session.add(project)
    db_session.flush()

    risk = models.Risk(
        project_id=project.id,
        risk_code="RSK-1",
        description="r",
        likelihood="Low",
        impact="Low",
        risk_rating="Low",
        status="Open",
    )
    db_session.add(risk)
    db_session.flush()

    entry = models.RiskAuditLog(
        risk_id=risk.id,
        action="status_change",
        field="status",
        old_value="Suggested",
        new_value="Open",
    )
    db_session.add(entry)
    db_session.flush()

    assert risk.audit_log[0].action == "status_change"
    assert entry.risk is risk
