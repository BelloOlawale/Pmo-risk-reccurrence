"""Tests for SLA deadline, warning windows, and activity detection."""

from datetime import datetime, timedelta

import pytest

from riskapp.domain.sla import (
    compute_deadline,
    evaluate_sla,
    has_activity,
    sla_hours,
    warning_hours,
)


class TestSlaHours:
    @pytest.mark.parametrize(
        ("rating", "hours"),
        [("High", 24), ("Medium", 48), ("Low", 120)],
    )
    def test_values(self, rating: str, hours: int) -> None:
        assert sla_hours(rating) == hours

    def test_case_insensitive(self) -> None:
        assert sla_hours("HIGH") == 24

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            sla_hours("Critical")


class TestWarningHours:
    @pytest.mark.parametrize(
        ("rating", "hours"),
        [("High", 4), ("Medium", 12), ("Low", 24)],
    )
    def test_values(self, rating: str, hours: int) -> None:
        assert warning_hours(rating) == hours


class TestComputeDeadline:
    def test_high(self) -> None:
        created = datetime(2026, 8, 20, 9, 0, 0)
        assert compute_deadline("High", created) == datetime(2026, 8, 21, 9, 0, 0)

    def test_low_is_five_days(self) -> None:
        created = datetime(2026, 8, 20, 9, 0, 0)
        assert compute_deadline("Low", created) == datetime(2026, 8, 25, 9, 0, 0)


class TestHasActivity:
    def test_none(self) -> None:
        assert not has_activity()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"owner_edited": True},
            {"status_changed": True},
            {"acknowledged": True},
        ],
    )
    def test_any_single_signal(self, kwargs: dict[str, bool]) -> None:
        assert has_activity(**kwargs)


class TestEvaluateSla:
    NOW = datetime(2026, 8, 20, 12, 0, 0)

    def test_satisfied_when_activity(self) -> None:
        result = evaluate_sla(
            rating="High",
            created_at=self.NOW - timedelta(hours=100),
            now=self.NOW,
            owner_edited=True,
        )
        assert result == "satisfied"

    def test_breach_when_deadline_passed(self) -> None:
        created = self.NOW - timedelta(hours=25)  # past the 24h High deadline
        assert evaluate_sla(rating="High", created_at=created, now=self.NOW) == "breach"

    def test_warning_when_inside_window(self) -> None:
        # High: 24h deadline, 4h warning -> warning from hour 20 onward.
        created = self.NOW - timedelta(hours=21)
        assert evaluate_sla(rating="High", created_at=created, now=self.NOW) == "warning"

    def test_ok_when_before_warning(self) -> None:
        created = self.NOW - timedelta(hours=10)
        assert evaluate_sla(rating="High", created_at=created, now=self.NOW) == "ok"

    def test_exact_deadline_is_breach(self) -> None:
        created = self.NOW - timedelta(hours=24)
        assert evaluate_sla(rating="High", created_at=created, now=self.NOW) == "breach"
