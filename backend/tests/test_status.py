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
            (RiskStatus.OPEN, RiskStatus.RESOLVED),
            (RiskStatus.IN_PROGRESS, RiskStatus.ESCALATED),
            (RiskStatus.IN_PROGRESS, RiskStatus.EVENT),
            (RiskStatus.IN_PROGRESS, RiskStatus.RESOLVED),
            (RiskStatus.ESCALATED, RiskStatus.IN_PROGRESS),
            (RiskStatus.ESCALATED, RiskStatus.EVENT),
            (RiskStatus.ESCALATED, RiskStatus.RESOLVED),
            (RiskStatus.EVENT, RiskStatus.RESOLVED),
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
            (RiskStatus.IN_PROGRESS, RiskStatus.OPEN),
            (RiskStatus.EVENT, RiskStatus.OPEN),
            (RiskStatus.EVENT, RiskStatus.ESCALATED),
            (RiskStatus.ESCALATED, RiskStatus.OPEN),
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
