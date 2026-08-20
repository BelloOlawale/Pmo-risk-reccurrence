"""Risk Rating computation from the 3x3 Likelihood x Impact matrix."""

from __future__ import annotations

VALID_LEVELS: tuple[str, ...] = ("Low", "Medium", "High")

# (likelihood, impact) -> risk_rating
_RATING_MATRIX: dict[tuple[str, str], str] = {
    ("High", "High"): "High",
    ("High", "Medium"): "High",
    ("High", "Low"): "Medium",
    ("Medium", "High"): "High",
    ("Medium", "Medium"): "Medium",
    ("Medium", "Low"): "Low",
    ("Low", "High"): "Medium",
    ("Low", "Medium"): "Low",
    ("Low", "Low"): "Low",
}


def normalize_level(value: str) -> str:
    """Normalize a rating level to its canonical form (Low/Medium/High).

    Raises:
        ValueError: if ``value`` is not one of Low / Medium / High (case-insensitive).
    """
    normalized = value.strip().title()
    if normalized not in VALID_LEVELS:
        raise ValueError(f"Invalid level {value!r}; expected one of {VALID_LEVELS}")
    return normalized


def compute_risk_rating(likelihood: str, impact: str) -> str:
    """Compute the Risk Rating from Likelihood and Impact.

    Both inputs must be one of Low / Medium / High (case-insensitive).

    Raises:
        ValueError: if either input is not a valid level.
    """
    lik = normalize_level(likelihood)
    imp = normalize_level(impact)
    return _RATING_MATRIX[(lik, imp)]
