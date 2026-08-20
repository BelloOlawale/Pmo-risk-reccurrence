"""SLA deadline, warning windows, and activity-based monitoring logic."""

from __future__ import annotations

from datetime import datetime, timedelta

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


def compute_deadline(rating: str, created_at: datetime) -> datetime:
    """Return the SLA deadline: creation time plus the rating's response window."""
    return created_at + timedelta(hours=sla_hours(rating))


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
    created_at: datetime,
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

    deadline = compute_deadline(rating, created_at)
    if now >= deadline:
        return "breach"

    if now >= deadline - timedelta(hours=warning_hours(rating)):
        return "warning"

    return "ok"
