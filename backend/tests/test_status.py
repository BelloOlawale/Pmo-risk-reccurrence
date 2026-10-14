"""Tests for the risk status lifecycle."""

import pytest

from riskapp.domain.status import (
    RiskStatus,
    allowed_transitions,
    can_transition,
    display_label,
    is_terminal,
)


class TestTransitions:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (RiskStatus.SUGGESTED, RiskStatus.OPEN),
            (RiskStatus.SUGGESTED, RiskStatus.DISMISSED),
            (RiskStatus.OPEN, RiskStatus.IN_PROGRESS),
            (RiskStatus.OPEN, RiskStatus.ESCALATED),
            (RiskStatus.OPEN, RiskStatus.EVENT),
            (RiskStatus.OPEN, RiskStatus.PENDING_RESOLUTION),
            (RiskStatus.IN_PROGRESS, RiskStatus.ESCALATED),
            (RiskStatus.IN_PROGRESS, RiskStatus.EVENT),
            (RiskStatus.IN_PROGRESS, RiskStatus.PENDING_RESOLUTION),
            (RiskStatus.ESCALATED, RiskStatus.IN_PROGRESS),
            (RiskStatus.ESCALATED, RiskStatus.EVENT),
            (RiskStatus.ESCALATED, RiskStatus.PENDING_RESOLUTION),
            (RiskStatus.EVENT, RiskStatus.PENDING_RESOLUTION),
            # PM accepts the owner's proposed resolution.
            (RiskStatus.PENDING_RESOLUTION, RiskStatus.RESOLVED),
            # PM rejects the owner's proposed resolution.
            (RiskStatus.PENDING_RESOLUTION, RiskStatus.IN_PROGRESS),
            (RiskStatus.RESOLVED, RiskStatus.CLOSED),
        ],
    )
    def test_valid(self, current: RiskStatus, target: RiskStatus) -> None:
        assert can_transition(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            # Can't accept after dismissal/closure.
            (RiskStatus.DISMISSED, RiskStatus.OPEN),
            (RiskStatus.CLOSED, RiskStatus.OPEN),
            # Can't reopen once closed.
            (RiskStatus.CLOSED, RiskStatus.IN_PROGRESS),
            # Can't jump backwards arbitrarily.
            (RiskStatus.RESOLVED, RiskStatus.OPEN),
            (RiskStatus.RESOLVED, RiskStatus.IN_PROGRESS),
            (RiskStatus.RESOLVED, RiskStatus.PENDING_RESOLUTION),
            (RiskStatus.IN_PROGRESS, RiskStatus.OPEN),
            (RiskStatus.EVENT, RiskStatus.OPEN),
            (RiskStatus.EVENT, RiskStatus.ESCALATED),
            (RiskStatus.ESCALATED, RiskStatus.OPEN),
            # A pending resolution only becomes Resolved or In Progress.
            (RiskStatus.PENDING_RESOLUTION, RiskStatus.OPEN),
            (RiskStatus.PENDING_RESOLUTION, RiskStatus.CLOSED),
            (RiskStatus.PENDING_RESOLUTION, RiskStatus.EVENT),
            # Suggested can only become Open or Dismissed.
            (RiskStatus.SUGGESTED, RiskStatus.IN_PROGRESS),
            (RiskStatus.SUGGESTED, RiskStatus.RESOLVED),
            (RiskStatus.SUGGESTED, RiskStatus.CLOSED),
        ],
    )
    def test_invalid(self, current: RiskStatus, target: RiskStatus) -> None:
        assert not can_transition(current, target)

    def test_accepts_strings(self) -> None:
        assert can_transition("Suggested", "Open")
        assert not can_transition("Closed", "Open")


class TestTerminal:
    @pytest.mark.parametrize(
        "status",
        [RiskStatus.CLOSED, RiskStatus.DISMISSED],
    )
    def test_terminal(self, status: RiskStatus) -> None:
        assert is_terminal(status)

    @pytest.mark.parametrize(
        "status",
        [
            RiskStatus.SUGGESTED,
            RiskStatus.OPEN,
            RiskStatus.IN_PROGRESS,
            RiskStatus.ESCALATED,
            RiskStatus.EVENT,
            RiskStatus.PENDING_RESOLUTION,
            RiskStatus.RESOLVED,
        ],
    )
    def test_not_terminal(self, status: RiskStatus) -> None:
        assert not is_terminal(status)


class TestAllowedTransitions:
    def test_suggested(self) -> None:
        assert allowed_transitions(RiskStatus.SUGGESTED) == frozenset(
            {RiskStatus.OPEN, RiskStatus.DISMISSED}
        )


class TestDisplayLabel:
    def test_event_reads_materialized(self) -> None:
        assert display_label(RiskStatus.EVENT) == "Materialized"

    def test_other_statuses_use_their_name(self) -> None:
        assert display_label(RiskStatus.OPEN) == "Open"
        assert display_label(RiskStatus.CLOSED) == "Closed"


class TestTransitionMatrix:
    """The documented actor matrix must match the enforced state machine."""

    def test_matrix_covers_exactly_the_valid_transitions(self) -> None:
        from riskapp.domain.status import TRANSITION_MATRIX, allowed_transitions

        expected = {
            (current, target)
            for current in RiskStatus
            for target in allowed_transitions(current)
        }
        assert set(TRANSITION_MATRIX) == expected

    def test_every_matrix_edge_has_at_least_one_actor(self) -> None:
        from riskapp.domain.status import TRANSITION_MATRIX

        assert all(actors for actors in TRANSITION_MATRIX.values())

    def test_closure_is_project_manager_or_higher(self) -> None:
        from riskapp.domain.status import PM, PMO_LEAD, SYSTEM_ADMIN, actors_for_transition

        actors = actors_for_transition(RiskStatus.RESOLVED, RiskStatus.CLOSED)
        assert actors == frozenset({PM, PMO_LEAD, SYSTEM_ADMIN})

    def test_owner_can_submit_a_resolution_but_never_close(self) -> None:
        from riskapp.domain.status import OWNER, actors_for_transition

        assert OWNER in actors_for_transition(
            RiskStatus.IN_PROGRESS, RiskStatus.PENDING_RESOLUTION
        )
        assert OWNER not in actors_for_transition(
            RiskStatus.RESOLVED, RiskStatus.CLOSED
        )

    def test_unknown_transition_has_no_actors(self) -> None:
        from riskapp.domain.status import actors_for_transition

        assert actors_for_transition(RiskStatus.OPEN, RiskStatus.CLOSED) == frozenset()
