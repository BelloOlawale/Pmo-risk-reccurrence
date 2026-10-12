"""Tests for the scheduler logic: daily reminders, escalations, weekly summary.

The monitoring cadence is day-based:

- Daily acknowledgement reminders from the Risk Start Date up to (and including)
  three days before the Risk End Date, stopping once acknowledged.
- An unacknowledged risk escalates two days before the Risk End Date, emailing
  the Risk Owner and the Project Manager. Escalation never creates an Issue.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.status import RiskStatus
from riskapp.notifications import NotificationService
from riskapp.scheduler import (
    find_daily_reminder_risks,
    find_escalation_risks,
    run_daily_reminders,
    run_escalation_monitor,
    run_weekly_summary,
    weekly_summary_data,
)

TODAY = dt.date(2026, 8, 23)


def _risk(
    db: Session,
    *,
    code: str,
    status: str = "Open",
    acknowledged: bool = False,
    owner: models.User | None = None,
    start_date: dt.date | None = dt.date(2026, 8, 18),
    end_date: dt.date | None = dt.date(2026, 8, 30),
    last_reminder_on: dt.date | None = None,
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
        description=f"risk {code}",
        likelihood="High",
        impact="High",
        risk_rating="High",
        status=status,
        sla_acknowledged=acknowledged,
        owner_user_id=owner.id,
        risk_start_date=start_date,
        risk_end_date=end_date,
        last_reminder_on=last_reminder_on,
    )
    db.add(risk)
    db.commit()
    return risk


class TestFindDailyReminderRisks:
    def test_reminder_due_within_window(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-REM")
        assert find_daily_reminder_risks(db_session, TODAY) == [risk]

    def test_no_reminder_after_three_days_before_end(self, db_session: Session) -> None:
        # end - 3 = 2026-08-25; on 08-26 the reminder window has closed.
        _risk(db_session, code="RSK-LATE", end_date=dt.date(2026, 8, 28))
        assert find_daily_reminder_risks(db_session, dt.date(2026, 8, 26)) == []

    def test_no_reminder_before_start_date(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-EARLY", start_date=dt.date(2026, 8, 24))
        assert find_daily_reminder_risks(db_session, TODAY) == []

    def test_acknowledged_risk_is_not_reminded(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-ACK", acknowledged=True)
        assert find_daily_reminder_risks(db_session, TODAY) == []

    def test_already_reminded_today_is_skipped(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-DONE", last_reminder_on=TODAY)
        assert find_daily_reminder_risks(db_session, TODAY) == []

    def test_risk_without_owner_is_skipped(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-NOOWNER")
        risk.owner_user_id = None
        db_session.commit()
        assert find_daily_reminder_risks(db_session, TODAY) == []

    def test_risk_without_dates_is_skipped(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-NODATES", start_date=None, end_date=None)
        assert find_daily_reminder_risks(db_session, TODAY) == []


class TestRunDailyReminders:
    def test_sends_owner_reminder_and_stamps_the_day(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-SEND")
        count = run_daily_reminders(db_session, NotificationService(), TODAY)
        assert count == 1

        db_session.refresh(risk)
        assert risk.last_reminder_on == TODAY
        notifications = db_session.scalars(select(models.Notification)).all()
        assert len(notifications) == 1
        assert notifications[0].type == "owner_reminder"
        assert notifications[0].recipient_user_id == risk.owner_user_id

    def test_second_run_same_day_is_idempotent(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-ONCE")
        first = run_daily_reminders(db_session, NotificationService(), TODAY)
        second = run_daily_reminders(db_session, NotificationService(), TODAY)
        assert first == 1
        assert second == 0


class TestFindEscalationRisks:
    def test_due_two_days_before_end(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-ESC", end_date=dt.date(2026, 8, 25))
        assert find_escalation_risks(db_session, TODAY) == [risk]

    def test_not_due_before_two_days(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-WAIT", end_date=dt.date(2026, 8, 27))
        assert find_escalation_risks(db_session, TODAY) == []

    def test_acknowledged_risk_is_not_escalated(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-ESCACK", acknowledged=True, end_date=dt.date(2026, 8, 24))
        assert find_escalation_risks(db_session, TODAY) == []


class TestRunEscalationMonitor:
    def test_escalates_and_notifies_owner_and_pm(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-ESC2", end_date=dt.date(2026, 8, 25))
        count = run_escalation_monitor(db_session, NotificationService(), TODAY)
        assert count == 1

        db_session.refresh(risk)
        assert risk.status == RiskStatus.ESCALATED.value

        notifications = db_session.scalars(
            select(models.Notification).where(models.Notification.type == "escalation")
        ).all()
        assert {n.recipient_user_id for n in notifications} == {
            risk.owner_user_id,
            risk.project.pm_user_id,
        }

    def test_escalation_does_not_create_an_issue(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-ESC3", end_date=dt.date(2026, 8, 25))
        run_escalation_monitor(db_session, NotificationService(), TODAY)
        assert db_session.scalars(select(models.Issue)).all() == []

    def test_escalation_is_idempotent(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-ESC4", end_date=dt.date(2026, 8, 25))
        first = run_escalation_monitor(db_session, NotificationService(), TODAY)
        second = run_escalation_monitor(db_session, NotificationService(), TODAY)
        assert first == 1
        assert second == 0


class TestWeeklySummary:
    def test_summary_counts(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-1", status="Closed")
        _risk(db_session, code="RSK-2", status="Escalated")
        _risk(db_session, code="RSK-3", status="Open")

        summary = weekly_summary_data(db_session)
        assert summary["total"] == 3
        assert summary["closed"] == 1
        assert summary["escalated"] == 1
        assert summary["resolution_rate"] == pytest.approx(1 / 3)

    def test_run_weekly_summary_notifies(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-1", status="Closed")
        summary = run_weekly_summary(db_session, NotificationService())
        assert summary["total"] == 1
        notifications = db_session.scalars(select(models.Notification)).all()
        assert notifications[0].type == "weekly_summary"
