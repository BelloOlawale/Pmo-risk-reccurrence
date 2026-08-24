"""Tests for the deterministic suggestion lifecycle (list / accept / dismiss)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.status import RiskStatus
from riskapp.suggestions import (
    accept_suggestion,
    dismiss_suggestion,
    list_suggestions,
)


def _make_projects(
    db: Session,
    *,
    department: str,
    project_type: str,
) -> tuple[models.Project, models.Project]:
    """Create a historical project and a target project sharing dept + type."""
    dept = models.Department(name=department)
    db.add(dept)
    db.flush()
    ptype = models.ProjectType(name=project_type)
    db.add(ptype)
    db.flush()

    def project(code: str) -> models.Project:
        p = models.Project(name=f"Project {code}", project_code=code, status="Active")
        p.department = dept
        p.project_type = ptype
        db.add(p)
        db.flush()
        return p

    return project("PRJ-H"), project("PRJ-T")


def _historical_risk(
    db: Session,
    *,
    code: str,
    project: models.Project,
    description: str,
    category: str | None = None,
    source_file: str = "register.xlsx",
) -> models.Risk:
    risk = models.Risk(
        project_id=project.id,
        risk_code=code,
        description=description,
        category=category,
        likelihood="Medium",
        impact="High",
        risk_rating="High",
        status="Closed",
        source="Historical",
        source_file_name=source_file,
        source_risk_id="1",
    )
    db.add(risk)
    db.flush()
    return risk


class TestListSuggestions:
    def test_exact_match_included(self, db_session: Session) -> None:
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        _historical_risk(
            db_session, code="RSK-H1", project=historical, description="Data migration delay"
        )

        suggestions = list_suggestions(db_session, target)
        assert any(s.risk_id == "RSK-H1" for s in suggestions)

    def test_keyword_match_included(self, db_session: Session) -> None:
        historical, target = _make_projects(
            db_session, department="Digital Advisory", project_type="Cloud Migration"
        )
        _historical_risk(
            db_session,
            code="RSK-K1",
            project=historical,
            description="Cloud migration data loss during cutover",
        )

        suggestions = list_suggestions(db_session, target)
        assert any(s.risk_id == "RSK-K1" for s in suggestions)

    def test_suggestions_carry_rating_and_category(self, db_session: Session) -> None:
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        _historical_risk(
            db_session,
            code="RSK-H1",
            project=historical,
            description="Vendor delay",
            category="Technical",
        )

        suggestion = list_suggestions(db_session, target)[0]
        assert suggestion.risk_rating == "High"
        assert suggestion.category == "Technical"


class TestAcceptSuggestion:
    def test_accept_creates_open_risk_and_excludes_candidate(self, db_session: Session) -> None:
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        _historical_risk(
            db_session, code="RSK-H1", project=historical, description="Data migration delay"
        )

        accepted = accept_suggestion(db_session, target, "RSK-H1")

        assert accepted.status == RiskStatus.OPEN.value
        assert accepted.project_id == target.id
        assert accepted.source == "Historical"
        assert accepted.description == "Data migration delay"

        # The accepted candidate should no longer be suggested.
        remaining = [s.risk_id for s in list_suggestions(db_session, target)]
        assert "RSK-H1" not in remaining

    def test_accept_unknown_risk_raises(self, db_session: Session) -> None:
        _, target = _make_projects(db_session, department="SAP", project_type="ERP")
        with pytest.raises(ValueError):
            accept_suggestion(db_session, target, "RSK-NOPE")


class TestDismissSuggestion:
    def test_dismiss_excludes_candidate(self, db_session: Session) -> None:
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        _historical_risk(
            db_session, code="RSK-H1", project=historical, description="Data migration delay"
        )

        dismiss_suggestion(db_session, target, "RSK-H1", reason="not applicable")

        remaining = [s.risk_id for s in list_suggestions(db_session, target)]
        assert "RSK-H1" not in remaining

    def test_dismiss_unknown_risk_raises(self, db_session: Session) -> None:
        _, target = _make_projects(db_session, department="SAP", project_type="ERP")
        with pytest.raises(ValueError):
            dismiss_suggestion(db_session, target, "RSK-NOPE")
