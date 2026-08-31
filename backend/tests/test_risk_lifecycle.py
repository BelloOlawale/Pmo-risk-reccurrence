"""Tests for the suggestion lifecycle: accept, dismiss, and quick add."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models, schemas
from riskapp.domain.status import RiskStatus
from riskapp.services import (
    accept_risk,
    create_project,
    create_risk,
    dismiss_risk,
)


def _seed_project(
    db: Session, *, code: str = "PRJ-1", pm_user_id: int | None = None
) -> models.Project:
    payload = schemas.ProjectCreate(
        name=f"Project {code}",
        department="Digital Advisory",
        project_type="Cloud Migration",
    )
    project = create_project(db, payload)
    if pm_user_id is not None:
        project.pm_user_id = pm_user_id
        db.commit()
    return project


def _suggested_risk(db: Session, project: models.Project) -> models.Risk:
    return create_risk(
        db,
        schemas.RiskCreate(
            project_id=project.id,
            description="Data loss during cutover",
            likelihood="High",
            impact="High",
        ),
    )


class TestAccept:
    def test_accept_transitions_to_open_and_assigns_owner(self, db_session: Session) -> None:
        user = models.User(upn="pm@example.com", display_name="PM")
        db_session.add(user)
        db_session.flush()

        project = _seed_project(db_session, pm_user_id=user.id)
        risk = _suggested_risk(db_session, project)

        accepted = accept_risk(db_session, risk)
        assert accepted.status == RiskStatus.OPEN.value
        assert accepted.owner_user_id == user.id
        assert accepted.accepted_date is not None
        assert accepted.sla_deadline is not None

    def test_accept_requires_suggested_status(self, db_session: Session) -> None:
        project = _seed_project(db_session)
        risk = _suggested_risk(db_session, project)
        accept_risk(db_session, risk)

        import pytest

        from riskapp.domain.status import InvalidTransitionError

        with pytest.raises(InvalidTransitionError):
            accept_risk(db_session, risk)


class TestDismiss:
    def test_dismiss_transitions_and_records_exclusion(self, db_session: Session) -> None:
        project = _seed_project(db_session)
        risk = _suggested_risk(db_session, project)

        dismissed = dismiss_risk(db_session, risk, reason="already handled")
        assert dismissed.status == RiskStatus.DISMISSED.value

        exclusions = db_session.scalars(
            select(models.SuggestionDismissal).where(
                models.SuggestionDismissal.project_id == project.id
            )
        ).all()
        assert len(exclusions) == 1
        assert exclusions[0].historical_risk_key == risk.risk_code

    def test_dismiss_is_per_project(self, db_session: Session) -> None:
        project_a = _seed_project(db_session, code="PRJ-A")
        project_b = _seed_project(db_session, code="PRJ-B")
        risk = _suggested_risk(db_session, project_a)

        dismiss_risk(db_session, risk)

        exclusions_a = db_session.scalars(
            select(models.SuggestionDismissal).where(
                models.SuggestionDismissal.project_id == project_a.id
            )
        ).all()
        exclusions_b = db_session.scalars(
            select(models.SuggestionDismissal).where(
                models.SuggestionDismissal.project_id == project_b.id
            )
        ).all()
        assert len(exclusions_a) == 1
        assert len(exclusions_b) == 0


class TestQuickAdd:
    def test_quick_add_computes_rating_and_sets_kickoff_source(
        self, db_session: Session
    ) -> None:
        project = _seed_project(db_session)
        risk = create_risk(
            db_session,
            schemas.RiskCreate(
                project_id=project.id,
                description="Vendor delay",
                likelihood="Low",
                impact="High",
                source="Kickoff",
            ),
        )
        assert risk.status == RiskStatus.SUGGESTED.value
        assert risk.risk_rating == "Medium"  # Low x High -> Medium
        assert risk.source == "Kickoff"
        assert risk.category is None

    def test_manual_entry_defaults_to_custom_source(self, db_session: Session) -> None:
        project = _seed_project(db_session)
        risk = create_risk(
            db_session,
            schemas.RiskCreate(
                project_id=project.id,
                description="Vendor delay",
                likelihood="Medium",
                impact="Medium",
            ),
        )
        assert risk.source == "Custom"
