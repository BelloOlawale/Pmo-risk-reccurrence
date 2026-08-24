"""Tests for the scheduler logic: SLA monitor, start dates, weekly summary."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.status import RiskStatus
from riskapp.notifications import NotificationService
from riskapp.scheduler import (
    find_sla_actions,
    run_sla_monitor,
    run_start_date_check,
    run_weekly_summary,
    sla_state,
    weekly_summary_data,
)

NOW = dt.datetime(2026, 8, 23, 12, 0, 0)


class TestSlaState:
    def test_owner_active_satisfied(self) -> None:
        assert sla_state("High", NOW, NOW, owner_active=True) == "satisfied"

    def test_breach_when_deadline_passed(self) -> None:
        assert (
            sla_state("High", NOW - dt.timedelta(minutes=1), NOW, owner_active=False)
            == "breach"
        )

    def test_warning_within_window(self) -> None:
        deadline = NOW + dt.timedelta(hours=2)  # High warning window is 4h
        assert sla_state("High", deadline, NOW, owner_active=False) == "warning"

    def test_ok_before_warning_window(self) -> None:
        deadline = NOW + dt.timedelta(hours=10)
        assert sla_state("High", deadline, NOW, owner_active=False) == "ok"


def _risk(
    db: Session,
    *,
    code: str,
    status: str = "Open",
    deadline: dt.datetime | None = NOW + dt.timedelta(hours=10),
    acknowledged: bool = False,
    owner: models.User | None = None,
    start_date: dt.date | None = None,
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
        sla_deadline=deadline,
        sla_acknowledged=acknowledged,
        owner_user_id=owner.id,
        risk_start_date=start_date,
    )
    db.add(risk)
    db.commit()
    return risk


class TestFindSlaActions:
    def test_breach_and_warning_detected(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-B", deadline=NOW - dt.timedelta(hours=1))
        _risk(db_session, code="RSK-W", deadline=NOW + dt.timedelta(hours=1))
        _risk(db_session, code="RSK-OK", deadline=NOW + dt.timedelta(hours=10))

        actions = find_sla_actions(db_session, NOW)
        by_code = {a.risk_code: a.action for a in actions}
        assert by_code == {"RSK-B": "breach", "RSK-W": "warning"}

    def test_acknowledged_risk_skipped(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-ACK", acknowledged=True, deadline=NOW - dt.timedelta(hours=1))
        assert find_sla_actions(db_session, NOW) == []

    def test_no_deadline_skipped(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-NODL", deadline=None)
        assert find_sla_actions(db_session, NOW) == []

    def test_owner_activity_satisfies_sla(self, db_session: Session) -> None:
        owner = models.User(upn="o@example.com", display_name="O")
        db_session.add(owner)
        db_session.flush()
        risk = _risk(
            db_session,
            code="RSK-EDIT",
            owner=owner,
            deadline=NOW - dt.timedelta(hours=1),
        )
        db_session.add(
            models.RiskAuditLog(
                risk_id=risk.id, user_id=owner.id, action="field_edit", field="description"
            )
        )
        db_session.commit()
        assert find_sla_actions(db_session, NOW) == []


class TestRunSlaMonitor:
    def test_breach_escalates_and_notifies(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-ESC", deadline=NOW - dt.timedelta(hours=1))
        count = run_sla_monitor(db_session, NotificationService(), NOW)
        assert count == 1

        db_session.refresh(risk)
        assert risk.status == RiskStatus.ESCALATED.value

        notifications = db_session.scalars(select(models.Notification)).all()
        # Breach → owner + PM (PMO Lead is email-only).
        assert len(notifications) == 2
        assert {n.recipient_user_id for n in notifications} == {
            risk.owner_user_id,
            risk.project.pm_user_id,
        }
        assert all(n.type == "breach" for n in notifications)

    def test_warning_notifies_without_escalating(self, db_session: Session) -> None:
        risk = _risk(db_session, code="RSK-WARN", deadline=NOW + dt.timedelta(hours=1))
        run_sla_monitor(db_session, NotificationService(), NOW)

        db_session.refresh(risk)
        assert risk.status == "Open"
        notifications = db_session.scalars(select(models.Notification)).all()
        assert len(notifications) == 1
        assert notifications[0].type == "sla_warning"


class TestStartDateCheck:
    def test_notifies_owner_for_risks_starting_today(self, db_session: Session) -> None:
        _risk(db_session, code="RSK-START", start_date=dt.date(2026, 8, 23))
        count = run_start_date_check(
            db_session, NotificationService(), dt.date(2026, 8, 23)
        )
        assert count == 1
        notifications = db_session.scalars(select(models.Notification)).all()
        assert notifications[0].type == "risk_start"


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
