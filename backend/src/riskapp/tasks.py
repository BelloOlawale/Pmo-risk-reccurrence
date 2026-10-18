"""Celery task wrappers for the scheduler.

Each task is a thin shell: open a DB session, delegate to the testable logic in
:mod:`riskapp.scheduler`, and close the session. This keeps the worker code
trivial while the decision logic stays fully unit-tested without a broker.
"""

from __future__ import annotations

import datetime as dt

from riskapp.celery_app import celery_app
from riskapp.config import settings
from riskapp.db import SessionLocal
from riskapp.notifications import build_notification_service
from riskapp.scheduler import (
    run_daily_reminders,
    run_end_date_monitor,
    run_escalation_monitor,
    run_start_date_activation,
    run_weekly_summary,
)


def _today() -> dt.date:
    """Today in the configured business timezone."""
    return dt.datetime.now(settings.tz).date()


@celery_app.task(name="riskapp.tasks.activate_risks_on_start_date")  # type: ignore[untyped-decorator]
def activate_risks_on_start_date() -> int:
    """Daily: move Open risks to In Progress once their start date arrives."""
    with SessionLocal() as db:
        return run_start_date_activation(db, build_notification_service(), _today())


@celery_app.task(name="riskapp.tasks.send_daily_reminders")  # type: ignore[untyped-decorator]
def send_daily_reminders() -> int:
    """Daily: email Risk Owners whose risks await acknowledgement."""
    with SessionLocal() as db:
        return run_daily_reminders(db, build_notification_service(), _today())


@celery_app.task(name="riskapp.tasks.escalate_unacknowledged_risks")  # type: ignore[untyped-decorator]
def escalate_unacknowledged_risks() -> int:
    """Daily: escalate risks unacknowledged two days before their end date."""
    with SessionLocal() as db:
        return run_escalation_monitor(db, build_notification_service(), _today())


@celery_app.task(name="riskapp.tasks.materialize_overdue_risks")  # type: ignore[untyped-decorator]
def materialize_overdue_risks() -> int:
    """Daily: materialize unresolved risks past their Risk End Date.

    Overdue unresolved risks become Event ("Materialized") and each generates
    exactly one Issue, populated from the originating risk.
    """
    with SessionLocal() as db:
        return run_end_date_monitor(db, build_notification_service(), _today())


@celery_app.task(name="riskapp.tasks.weekly_summary")  # type: ignore[untyped-decorator]
def weekly_summary() -> dict[str, int | float]:
    """Monday 8 AM: aggregate the portfolio and email PMs + PMO Lead."""
    with SessionLocal() as db:
        return run_weekly_summary(db, build_notification_service())
