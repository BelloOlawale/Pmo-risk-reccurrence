"""Tests for the PM-defined SLA deadline and the rating's warning window."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from riskapp.domain.sla import (
    as_naive_utc,
    deadline_from_end_date,
    warning_hours,
)


class TestWarningHours:
    @pytest.mark.parametrize(
        ("rating", "hours"),
        [("High", 4), ("Medium", 12), ("Low", 24)],
    )
    def test_values(self, rating: str, hours: int) -> None:
        assert warning_hours(rating) == hours

    def test_case_insensitive(self) -> None:
        assert warning_hours("HIGH") == 4

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            warning_hours("Critical")


class TestAsNaiveUtc:
    def test_naive_unchanged(self) -> None:
        naive = datetime(2026, 8, 25, 23, 0, 0)
        assert as_naive_utc(naive) == naive

    def test_aware_converts_to_utc(self) -> None:
        # 2026-08-25 00:00 Africa/Lagos (UTC+1) == 2026-08-24 23:00 UTC.
        aware = datetime(2026, 8, 25, 0, 0, 0, tzinfo=ZoneInfo("Africa/Lagos"))
        assert as_naive_utc(aware) == datetime(2026, 8, 24, 23, 0, 0)


class TestDeadlineFromEndDate:
    def test_none_when_no_end_date(self) -> None:
        assert deadline_from_end_date(None, ZoneInfo("Africa/Lagos")) is None

    def test_end_of_day_in_business_tz(self) -> None:
        # End of 2099-08-30 Africa/Lagos (UTC+1) == 2099-08-30 22:59:59.999999 UTC.
        assert deadline_from_end_date(
            date(2099, 8, 30), ZoneInfo("Africa/Lagos")
        ) == datetime(2099, 8, 30, 22, 59, 59, 999999)
