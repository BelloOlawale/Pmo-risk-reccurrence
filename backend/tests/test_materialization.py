"""Tests for risk materialization: Risk End Date -> Event -> Issue.

Covers the services helper (one Issue per Event risk, field inheritance) and the
scheduler end-date monitor (overdue detection, exclusions, idempotency, audit,
notifications), including the five lifecycle scenarios from the spec.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.status import RiskStatus
from riskapp.notifications import NotificationService
from riskapp.scheduler import (
    find_event_risks_without_issue,
    find_overdue_risks,
    run_end_date_monitor,
)
from riskapp.services import ensure_issue_for_risk

TODAY = dt.date(2026, 8, 24)
PAST = dt.date(2026, 8, 20)


def _risk(
    db: Session,
    *,
    code: str,
    status: str = "Open",
    end_date: dt.date | None = PAST,
    acknowledged: bool = False,
    owner: models.User | None = None,
    description: str = "Unavailability of key project stakeholders",
    category: str | None = "Project Management",
    risk_source: str | None = "Human",
    response_strategy: str | None = "Mitigate",
    response_plan: str | None = "Assign a named deputy to each decision forum.",
    identified_during: str | None = "Execution",
    likelihood: str = "High",
    impact: str = "High",
) -> models.Risk:
    dept = models.Department(name=f"D-{code}")
    ptype = models.ProjectType(name=f"T-{code}")
    db.add_all([dept, ptype])
    db.flush()

    if owner is None:
        owner = models.User(upn=f"{code}-owner@example.com", display_name=f"{code} owner")
    pm = models.User(upn=f"{code}-pm@example.com", display_name=f"{code} pm")
    db.add_all([owner, pm])
    db.flush()

    project = models.Project(
        name=f"P-{code}",
        project_code=f"PRJ-{code}",
        status="Active",
        pm_user_id=pm.id,
    )
    db.add(project)
    project.department = dept
    project.project_type = ptype
    db.flush()

    risk = models.Risk(
        project_id=project.id,
        risk_code=code,
        description=description,
        category=category,
        risk_source=risk_source,
        likelihood=likelihood,
        impact=impact,
        risk_rating="High",
        response_strategy=response_strategy,
        response_plan=response_plan,
        identified_during=identified_during,
        owner_user_id=owner.id,
        status=status,
        sla_acknowledged=acknowledged,
        risk_start_date=dt.date(2026, 8, 18),
        risk_end_date=end_date,
    )
    db.add(risk)
    db.commit()
    return risk


def _issues(db: Session) -> list[models.Issue]:
    return list(db.scalars(select(models.Issue).order_by(models.Issue.id)).all())


class TestFindOverdueRisks:
    def test_overdue_open_risk_is_found(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-OVERDUE")
        assert [r.id for r in find_overdue_risks(db_session, TODAY)] == [risk.id]

    def test_not_overdue_when_end_date_is_today(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-TODAY", end_date=TODAY)
        assert find_overdue_risks(db_session, TODAY) == []

    def test_not_overdue_when_end_date_is_future(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-FUTURE", end_date=TODAY + dt.timedelta(days=5))
        assert find_overdue_risks(db_session, TODAY) == []

    def test_resolved_and_closed_are_excluded(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-RESOLVED", status="Resolved")
        _risk(db_session, code="RSK-CLOSED", status="Closed")
        assert find_overdue_risks(db_session, TODAY) == []

    def test_suggested_and_dismissed_are_excluded(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-SUG", status="Suggested")
        _risk(db_session, code="RSK-DISMISSED", status="Dismissed")
        assert find_overdue_risks(db_session, TODAY) == []

    def test_event_is_not_rechecked(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-EVENT", status="Event")
        assert find_overdue_risks(db_session, TODAY) == []

    def test_missing_end_date_is_excluded(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-NOEND", end_date=None)
        assert find_overdue_risks(db_session, TODAY) == []

    def test_in_progress_and_escalated_are_materializable(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-IP", status="In Progress")
        _risk(db_session, code="RSK-ESC", status="Escalated")
        assert {r.risk_code for r in find_overdue_risks(db_session, TODAY)} == {
            "RSK-IP",
            "RSK-ESC",
        }


class TestEnsureIssueForRisk:
    def test_issue_inherits_risk_fields(self, db_session: Session) -> None:
        risk = _risk(
            db_session,
            code="RSK-INHERIT",
            category="Technical",
            risk_source="Technical",
            response_strategy="Transfer",
            response_plan="Hand to vendor support.",
            identified_during="Planning",
        )
        risk.status = RiskStatus.EVENT.value
        db_session.commit()

        issue = ensure_issue_for_risk(db_session, risk)

        assert issue.issue_code == "ISS-001"
        assert issue.project_id == risk.project_id
        assert issue.source_risk_id == risk.id
        assert issue.description == risk.description
        assert issue.category == "Technical"
        assert issue.risk_source == "Technical"
        assert issue.likelihood == risk.likelihood
        assert issue.impact == risk.impact
        assert issue.risk_rating == "High"
        assert issue.response_strategy == "Transfer"
        assert issue.response_plan == risk.response_plan
        assert issue.identified_during == "Planning"
        assert issue.owner_user_id == risk.owner_user_id
        assert issue.risk_start_date == risk.risk_start_date
        assert issue.risk_end_date == risk.risk_end_date
        assert issue.status == "Open"

        # The originating risk is never deleted.
        db_session.refresh(risk)
        assert risk.status == RiskStatus.EVENT.value

    def test_issue_creation_is_audited_on_the_risk(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-AUDIT")
        risk.status = RiskStatus.EVENT.value
        db_session.commit()

        issue = ensure_issue_for_risk(db_session, risk)

        entry = db_session.scalar(
            select(models.RiskAuditLog).where(
                models.RiskAuditLog.risk_id == risk.id,
                models.RiskAuditLog.action == "issue_created",
            )
        )
        assert entry is not None
        assert entry.field == "issue_code"
        assert entry.new_value == issue.issue_code

    def test_non_event_risk_is_rejected(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-OPEN")
        with pytest.raises(ValueError, match="Event"):
            ensure_issue_for_risk(db_session, risk)

    def test_second_call_is_idempotent(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-ONCE")
        risk.status = RiskStatus.EVENT.value
        db_session.commit()

        first = ensure_issue_for_risk(db_session, risk)
        second = ensure_issue_for_risk(db_session, risk)

        assert first.id == second.id
        assert len(_issues(db_session)) == 1

    def test_codes_are_unique_across_risks(self, db_session: Session) -> None:
        risk_a = _risk(db_session, code="RSK-A")
        risk_a.status = RiskStatus.EVENT.value
        risk_b = _risk(db_session, code="RSK-B")
        risk_b.status = RiskStatus.EVENT.value
        db_session.commit()

        issue_a = ensure_issue_for_risk(db_session, risk_a)
        issue_b = ensure_issue_for_risk(db_session, risk_b)

        assert {issue_a.issue_code, issue_b.issue_code} == {"ISS-001", "ISS-002"}


class TestRunEndDateMonitor:
    def test_scenario2_acknowledged_but_unresolved_materializes(
        self, db_session: Session
    ) -> None:
        """Acknowledged risk, SLA satisfied, owner never resolves -> Event + Issue."""
        risk = _risk(db_session, code="RSK-MAT", acknowledged=True)
        db_session.refresh(risk)

        count = run_end_date_monitor(db_session, NotificationService(), TODAY)

        assert count == 1
        db_session.refresh(risk)
        assert risk.status == RiskStatus.EVENT.value
        issues = _issues(db_session)
        assert len(issues) == 1
        assert issues[0].source_risk_id == risk.id

    def test_scenario1_acknowledged_and_resolved_does_not_materialize(
        self, db_session: Session
    ) -> None:
        _risk(db_session, code="RSK-RES", acknowledged=True, status="Resolved")
        count = run_end_date_monitor(db_session, NotificationService(), TODAY)
        assert count == 0
        assert _issues(db_session) == []

    def test_scenario3_resolved_does_not_materialize(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-RES2", status="Resolved")
        assert run_end_date_monitor(db_session, NotificationService(), TODAY) == 0
        assert _issues(db_session) == []

    def test_scenario4_closed_does_not_materialize(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-CLS", status="Closed")
        assert run_end_date_monitor(db_session, NotificationService(), TODAY) == 0
        assert _issues(db_session) == []

    def test_scenario5_second_run_creates_no_duplicate_issue(
        self, db_session: Session
    ) -> None:
        risk = _risk(db_session, code="RSK-TWICE")
        db_session.refresh(risk)

        first = run_end_date_monitor(db_session, NotificationService(), TODAY)
        second = run_end_date_monitor(db_session, NotificationService(), TODAY)

        assert first == 1
        assert second == 0
        assert len(_issues(db_session)) == 1
        db_session.refresh(risk)
        assert risk.status == RiskStatus.EVENT.value

    def test_end_date_not_reached_does_not_materialize(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-SOON", end_date=TODAY + dt.timedelta(days=1))
        assert run_end_date_monitor(db_session, NotificationService(), TODAY) == 0
        assert _issues(db_session) == []

    def test_original_risk_is_retained_with_issue_relationship(
        self, db_session: Session
    ) -> None:
        risk = _risk(db_session, code="RSK-RETAIN")
        run_end_date_monitor(db_session, NotificationService(), TODAY)

        still_there = db_session.get(models.Risk, risk.id)
        assert still_there is not None
        assert still_there.status == RiskStatus.EVENT.value
        assert still_there.issue is not None
        assert still_there.issue.source_risk_id == risk.id

    def test_escalated_overdue_risk_materializes(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-ESC", status="Escalated")
        count = run_end_date_monitor(db_session, NotificationService(), TODAY)
        assert count == 1
        assert len(_issues(db_session)) == 1

    def test_event_risk_without_issue_is_backfilled_once(self, db_session: Session) -> None:
        # A risk manually moved to Event before this workflow existed.
        risk = _risk(db_session, code="RSK-BACKFILL", status="Event")
        assert find_event_risks_without_issue(db_session) == [risk]

        run_end_date_monitor(db_session, NotificationService(), TODAY)
        assert len(_issues(db_session)) == 1

        run_end_date_monitor(db_session, NotificationService(), TODAY)
        assert len(_issues(db_session)) == 1  # no duplicate

    def test_audit_trail_records_transition_and_issue(
        self, db_session: Session
    ) -> None:
        risk = _risk(db_session, code="RSK-HIST")
        db_session.refresh(risk)

        run_end_date_monitor(db_session, NotificationService(), TODAY)

        actions = list(
            db_session.scalars(
                select(models.RiskAuditLog.action)
                .where(models.RiskAuditLog.risk_id == risk.id)
                .order_by(models.RiskAuditLog.id)
            ).all()
        )
        assert "status_change" in actions  # Open -> Event
        assert "issue_created" in actions

    def test_materialization_notifies_owner_and_pm(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-NOTIFY")
        db_session.refresh(risk)

        run_end_date_monitor(db_session, NotificationService(), TODAY)

        notifications = db_session.scalars(
            select(models.Notification).where(models.Notification.type == "materialized")
        ).all()
        assert len(notifications) == 2
        assert {n.recipient_user_id for n in notifications} == {
            risk.owner_user_id,
            risk.project.pm_user_id,
        }
        issue = _issues(db_session)[0]
        assert any(issue.issue_code in n.body for n in notifications)

    def test_issue_population_end_to_end(self, db_session: Session) -> None:
        """The Issue carries the source risk's identity and rating information."""
        risk = _risk(
            db_session,
            code="RSK-POP",
            acknowledged=True,
            category="Project Management",
            risk_source="Human",
            response_strategy="Mitigate",
            response_plan="Maintain a named deputy for every decision forum.",
            identified_during="Execution",
        )
        db_session.refresh(risk)

        run_end_date_monitor(db_session, NotificationService(), TODAY)

        issue = _issues(db_session)[0]
        assert issue.issue_code == "ISS-001"
        assert issue.source_risk_id == risk.id
        assert issue.description == risk.description
        assert issue.risk_rating == risk.risk_rating
        assert issue.likelihood == risk.likelihood
        assert issue.impact == risk.impact
        assert issue.risk_end_date == risk.risk_end_date
        assert issue.project_id == risk.project_id

    def test_materialized_risk_is_not_closed(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-NOCLOSE")
        run_end_date_monitor(db_session, NotificationService(), TODAY)
        db_session.refresh(risk)
        assert risk.status == RiskStatus.EVENT.value
        assert risk.status != RiskStatus.CLOSED.value


def test_no_issues_are_ever_created_for_resolved_risks(db_session: Session) -> None:
    """Regression: resolution before the end date must never produce an Issue."""
    _risk(db_session, code="RSK-EARLY", status="Resolved", end_date=PAST)
    _risk(db_session, code="RSK-CLOSED", status="Closed", end_date=PAST)
    count = db_session.scalar(select(func.count()).select_from(models.Issue)) or 0
    assert count == 0
