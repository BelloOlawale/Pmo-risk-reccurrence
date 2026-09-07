"""Tests for the deterministic suggestion lifecycle (list / accept / dismiss)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
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
    project: models.Project,
    description: str,
    category: str | None = None,
    source_file: str = "register.xlsx",
) -> models.ProjectRisk:
    catalog = models.RiskCatalog(description=description, category=category)
    db.add(catalog)
    db.flush()
    risk = models.ProjectRisk(
        project_id=project.id,
        risk_id=catalog.id,
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
        risk = _historical_risk(
            db_session, project=historical, description="Data migration delay"
        )

        suggestions = list_suggestions(db_session, target)
        assert any(s.risk_id == str(risk.id) for s in suggestions)

    def test_keyword_match_included(self, db_session: Session) -> None:
        historical, target = _make_projects(
            db_session, department="Digital Advisory", project_type="Cloud Migration"
        )
        risk = _historical_risk(
            db_session,
            project=historical,
            description="Cloud migration data loss during cutover",
        )

        suggestions = list_suggestions(db_session, target)
        assert any(s.risk_id == str(risk.id) for s in suggestions)

    def test_suggestions_carry_rating_and_category(self, db_session: Session) -> None:
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        _historical_risk(
            db_session,
            project=historical,
            description="Vendor delay",
            category="Technical",
        )

        suggestion = list_suggestions(db_session, target)[0]
        assert suggestion.risk_rating == "High"
        assert suggestion.category == "Technical"


class TestAcceptSuggestion:
    def test_accept_creates_open_risk_and_excludes_candidate(
        self, db_session: Session
    ) -> None:
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        risk = _historical_risk(
            db_session, project=historical, description="Data migration delay"
        )

        accepted = accept_suggestion(db_session, target, str(risk.id))

        assert accepted.status == RiskStatus.OPEN.value
        assert accepted.project_id == target.id
        assert accepted.source == "Historical"
        assert accepted.catalog_risk.description == "Data migration delay"

        # The accepted candidate should no longer be suggested.
        remaining = [s.risk_id for s in list_suggestions(db_session, target)]
        assert str(risk.id) not in remaining

    def test_accept_unknown_risk_raises(self, db_session: Session) -> None:
        _, target = _make_projects(db_session, department="SAP", project_type="ERP")
        with pytest.raises(ValueError):
            accept_suggestion(db_session, target, "99999")

    def test_accept_creates_project_risk_linked_to_catalog(
        self, db_session: Session
    ) -> None:
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        risk = _historical_risk(
            db_session, project=historical, description="Data migration delay"
        )

        accept_suggestion(db_session, target, str(risk.id))

        instances = db_session.scalars(select(models.ProjectRisk)).all()
        # One historical instance + the newly accepted one on the target.
        assert len(instances) == 2
        new_instance = next(i for i in instances if i.project_id == target.id)
        catalog = db_session.get(models.RiskCatalog, new_instance.risk_id)
        assert catalog is not None
        assert catalog.description == "Data migration delay"

    def test_accept_reuses_catalog_entry(self, db_session: Session) -> None:
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        # Two historical risks share one deduplicated catalog entry (as the
        # importer produces), so accepting both reuses it.
        catalog = models.RiskCatalog(description="Vendor delay")
        db_session.add(catalog)
        db_session.flush()

        def instance(source_risk_id: str) -> models.ProjectRisk:
            risk = models.ProjectRisk(
                project_id=historical.id,
                risk_id=catalog.id,
                likelihood="Medium",
                impact="High",
                risk_rating="High",
                status="Closed",
                source="Historical",
                source_file_name="register.xlsx",
                source_risk_id=source_risk_id,
            )
            db_session.add(risk)
            db_session.flush()
            return risk

        r1 = instance("1")
        r2 = instance("2")

        accept_suggestion(db_session, target, str(r1.id))
        accept_suggestion(db_session, target, str(r2.id))

        catalogs = db_session.scalars(select(models.RiskCatalog)).all()
        assert len(catalogs) == 1

        instances = db_session.scalars(select(models.ProjectRisk)).all()
        assert len(instances) == 4  # 2 historical + 2 accepted
        accepted = [i for i in instances if i.project_id == target.id]
        assert {i.risk_id for i in accepted} == {catalogs[0].id}


class TestDismissSuggestion:
    def test_dismiss_excludes_candidate(self, db_session: Session) -> None:
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        risk = _historical_risk(
            db_session, project=historical, description="Data migration delay"
        )

        dismiss_suggestion(db_session, target, str(risk.id), reason="not applicable")

        remaining = [s.risk_id for s in list_suggestions(db_session, target)]
        assert str(risk.id) not in remaining

    def test_dismiss_unknown_risk_raises(self, db_session: Session) -> None:
        _, target = _make_projects(db_session, department="SAP", project_type="ERP")
        with pytest.raises(ValueError):
            dismiss_suggestion(db_session, target, "99999")
