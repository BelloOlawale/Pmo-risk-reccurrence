"""Tests for the PM-defined SLA deadline and day-based monitoring offsets."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from riskapp.domain.sla import (
    as_naive_utc,
    deadline_from_end_date,
    escalation_date,
    reminder_last_date,
)


class TestMonitoringOffsets:
    def test_reminder_last_date_is_three_days_before_end(self) -> None:
        assert reminder_last_date(date(2026, 8, 30)) == date(2026, 8, 27)

    def test_escalation_date_is_two_days_before_end(self) -> None:
        assert escalation_date(date(2026, 8, 30)) == date(2026, 8, 28)


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
