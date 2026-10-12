"""SLA deadline and day-based monitoring helpers.

The SLA is **PM-defined**: the Risk Start Date is the SLA start and the Risk End
Date *is* the SLA deadline and resolution deadline (see
:func:`deadline_from_end_date`). The risk rating represents severity only and
never drives the deadline or the monitoring cadence.

Monitoring is expressed in whole days before the Risk End Date: daily owner
reminders up to three days before, then escalation two days before, then
materialization once the end date has passed.

Datetimes are UTC-normalized and naive, matching the application's storage
convention.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, tzinfo

# Owner monitoring cadence, expressed in whole days before the Risk End Date.
#
# Daily acknowledgement reminders run from the Risk Start Date up to and
# including ``REMINDER_LEAD_DAYS`` before the end date. An unacknowledged risk is
# escalated (email to owner + PM, status -> Escalated) from
# ``ESCALATION_LEAD_DAYS`` before the end date. Once the end date has passed and
# the risk is still unresolved it materialises (status -> Event + Issue).
REMINDER_LEAD_DAYS = 3
ESCALATION_LEAD_DAYS = 2


def reminder_last_date(end_date: date) -> date:
    """Last day on which a daily owner reminder is sent (end date - 3 days)."""
    return end_date - timedelta(days=REMINDER_LEAD_DAYS)


def escalation_date(end_date: date) -> date:
    """Day on which an unacknowledged risk escalates (end date - 2 days)."""
    return end_date - timedelta(days=ESCALATION_LEAD_DAYS)


def as_naive_utc(value: datetime) -> datetime:
    """Return ``value`` as a naive UTC datetime.

    Timezone-aware values are converted to UTC and stripped of their offset;
    naive values are returned unchanged (assumed to already be UTC).
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def deadline_from_end_date(end_date: date | None, tz: tzinfo) -> datetime | None:
    """Return the SLA deadline for a manually-set Risk End Date.

    The Risk End Date *is* the SLA deadline: a risk is due by the end of that
    day in the business timezone. The result is a naive UTC datetime, matching
    the application's storage convention. Returns ``None`` when no end date is
    set (the risk then has no SLA deadline).
    """
    if end_date is None:
        return None
    end_of_day = datetime.combine(end_date, time.max, tzinfo=tz)
    return as_naive_utc(end_of_day)
