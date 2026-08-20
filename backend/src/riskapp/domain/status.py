"""Risk status lifecycle and valid transition rules."""

from __future__ import annotations

from enum import Enum


class RiskStatus(str, Enum):  # noqa: UP042 — str+Enum is intentional (DB-friendly values)
    """The merged risk lifecycle (FRD + PMO doc)."""

    SUGGESTED = "Suggested"
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    ESCALATED = "Escalated"
    EVENT = "Event"
    RESOLVED = "Resolved"
    CLOSED = "Closed"
    DISMISSED = "Dismissed"


# User-facing label overrides (team vocabulary). "Event" reads as "Materialized".
DISPLAY_LABELS: dict[RiskStatus, str] = {
    RiskStatus.EVENT: "Materialized",
}


def display_label(status: RiskStatus | str) -> str:
    """Return the user-facing label for a status (e.g. Event -> Materialized)."""
    st = RiskStatus(status)
    return DISPLAY_LABELS.get(st, st.value)


# Valid transitions: current status -> set of allowed next statuses.
_TRANSITIONS: dict[RiskStatus, frozenset[RiskStatus]] = {
    RiskStatus.SUGGESTED: frozenset({RiskStatus.OPEN, RiskStatus.DISMISSED}),
    RiskStatus.OPEN: frozenset(
        {
            RiskStatus.IN_PROGRESS,
            RiskStatus.ESCALATED,
            RiskStatus.EVENT,
            RiskStatus.RESOLVED,
        }
    ),
    RiskStatus.IN_PROGRESS: frozenset(
        {
            RiskStatus.ESCALATED,
            RiskStatus.EVENT,
            RiskStatus.RESOLVED,
        }
    ),
    RiskStatus.ESCALATED: frozenset(
        {
            RiskStatus.IN_PROGRESS,
            RiskStatus.EVENT,
            RiskStatus.RESOLVED,
        }
    ),
    RiskStatus.EVENT: frozenset({RiskStatus.RESOLVED}),
    RiskStatus.RESOLVED: frozenset({RiskStatus.CLOSED}),
    RiskStatus.CLOSED: frozenset(),
    RiskStatus.DISMISSED: frozenset(),
}


def can_transition(current: RiskStatus | str, target: RiskStatus | str) -> bool:
    """Return True if ``target`` is a valid next status from ``current``."""
    return RiskStatus(target) in _TRANSITIONS[RiskStatus(current)]


def allowed_transitions(current: RiskStatus | str) -> frozenset[RiskStatus]:
    """Return the set of statuses reachable in one step from ``current``."""
    return _TRANSITIONS[RiskStatus(current)]


def is_terminal(status: RiskStatus | str) -> bool:
    """Return True if ``status`` has no further transitions."""
    return not _TRANSITIONS[RiskStatus(status)]
