"""Celery application and beat schedule.

The broker is Redis (Azure Cache for Redis in production). The web app, the
worker, and the beat scheduler all import this single Celery instance.
"""

from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]

from riskapp.config import settings

celery_app = Celery(
    "riskapp",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Register the task module so the worker picks up riskapp.tasks on boot.
    include=["riskapp.tasks"],
    beat_schedule={
        "activate-risks-on-start-date": {
            "task": "riskapp.tasks.activate_risks_on_start_date",
            "schedule": crontab(hour=6, minute=5),
        },
        "daily-owner-reminders": {
            "task": "riskapp.tasks.send_daily_reminders",
            "schedule": crontab(hour=6, minute=0),
        },
        "daily-escalations": {
            "task": "riskapp.tasks.escalate_unacknowledged_risks",
            "schedule": crontab(hour=6, minute=15),
        },
        "materialize-overdue-risks-daily": {
            "task": "riskapp.tasks.materialize_overdue_risks",
            "schedule": crontab(hour=6, minute=30),
        },
        "weekly-summary-monday": {
            "task": "riskapp.tasks.weekly_summary",
            "schedule": crontab(day_of_week=0, hour=8, minute=0),
        },
    },
)
