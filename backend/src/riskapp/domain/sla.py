"""SLA deadline and warning-window helpers.

The SLA is **PM-defined**: the Risk Start Date is the SLA start and the Risk End
Date *is* the SLA deadline (see :func:`deadline_from_end_date`). The risk rating
represents severity only and never drives the deadline.

Risk rating is still used for one thing: how far ahead of the deadline the
owner is warned. That warning window lives here.

Datetimes are UTC-normalized and naive, matching the application's storage
convention.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, tzinfo

# Warning window (hours before the deadline) by rating. This is the only place
# the rating still influences monitoring cadence; it never moves the deadline.
WARNING_HOURS: dict[str, int] = {
    "High": 4,
    "Medium": 12,
    "Low": 24,
}


def _normalize(rating: str) -> str:
    normalized = rating.strip().title()
    if normalized not in WARNING_HOURS:
        raise ValueError(f"Unknown rating {rating!r}; expected Low / Medium / High")
    return normalized


def warning_hours(rating: str) -> int:
    """Return the warning window in hours before the deadline for a rating."""
    return WARNING_HOURS[_normalize(rating)]


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
