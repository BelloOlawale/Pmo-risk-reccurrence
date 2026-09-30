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
    EVENT_MATERIALIZED,
    EVENT_RISK_START,
    EVENT_SLA_WARNING,
    EVENT_WEEKLY_SUMMARY,
    NotificationService,
    Recipients,
    _unique,
)
from riskapp.services import ensure_issue_for_risk, transition_risk

_ACTIVE_STATUSES = (RiskStatus.OPEN.value, RiskStatus.IN_PROGRESS.value)

# Statuses from which the end-date monitor may transition a risk to Event.
# Suggested / Resolved / Closed / Dismissed are excluded: Suggested risks have
# not started, and resolved/closed/dismissed risks are finished business.
_MATERIALIZABLE_STATUSES = (
    RiskStatus.OPEN.value,
    RiskStatus.IN_PROGRESS.value,
    RiskStatus.ESCALATED.value,
)


def sla_state(
    rating: str, deadline: dt.datetime, now: dt.datetime, *, owner_active: bool
) -> str:
    """Return "satisfied" | "breach" | "warning" | "ok" for a stored deadline.

    Works directly off the stored ``sla_deadline`` (itself derived from the
    PM-set Risk End Date). The rating only picks the warning window.
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


def _owner_active(db: Session, risk: models.Risk) -> bool:
    """Whether the owner has acknowledged the risk.

    Acknowledgement is the single signal that satisfies the escalation
    requirement. General edits no longer stop the SLA clock: if the owner never
    acknowledges before the deadline, the risk escalates.
    """
    return risk.sla_acknowledged


@dataclass(frozen=True)
class SlaAction:
    risk_id: int
    risk_code: str
    action: str  # "warning" | "breach"


def find_sla_actions(db: Session, now: dt.datetime) -> list[SlaAction]:
    """Return the pending SLA actions for active, non-satisfied risks."""
    risks = db.scalars(
        select(models.Risk).where(models.Risk.status.in_(_ACTIVE_STATUSES))
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
                    risk_code=risk.risk_code,
                    action=state,
                )
            )
    return actions


def run_sla_monitor(db: Session, notifier: NotificationService, now: dt.datetime) -> int:
    """Apply pending SLA actions: remind on warning, escalate on breach."""
    actions = find_sla_actions(db, now)
    for action in actions:
        risk = db.get(models.Risk, action.risk_id)
        if risk is None:
            continue
        if action.action == "breach":
            transition_risk(db, risk, RiskStatus.ESCALATED.value)
            notifier.notify(
                db,
                event=EVENT_BREACH,
                title=f"SLA breached: {risk.risk_code}",
                body=f"Risk {risk.risk_code} exceeded its SLA deadline and was escalated.",
                risk=risk,
            )
        else:
            notifier.notify(
                db,
                event=EVENT_SLA_WARNING,
                title=f"SLA warning: {risk.risk_code}",
                body=f"Risk {risk.risk_code} is approaching its SLA deadline.",
                risk=risk,
            )
    db.commit()
    return len(actions)


def find_start_date_risks(db: Session, today: dt.date) -> list[models.Risk]:
    """Risks starting today that have not yet had their start notification.

    The dedupe (via the notification rows) lets this run hourly: a risk whose
    start date is set to "today" mid-morning is still caught on the next hourly
    pass, while each owner is only notified once.
    """
    already_notified = select(models.Notification.risk_id).where(
        models.Notification.type == EVENT_RISK_START,
        models.Notification.risk_id.is_not(None),
    )
    return list(
        db.scalars(
            select(models.Risk).where(
                models.Risk.risk_start_date == today,
                # Nothing to send to without an owner (and it would re-fire).
                models.Risk.owner_user_id.is_not(None),
                ~models.Risk.id.in_(already_notified),
            )
        ).all()
    )


def run_start_date_check(
    db: Session, notifier: NotificationService, today: dt.date
) -> int:
    """Notify the owner for every risk starting today."""
    risks = find_start_date_risks(db, today)
    for risk in risks:
        notifier.notify(
            db,
            event=EVENT_RISK_START,
            title=f"Risk starts today: {risk.risk_code}",
            body=f"Risk {risk.risk_code} is now within its active window.",
            risk=risk,
        )
    db.commit()
    return len(risks)


def weekly_summary_data(db: Session) -> dict[str, int | float]:
    """Aggregate portfolio counts for the Monday summary email."""
    total = db.scalar(select(func.count()).select_from(models.Risk)) or 0
    escalated = (
        db.scalar(
            select(func.count())
            .select_from(models.Risk)
            .where(models.Risk.status == RiskStatus.ESCALATED.value)
        )
        or 0
    )
    closed = (
        db.scalar(
            select(func.count())
            .select_from(models.Risk)
            .where(models.Risk.status.in_((RiskStatus.CLOSED.value, RiskStatus.RESOLVED.value)))
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


def find_overdue_risks(db: Session, today: dt.date) -> list[models.Risk]:
    """Acknowledged risks whose Risk End Date has already passed (``end < today``).

    ``today`` is the current date in the business timezone. A risk is overdue
    only after its end-date day has fully elapsed in that timezone, so risks are
    never materialized early because of a timezone/midnight skew. Only
    acknowledged risks materialize: an *unacknowledged* risk past its deadline
    is escalated (not turned into an Event), while an acknowledged-but-unresolved
    risk becomes an Event. Suggested risks are excluded because the status
    machine forbids Suggested -> Event.
    """
    return list(
        db.scalars(
            select(models.Risk)
            .where(
                models.Risk.status.in_(_MATERIALIZABLE_STATUSES),
                models.Risk.sla_acknowledged.is_(True),
                models.Risk.risk_end_date.is_not(None),
                models.Risk.risk_end_date < today,
            )
            .order_by(models.Risk.id)
        ).all()
    )


def find_event_risks_without_issue(db: Session) -> list[models.Risk]:
    """Escalated/Event risks that do not yet have an Issue.

    Kept as a separate sweep so the invariant "one Issue per escalated or
    materialized risk" holds even for risks that reached those statuses through
    a path other than this monitor (e.g. a manual transition or rows created
    before Issues existed).
    """
    with_issue = select(models.Issue.source_risk_id)
    return list(
        db.scalars(
            select(models.Risk)
            .where(
                models.Risk.status.in_(
                    (RiskStatus.EVENT.value, RiskStatus.ESCALATED.value)
                ),
                ~models.Risk.id.in_(with_issue),
            )
            .order_by(models.Risk.id)
        ).all()
    )


def run_end_date_monitor(db: Session, notifier: NotificationService, today: dt.date) -> int:
    """Materialize overdue unresolved risks: Event status + automatic Issue.

    Business rule: once the Risk End Date has passed and the risk is still not
    resolved, the risk becomes an Event (displayed as "Materialized") and a
    single Issue is created from it. Resolved / Closed / Dismissed risks never
    materialize. The operation is idempotent: a second run finds no overdue
    risks (they are Event already) and no Event risk is issued twice (the
    existence check + unique ``source_risk_id``).

    Returns the number of risks materialized in this run.
    """
    materialized = 0
    for risk in find_overdue_risks(db, today):
        # Audit log records the Open/In Progress/Escalated -> Event transition.
        transition_risk(db, risk, RiskStatus.EVENT.value)
        issue = ensure_issue_for_risk(db, risk)
        notifier.notify(
            db,
            event=EVENT_MATERIALIZED,
            title=f"Risk materialized: {risk.risk_code}",
            body=(
                f"Risk {risk.risk_code} passed its risk end date "
                f"({risk.risk_end_date.isoformat() if risk.risk_end_date else '—'}) "
                f"without being resolved and became an Event. "
                f"Issue {issue.issue_code} has been created from the materialized risk."
            ),
            risk=risk,
        )
        materialized += 1

    # Backfill any Event risk that somehow has no Issue yet (manual Event, or
    # rows created before this workflow existed). This is what keeps Issue
    # creation idempotent across repeated scheduler runs.
    for risk in find_event_risks_without_issue(db):
        issue = ensure_issue_for_risk(db, risk)
        notifier.notify(
            db,
            event=EVENT_MATERIALIZED,
            title=f"Issue created: {issue.issue_code}",
            body=(
                f"Issue {issue.issue_code} has been created from materialized "
                f"risk {risk.risk_code}."
            ),
            risk=risk,
        )

    db.commit()
    return materialized


def _get_setting(db: Session, key: str) -> str | None:
    value = db.scalar(select(models.Setting.value).where(models.Setting.key == key))
    return value or None
