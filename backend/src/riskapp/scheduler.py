"""Scheduler logic: SLA monitoring, start-date checks, and weekly summaries.

The pure, testable decision logic lives here; the Celery task wrappers in
:mod:`riskapp.tasks` only open a session and delegate. This keeps the monitor
unit-testable against SQLite with a fake clock, no broker required.

Datetimes follow the app convention: naive UTC.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.sla import as_naive_utc, warning_hours
from riskapp.domain.status import RiskStatus
from riskapp.notifications import (
    EVENT_BREACH,
    EVENT_RISK_START,
    EVENT_SLA_WARNING,
    EVENT_WEEKLY_SUMMARY,
    NotificationService,
    Recipients,
    _unique,
)
from riskapp.services import transition_risk

_ACTIVE_STATUSES = (RiskStatus.OPEN.value, RiskStatus.IN_PROGRESS.value)


def sla_state(
    rating: str, deadline: dt.datetime, now: dt.datetime, *, owner_active: bool
) -> str:
    """Return "satisfied" | "breach" | "warning" | "ok" for a stored deadline.

    Unlike :func:`riskapp.domain.sla.evaluate_sla`, this works directly off the
    stored ``sla_deadline`` so a manual override is respected.
    """
    if owner_active:
        return "satisfied"
    deadline = as_naive_utc(deadline)
    now = as_naive_utc(now)
    if now >= deadline:
        return "breach"
    if now >= deadline - dt.timedelta(hours=warning_hours(rating)):
        return "warning"
    return "ok"


def _owner_active(db: Session, risk: models.ProjectRisk) -> bool:
    """Whether the owner has responded (acknowledged or any audit entry)."""
    if risk.sla_acknowledged:
        return True
    if risk.owner_user_id is None:
        return False
    count = db.scalar(
        select(func.count())
        .select_from(models.RiskAuditLog)
        .where(
            models.RiskAuditLog.risk_id == risk.id,
            models.RiskAuditLog.user_id == risk.owner_user_id,
        )
    )
    return (count or 0) > 0


@dataclass(frozen=True)
class SlaAction:
    risk_id: int
    risk_code: str
    action: str  # "warning" | "breach"


def find_sla_actions(db: Session, now: dt.datetime) -> list[SlaAction]:
    """Return the pending SLA actions for active, non-satisfied risks."""
    risks = db.scalars(
        select(models.ProjectRisk).where(models.ProjectRisk.status.in_(_ACTIVE_STATUSES))
    ).all()

    actions: list[SlaAction] = []
    for risk in risks:
        if risk.sla_deadline is None:
            continue
        state = sla_state(
            risk.risk_rating,
            risk.sla_deadline,
            now,
            owner_active=_owner_active(db, risk),
        )
        if state in ("warning", "breach"):
            actions.append(
                SlaAction(
                    risk_id=risk.id,
                    risk_code=f"#{risk.id}",
                    action=state,
                )
            )
    return actions


def run_sla_monitor(db: Session, notifier: NotificationService, now: dt.datetime) -> int:
    """Apply pending SLA actions: remind on warning, escalate on breach."""
    actions = find_sla_actions(db, now)
    for action in actions:
        risk = db.get(models.ProjectRisk, action.risk_id)
        if risk is None:
            continue
        label = f"#{risk.id}"
        if action.action == "breach":
            transition_risk(db, risk, RiskStatus.ESCALATED.value)
            notifier.notify(
                db,
                event=EVENT_BREACH,
                title=f"SLA breached: {label}",
                body=f"Risk {label} exceeded its SLA deadline and was escalated.",
                risk=risk,
            )
        else:
            notifier.notify(
                db,
                event=EVENT_SLA_WARNING,
                title=f"SLA warning: {label}",
                body=f"Risk {label} is approaching its SLA deadline.",
                risk=risk,
            )
    db.commit()
    return len(actions)


def find_start_date_risks(db: Session, today: dt.date) -> list[models.ProjectRisk]:
    """Risks whose ``risk_start_date`` is ``today`` (in the app timezone)."""
    return list(
        db.scalars(
            select(models.ProjectRisk).where(models.ProjectRisk.risk_start_date == today)
        ).all()
    )


def run_start_date_check(
    db: Session, notifier: NotificationService, today: dt.date
) -> int:
    """Notify the owner for every risk starting today."""
    risks = find_start_date_risks(db, today)
    for risk in risks:
        label = f"#{risk.id}"
        notifier.notify(
            db,
            event=EVENT_RISK_START,
            title=f"Risk starts today: {label}",
            body=f"Risk {label} is now within its active window.",
            risk=risk,
        )
    db.commit()
    return len(risks)


def weekly_summary_data(db: Session) -> dict[str, int | float]:
    """Aggregate portfolio counts for the Monday summary email."""
    total = db.scalar(select(func.count()).select_from(models.ProjectRisk)) or 0
    escalated = (
        db.scalar(
            select(func.count())
            .select_from(models.ProjectRisk)
            .where(models.ProjectRisk.status == RiskStatus.ESCALATED.value)
        )
        or 0
    )
    closed = (
        db.scalar(
            select(func.count())
            .select_from(models.ProjectRisk)
            .where(
                models.ProjectRisk.status.in_(
                    (RiskStatus.CLOSED.value, RiskStatus.RESOLVED.value)
                )
            )
        )
        or 0
    )
    resolution_rate = (closed / total) if total else 0.0
    return {
        "total": total,
        "escalated": escalated,
        "closed": closed,
        "resolution_rate": resolution_rate,
    }


def run_weekly_summary(
    db: Session, notifier: NotificationService
) -> dict[str, int | float]:
    """Send the weekly summary to every PM and the PMO Lead."""
    summary = weekly_summary_data(db)
    body = (
        f"Weekly summary — {summary['total']} risks total, "
        f"{summary['escalated']} escalated, {summary['closed']} closed. "
        f"Resolution rate {summary['resolution_rate']:.0%}."
    )

    pm_users = list(
        db.scalars(
            select(models.User)
            .join(models.Project, models.Project.pm_user_id == models.User.id)
            .distinct()
            .order_by(models.User.id)
        ).all()
    )
    pmo_email = _get_setting(db, "pmo_lead_email")
    recipients = Recipients(
        to_user_ids=tuple(user.id for user in pm_users),
        to_emails=_unique(*[user.upn for user in pm_users], pmo_email),
        cc_emails=(),
    )
    notifier.notify_recipients(
        db,
        event=EVENT_WEEKLY_SUMMARY,
        title="Weekly risk summary",
        body=body,
        recipients=recipients,
    )
    db.commit()
    return summary


def _get_setting(db: Session, key: str) -> str | None:
    value = db.scalar(select(models.Setting.value).where(models.Setting.key == key))
    return value or None
