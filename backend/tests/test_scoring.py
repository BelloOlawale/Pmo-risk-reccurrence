"""Tests for the 3x3 risk rating matrix."""

import pytest

from riskapp.domain.scoring import compute_risk_rating, normalize_level


class TestComputeRiskRating:
    @pytest.mark.parametrize(
        ("likelihood", "impact", "expected"),
        [
            ("High", "High", "High"),
            ("High", "Medium", "High"),
            ("High", "Low", "Medium"),
            ("Medium", "High", "High"),
            ("Medium", "Medium", "Medium"),
            ("Medium", "Low", "Low"),
            ("Low", "High", "Medium"),
            ("Low", "Medium", "Low"),
            ("Low", "Low", "Low"),
        ],
    )
    def test_matrix(self, likelihood: str, impact: str, expected: str) -> None:
        assert compute_risk_rating(likelihood, impact) == expected

    def test_case_insensitive(self) -> None:
        assert compute_risk_rating("high", "high") == "High"
        assert compute_risk_rating("MEDIUM", "low") == "Low"

    def test_whitespace_trimmed(self) -> None:
        assert compute_risk_rating("  High  ", " Medium ") == "High"


class TestNormalizeLevel:
    def test_valid(self) -> None:
        assert normalize_level("high") == "High"
        assert normalize_level("Medium") == "Medium"
        assert normalize_level("LOW") == "Low"

    @pytest.mark.parametrize("bad", ["", "Critical", "Very High", "3", "None"])
    def test_invalid_raises(self, bad: str) -> None:
        with pytest.raises(ValueError):
            normalize_level(bad)

    def test_invalid_rating_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_risk_rating("High", "Critical")
