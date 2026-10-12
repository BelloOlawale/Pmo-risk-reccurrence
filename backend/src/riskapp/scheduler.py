"""Scheduler logic: daily reminders, escalation, materialization, summaries.

Monitoring is day-based, in the business timezone:

- daily acknowledgement reminders from the Risk Start Date until three days
  before the Risk End Date (stopping once acknowledged);
- escalation of unacknowledged risks two days before the Risk End Date
  (status -> Escalated, owner + PM emailed, **no** Issue);
- materialization of unresolved risks after the Risk End Date (status -> Event,
  PM emailed, exactly one Issue created).

The pure, testable decision logic lives here; the Celery task wrappers in
:mod:`riskapp.tasks` only open a session and delegate. This keeps the monitor
unit-testable against SQLite with a fake clock, no broker required.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.sla import escalation_date, reminder_last_date
from riskapp.domain.status import RiskStatus
from riskapp.external import acknowledgement_url
from riskapp.notifications import (
    EVENT_ESCALATION,
    EVENT_MATERIALIZED,
    EVENT_OWNER_REMINDER,
    EVENT_WEEKLY_SUMMARY,
    NotificationService,
    Recipients,
    _unique,
    escalation_email,
    owner_reminder_email,
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


def find_daily_reminder_risks(db: Session, today: dt.date) -> list[models.Risk]:
    """Active, unacknowledged, owned risks that are due a reminder today.

    Reminders run every day from the Risk Start Date up to (and including)
    three days before the Risk End Date. They stop once the risk is acknowledged.
    ``last_reminder_on`` keeps the job idempotent within a day, so it is safe to
    run more than once.
    """
    risks = db.scalars(
        select(models.Risk)
        .where(models.Risk.status.in_(_ACTIVE_STATUSES))
        .order_by(models.Risk.id)
    ).all()
    due: list[models.Risk] = []
    for risk in risks:
        if (
            risk.risk_start_date is None
            or risk.risk_end_date is None
            or risk.owner_user_id is None
            or risk.sla_acknowledged
            or risk.last_reminder_on == today
        ):
            continue
        if risk.risk_start_date <= today <= reminder_last_date(risk.risk_end_date):
            due.append(risk)
    return due


def run_daily_reminders(
    db: Session, notifier: NotificationService, today: dt.date
) -> int:
    """Email each due Risk Owner a daily acknowledgement reminder."""
    risks = find_daily_reminder_risks(db, today)
    for risk in risks:
        assert risk.risk_end_date is not None  # filtered by find_daily_reminder_risks
        days_left = (risk.risk_end_date - today).days
        link = acknowledgement_url(risk)
        notifier.notify(
            db,
            event=EVENT_OWNER_REMINDER,
            title=f"Risk acknowledgement reminder: {risk.risk_code}",
            body=(
                f"Risk {risk.risk_code} is still awaiting acknowledgement and has "
                f"{days_left} day(s) left before its risk end date "
                f"({risk.risk_end_date.isoformat()})."
            ),
            risk=risk,
            owner_email_body=(
                owner_reminder_email(risk, link, days_left=days_left) if link else None
            ),
        )
        risk.last_reminder_on = today
    db.commit()
    return len(risks)


def find_escalation_risks(db: Session, today: dt.date) -> list[models.Risk]:
    """Active, unacknowledged, owned risks due for escalation today.

    Escalation fires two days before the Risk End Date and stays pending until
    the owner acknowledges (or the end date arrives and the risk materialises).
    """
    risks = db.scalars(
        select(models.Risk)
        .where(models.Risk.status.in_(_ACTIVE_STATUSES))
        .order_by(models.Risk.id)
    ).all()
    due: list[models.Risk] = []
    for risk in risks:
        if (
            risk.risk_end_date is None
            or risk.owner_user_id is None
            or risk.sla_acknowledged
        ):
            continue
        if today >= escalation_date(risk.risk_end_date):
            due.append(risk)
    return due


def run_escalation_monitor(
    db: Session, notifier: NotificationService, today: dt.date
) -> int:
    """Escalate unacknowledged risks: status -> Escalated, owner + PM emailed.

    Escalated risks deliberately do NOT create an Issue: escalation is a
    monitoring state, not materialization. The risk keeps its owner and may
    still be acknowledged or resolved before the end date.
    """
    risks = find_escalation_risks(db, today)
    for risk in risks:
        transition_risk(db, risk, RiskStatus.ESCALATED.value)
        assert risk.risk_end_date is not None  # filtered by find_escalation_risks
        deadline = escalation_date(risk.risk_end_date)
        link = acknowledgement_url(risk)
        notifier.notify(
            db,
            event=EVENT_ESCALATION,
            title=f"Risk escalated: {risk.risk_code}",
            body=(
                f"Risk {risk.risk_code} was escalated because its Risk Owner did "
                f"not acknowledge it before {deadline.isoformat()}. The Risk Owner "
                f"has been asked to acknowledge and action the response plan."
            ),
            risk=risk,
            owner_email_body=escalation_email(risk, link) if link else None,
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
    """Unresolved risks whose Risk End Date has already passed (``end < today``).

    ``today`` is the current date in the business timezone. A risk is overdue
    only after its end-date day has fully elapsed in that timezone, so risks are
    never materialized early because of a timezone/midnight skew. An unresolved
    risk (Open / In Progress / Escalated) past its end date becomes an Event,
    whether or not it was ever acknowledged. Suggested risks are excluded because
    the status machine forbids Suggested -> Event.
    """
    return list(
        db.scalars(
            select(models.Risk)
            .where(
                models.Risk.status.in_(_MATERIALIZABLE_STATUSES),
                models.Risk.risk_end_date.is_not(None),
                models.Risk.risk_end_date < today,
            )
            .order_by(models.Risk.id)
        ).all()
    )


def find_event_risks_without_issue(db: Session) -> list[models.Risk]:
    """Event risks that do not yet have an Issue.

    Kept as a separate sweep so the invariant "exactly one Issue per materialized
    risk" holds even for risks that reached Event through a path other than this
    monitor (e.g. a manual transition or rows created before Issues existed).
    Escalated risks are deliberately excluded: escalation never creates an Issue.
    """
    with_issue = select(models.Issue.source_risk_id)
    return list(
        db.scalars(
            select(models.Risk)
            .where(
                models.Risk.status == RiskStatus.EVENT.value,
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
        owner = risk.owner
        owner_name = owner.display_name if owner else "Unassigned"
        owner_email = owner.upn if owner else "—"
        notifier.notify(
            db,
            event=EVENT_MATERIALIZED,
            title=f"Risk materialized: {risk.risk_code}",
            body=(
                f"Risk {risk.risk_code} passed its risk end date "
                f"({risk.risk_end_date.isoformat() if risk.risk_end_date else '—'}) "
                f"without being resolved and has become an Event. "
                f"Risk Owner: {owner_name} ({owner_email}). "
                f"Issue {issue.issue_code} has been created from the materialized risk "
                f"and now appears in the Issues table."
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
