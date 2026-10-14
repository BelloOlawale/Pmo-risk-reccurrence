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
    PENDING_RESOLUTION = "Pending Resolution"
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
            RiskStatus.PENDING_RESOLUTION,
        }
    ),
    RiskStatus.IN_PROGRESS: frozenset(
        {
            RiskStatus.ESCALATED,
            RiskStatus.EVENT,
            RiskStatus.PENDING_RESOLUTION,
        }
    ),
    RiskStatus.ESCALATED: frozenset(
        {
            RiskStatus.IN_PROGRESS,
            RiskStatus.EVENT,
            RiskStatus.PENDING_RESOLUTION,
        }
    ),
    RiskStatus.EVENT: frozenset({RiskStatus.PENDING_RESOLUTION}),
    # A proposed resolution only becomes Resolved when the Project Manager
    # accepts it, or goes back to In Progress when they reject it.
    RiskStatus.PENDING_RESOLUTION: frozenset(
        {RiskStatus.RESOLVED, RiskStatus.IN_PROGRESS}
    ),
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


# ---------------------------------------------------------------------------
# Concrete status-transition matrix
# ---------------------------------------------------------------------------
#
# Every edge of the lifecycle above, paired with the actor(s) allowed to cause
# it. The keys of this mapping are asserted (in the test suite) to be exactly
# the valid transitions in ``_TRANSITIONS`` — so the matrix can never silently
# drift from the enforced state machine. It is documentation that is checked by
# a test, not a second, competing source of truth.
#
# Actor labels are deliberately role-flavoured rather than principal objects:
#
#   Owner          — the assigned Risk Owner (acts from their signed link)
#   PM             — the Project Manager of the risk's project
#   PMO Lead       — portfolio-wide governance role
#   System Admin   — application superuser
#   System         — the scheduler / background monitors (no human actor)
OWNER = "Risk Owner"
PM = "Project Manager"
PMO_LEAD = "PMO Lead"
SYSTEM_ADMIN = "System Admin"
SYSTEM = "System"

TRANSITION_MATRIX: dict[tuple[RiskStatus, RiskStatus], frozenset[str]] = {
    (RiskStatus.SUGGESTED, RiskStatus.OPEN): frozenset({PM, PMO_LEAD, SYSTEM_ADMIN}),
    (RiskStatus.SUGGESTED, RiskStatus.DISMISSED): frozenset({PM, PMO_LEAD, SYSTEM_ADMIN}),
    # Acknowledging / owner assignment moves a live risk into delivery.
    (RiskStatus.OPEN, RiskStatus.IN_PROGRESS): frozenset(
        {OWNER, PM, PMO_LEAD, SYSTEM_ADMIN}
    ),
    (RiskStatus.OPEN, RiskStatus.ESCALATED): frozenset({SYSTEM}),
    (RiskStatus.OPEN, RiskStatus.EVENT): frozenset({PM, PMO_LEAD, SYSTEM_ADMIN, SYSTEM}),
    # The owner proposes a resolution (requires a Resolution Summary); staff may
    # record it on the owner's behalf through the same guarded service call.
    (RiskStatus.OPEN, RiskStatus.PENDING_RESOLUTION): frozenset(
        {OWNER, PM, PMO_LEAD, SYSTEM_ADMIN}
    ),
    (RiskStatus.IN_PROGRESS, RiskStatus.ESCALATED): frozenset({SYSTEM}),
    (RiskStatus.IN_PROGRESS, RiskStatus.EVENT): frozenset(
        {PM, PMO_LEAD, SYSTEM_ADMIN, SYSTEM}
    ),
    (RiskStatus.IN_PROGRESS, RiskStatus.PENDING_RESOLUTION): frozenset(
        {OWNER, PM, PMO_LEAD, SYSTEM_ADMIN}
    ),
    # De-escalation is a deliberate management decision, not an owner action.
    (RiskStatus.ESCALATED, RiskStatus.IN_PROGRESS): frozenset({PM, PMO_LEAD, SYSTEM_ADMIN}),
    (RiskStatus.ESCALATED, RiskStatus.EVENT): frozenset(
        {PM, PMO_LEAD, SYSTEM_ADMIN, SYSTEM}
    ),
    (RiskStatus.ESCALATED, RiskStatus.PENDING_RESOLUTION): frozenset(
        {OWNER, PM, PMO_LEAD, SYSTEM_ADMIN}
    ),
    # A materialized risk can still be resolved; it can no longer be closed
    # without first going through review.
    (RiskStatus.EVENT, RiskStatus.PENDING_RESOLUTION): frozenset(
        {OWNER, PM, PMO_LEAD, SYSTEM_ADMIN}
    ),
    # The Project Manager (or PMO Lead / Admin) reviews the proposed resolution.
    (RiskStatus.PENDING_RESOLUTION, RiskStatus.RESOLVED): frozenset(
        {PM, PMO_LEAD, SYSTEM_ADMIN}
    ),
    (RiskStatus.PENDING_RESOLUTION, RiskStatus.IN_PROGRESS): frozenset(
        {PM, PMO_LEAD, SYSTEM_ADMIN}
    ),
    # Final closure: the project's PM, or the PMO Lead / Admin.
    (RiskStatus.RESOLVED, RiskStatus.CLOSED): frozenset({PM, PMO_LEAD, SYSTEM_ADMIN}),
}


def actors_for_transition(
    current: RiskStatus | str, target: RiskStatus | str
) -> frozenset[str]:
    """Return the actor labels allowed to perform ``current -> target``.

    Returns an empty frozenset when the transition is not valid at all.
    """
    return TRANSITION_MATRIX.get((RiskStatus(current), RiskStatus(target)), frozenset())


class InvalidTransitionError(ValueError):
    """Raised when a requested status transition is not allowed."""


def ensure_transition(current: RiskStatus | str, target: RiskStatus | str) -> RiskStatus:
    """Return the target status if the transition is valid, else raise.

    Raises:
        InvalidTransitionError: if the transition is not allowed.
        ValueError: if ``target`` is not a known status.
    """
    cur = RiskStatus(current)
    tgt = RiskStatus(target)
    if not can_transition(cur, tgt):
        raise InvalidTransitionError(f"Cannot transition from {cur.value} to {tgt.value}")
    return tgt
