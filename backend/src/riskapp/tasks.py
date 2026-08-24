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
from riskapp.notifications import NotificationService
from riskapp.scheduler import (
    run_sla_monitor,
    run_start_date_check,
    run_weekly_summary,
)


@celery_app.task(name="riskapp.tasks.monitor_sla")  # type: ignore[untyped-decorator]
def monitor_sla() -> int:
    """Hourly SLA monitor: warn approaching deadlines, escalate breaches."""
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    with SessionLocal() as db:
        return run_sla_monitor(db, NotificationService(), now)


@celery_app.task(name="riskapp.tasks.check_start_dates")  # type: ignore[untyped-decorator]
def check_start_dates() -> int:
    """Daily check: notify owners of risks whose active window starts today."""
    today = dt.datetime.now(settings.tz).date()
    with SessionLocal() as db:
        return run_start_date_check(db, NotificationService(), today)


@celery_app.task(name="riskapp.tasks.weekly_summary")  # type: ignore[untyped-decorator]
def weekly_summary() -> dict[str, int | float]:
    """Monday 8 AM: aggregate the portfolio and email PMs + PMO Lead."""
    with SessionLocal() as db:
        return run_weekly_summary(db, NotificationService())
