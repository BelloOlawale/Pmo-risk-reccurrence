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
    count: int = 2,
) -> tuple[models.Project, ...]:
    """Create a historical project and one or more target projects sharing dept + type."""
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

    return tuple(project(f"PRJ-{'H' if i == 0 else 'T'}{i}") for i in range(count))


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

    def test_accept_persists_llm_analysis(self, db_session: Session) -> None:
        """The LLM analysis shown on a suggestion is stored on the accepted risk."""
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        _historical_risk(
            db_session, code="RSK-H1", project=historical, description="Data migration delay"
        )

        accepted = accept_suggestion(
            db_session,
            target,
            "RSK-H1",
            analysis="High cutover risk for the migration window.",
        )

        assert accepted.llm_analysis == "High cutover risk for the migration window."
        # The analysis survives the accept transition (risk is now Open).
        db_session.refresh(accepted)
        assert accepted.llm_analysis == "High cutover risk for the migration window."

    def test_reaccept_same_suggestion_is_idempotent(self, db_session: Session) -> None:
        """Accepting the same suggestion twice must not create a duplicate risk.

        Regression: the risk row used to be committed before the processed
        marker, so a second acceptance persisted a second risk and then failed
        with an IntegrityError (HTTP 500) on the marker's unique constraint.
        """
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        _historical_risk(
            db_session,
            code="RSK-H1",
            project=historical,
            description="Data migration delay",
            source_file="a.xlsx",
        )
        _historical_risk(db_session, project=historical, code="RSK-H2", description="X")

        first = accept_suggestion(db_session, target, "RSK-H1")
        second = accept_suggestion(db_session, target, "RSK-H1")

        assert second.id == first.id
        risks = db_session.scalars(
            select(models.Risk).where(models.Risk.project_id == target.id)
        ).all()
        assert len(risks) == 1
        assert risks[0].description == "Data migration delay"

    def test_accept_after_dismiss_raises(self, db_session: Session) -> None:
        """A suggestion dismissed for a register cannot be resurrected."""
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        _historical_risk(
            db_session, code="RSK-H1", project=historical, description="Data migration delay"
        )

        dismiss_suggestion(db_session, target, "RSK-H1", reason="not applicable")

        with pytest.raises(ValueError, match="already been processed"):
            accept_suggestion(db_session, target, "RSK-H1")
        risks = db_session.scalars(
            select(models.Risk).where(models.Risk.project_id == target.id)
        ).all()
        assert risks == []

    def test_accepting_then_relisting_excludes_register_own_risk(
        self, db_session: Session
    ) -> None:
        """The just-accepted risk must not be suggested back to its own register.

        Regression: accepted risks keep ``source="Historical"`` and used to be
        retrieved as candidates for the same department/type, so the accepted
        suggestion reappeared under a fresh risk code and could be accepted
        again, duplicating it.
        """
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        _historical_risk(
            db_session, code="RSK-H1", project=historical, description="Data migration delay"
        )

        accept_suggestion(db_session, target, "RSK-H1")

        remaining = [s.risk_id for s in list_suggestions(db_session, target)]
        assert remaining == []

    def test_suggestion_still_reappears_for_other_registers(self, db_session: Session) -> None:
        """Accepted risks stay available as recurrence suggestions for other registers."""
        historical, target_a, target_b = _make_projects(
            db_session, department="SAP", project_type="ERP", count=3
        )
        _historical_risk(
            db_session, code="RSK-H1", project=historical, description="Data migration delay"
        )

        accept_suggestion(db_session, target_a, "RSK-H1")

        # The recurrence candidate (the accepted copy and its historical source
        # share provenance, so merge/dedup collapses them to one suggestion) is
        # still proposed for a second, unrelated register.
        remaining = list_suggestions(db_session, target_b)
        assert len(remaining) == 1
        assert remaining[0].description == "Data migration delay"

    def test_accept_does_not_reuse_risk_code_when_sequence_has_gaps(
        self, db_session: Session
    ) -> None:
        """Accepting a suggestion must not collide with an existing risk code.

        Regression: the dev DB has deleted rows, so the highest code (RSK-308)
        exceeds the risk count (299). Count-based allocation produced a
        duplicate code and the accept endpoint failed with a 500.
        """
        historical, target = _make_projects(db_session, department="SAP", project_type="ERP")
        # RSK-002 is missing, as if that row was deleted — the DB now has a gap.
        _historical_risk(
            db_session, code="RSK-001", project=historical, description="Data migration delay"
        )
        _historical_risk(
            db_session, code="RSK-003", project=historical, description="Vendor lock-in"
        )

        accepted = accept_suggestion(db_session, target, "RSK-001")

        assert accepted.status == RiskStatus.OPEN.value
        # Must be one past the highest existing code, not count+1 (which would
        # return RSK-003 and violate the unique risk_code constraint).
        assert accepted.risk_code == "RSK-004"


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
