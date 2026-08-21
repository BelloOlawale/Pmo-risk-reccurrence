"""SLA deadline, warning windows, and activity-based monitoring logic.

Datetimes here are UTC-normalized and naive, matching the application's
storage convention. ``deadline_anchor`` is the single place a business
``tz`` is applied to a date-only start date.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, tzinfo

# SLA response windows (hours) by rating.
SLA_HOURS: dict[str, int] = {
    "High": 24,
    "Medium": 48,
    "Low": 120,  # 5 days
}

# Warning window (hours before the deadline) by rating.
WARNING_HOURS: dict[str, int] = {
    "High": 4,
    "Medium": 12,
    "Low": 24,
}


def _normalize(rating: str) -> str:
    normalized = rating.strip().title()
    if normalized not in SLA_HOURS:
        raise ValueError(f"Unknown rating {rating!r}; expected Low / Medium / High")
    return normalized


def sla_hours(rating: str) -> int:
    """Return the SLA response window in hours for a rating."""
    return SLA_HOURS[_normalize(rating)]


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


def deadline_anchor(
    start_date: date | None, created_at: datetime, tz: tzinfo
) -> datetime:
    """Return the UTC-normalized datetime from which the SLA window starts.

    The clock starts at midnight of ``start_date`` in the business timezone
    ``tz``. When no start date is set, it falls back to the risk's creation
    time. The result is always a naive UTC datetime.
    """
    if start_date is not None:
        midnight_local = datetime.combine(start_date, time.min, tzinfo=tz)
        return as_naive_utc(midnight_local)
    return as_naive_utc(created_at)


def compute_deadline(rating: str, start_at: datetime) -> datetime:
    """Return the SLA deadline: the window start plus the rating's response window."""
    return start_at + timedelta(hours=sla_hours(rating))


def has_activity(
    *,
    owner_edited: bool = False,
    status_changed: bool = False,
    acknowledged: bool = False,
) -> bool:
    """Return True if any signal indicates the owner has responded.

    Activity is any of: an owner field edit, a status change, or an explicit
    acknowledge. Once activity occurs, the SLA is permanently satisfied.
    """
    return owner_edited or status_changed or acknowledged


def evaluate_sla(
    *,
    rating: str,
    start_at: datetime,
    now: datetime,
    owner_edited: bool = False,
    status_changed: bool = False,
    acknowledged: bool = False,
) -> str:
    """Determine the monitoring action for an active risk.

    Returns one of:
      "satisfied" — the owner already responded; SLA permanently met.
      "breach"    — deadline passed with no activity; escalate.
      "warning"   — within the warning window with no activity; remind.
      "ok"        — still within SLA and before the warning window.
    """
    if has_activity(
        owner_edited=owner_edited, status_changed=status_changed, acknowledged=acknowledged
    ):
        return "satisfied"

    deadline = compute_deadline(rating, start_at)
    if now >= deadline:
        return "breach"

    if now >= deadline - timedelta(hours=warning_hours(rating)):
        return "warning"

    return "ok"
