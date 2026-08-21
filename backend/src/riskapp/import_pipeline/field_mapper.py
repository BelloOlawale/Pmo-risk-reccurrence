"""Map Excel columns to the canonical risk fields.

Handles the ~9 known Excel schemas (PUNUKA, PUNUKA Extended, WACL, TNL,
Seamless HR, PROWEB, ORIGIN, Issues Log, and a generic best-effort fallback).
Each mapper produces a :class:`MappedRisk` dict in canonical snake_case keys;
the importer turns those into :class:`~riskapp.models.Risk` rows.

Ratings follow SPEC §4: ``risk_rating`` is always computed from the 3×3
Likelihood × Impact matrix. Unknown/empty levels are treated as ``Medium``
(the historical pipeline's default).
"""

from __future__ import annotations

from typing import TypedDict

from riskapp.domain.scoring import compute_risk_rating


class MappedRisk(TypedDict, total=False):
    """Canonical risk record produced by the field mappers."""

    risk_description: str
    risk_category: str
    subcategory: str
    likelihood: str
    impact: str
    risk_rating: str
    project_lifecycle_stage: str
    response_strategy: str
    response_plan: str
    risk_owner: str
    source_file_name: str
    source_file_url: str
    source_risk_id: str
    department: str
    project_type: str


_VALID_LEVELS = frozenset({"Low", "Medium", "High"})


def normalize_level(value: str) -> str:
    """Normalize a likelihood/impact value to Low/Medium/High.

    Empty or unrecognized values default to ``Medium`` (the historical
    pipeline's provisional default for missing ratings).
    """
    normalized = value.strip().title()
    return normalized if normalized in _VALID_LEVELS else "Medium"


def compute_rating(likelihood: str, impact: str) -> str:
    """Compute risk_rating from likelihood and impact via the 3×3 matrix."""
    return compute_risk_rating(normalize_level(likelihood), normalize_level(impact))


def map_hml_to_full(value: str) -> str:
    """Map single-letter H/M/L to full High/Medium/Low words.

    Already-full words pass through. Empty or unrecognized returns empty.
    """
    cleaned = value.strip()
    if not cleaned:
        return ""

    mapping = {"H": "High", "M": "Medium", "L": "Low"}
    if cleaned.upper() in mapping:
        return mapping[cleaned.upper()]

    # Already a full word — normalize case
    titled = cleaned.title()
    if titled in ("High", "Medium", "Low"):
        return titled

    return ""


def map_numeric_to_level(value: str) -> str:
    """Map 1-5 numeric scale to High/Medium/Low.

    1-2 → Low, 3 → Medium, 4-5 → High. Non-numeric (TBD, empty) returns empty.
    """
    cleaned = value.strip()
    if not cleaned:
        return ""

    try:
        num = int(cleaned)
    except ValueError:
        return ""

    if num <= 2:
        return "Low"
    if num == 3:
        return "Medium"
    return "High"


def map_punuka_row(
    row: dict[str, str], department: str, project_type: str, source_file: str
) -> MappedRisk:
    """Map Schema A (PUNUKA) row to canonical fields."""
    likelihood = row.get("Likelihood", "")
    impact = row.get("Impact", "")
    return MappedRisk(
        risk_description=row.get("Risk Description", ""),
        risk_category=row.get("Risk Category", ""),
        likelihood=likelihood,
        impact=impact,
        risk_rating=compute_rating(likelihood, impact),
        response_strategy=row.get("Mitigation Strategy", ""),
        risk_owner=row.get("Risk Owner", ""),
        source_risk_id=row.get("Risk ID", ""),
        source_file_name=source_file,
        department=department,
        project_type=project_type,
    )


def map_wacl_row(
    row: dict[str, str], department: str, project_type: str, source_file: str
) -> MappedRisk:
    """Map Schema B (WACL) row to canonical fields."""
    likelihood = map_numeric_to_level(row.get("Probability", ""))
    impact = map_numeric_to_level(row.get("Impact", ""))

    return MappedRisk(
        risk_description=row.get("Description of Risk", ""),
        likelihood=likelihood,
        impact=impact,
        risk_rating=compute_rating(likelihood, impact),
        response_plan=row.get("Risk Reponse", ""),
        risk_owner=row.get("Risk owner", ""),
        source_risk_id=row.get("ID", ""),
        source_file_name=source_file,
        department=department,
        project_type=project_type,
    )


def map_tnl_row(
    row: dict[str, str], department: str, project_type: str, source_file: str
) -> MappedRisk:
    """Map Schema C (TNL) row to canonical fields."""
    likelihood = map_hml_to_full(row.get("Probability (H/M/L)", ""))
    impact = map_hml_to_full(row.get("Impact (H/M/L)", ""))
    return MappedRisk(
        risk_description=row.get("Risk Description", ""),
        likelihood=likelihood,
        impact=impact,
        risk_rating=compute_rating(likelihood, impact),
        response_plan=row.get("Mitigation Steps", ""),
        risk_owner=row.get("Owner", ""),
        source_file_name=source_file,
        department=department,
        project_type=project_type,
    )


def map_seamless_hr_row(
    row: dict[str, str], department: str, project_type: str, source_file: str
) -> MappedRisk:
    """Map Schema D (Seamless HR) row to canonical fields."""
    likelihood = map_numeric_to_level(row.get("Probability (1-5)", ""))
    impact = map_numeric_to_level(row.get("Impact (1-5)", ""))
    return MappedRisk(
        risk_description=row.get("Risk Description", ""),
        likelihood=likelihood,
        impact=impact,
        risk_rating=compute_rating(likelihood, impact),
        response_strategy=row.get("Risk Response", ""),
        risk_owner=row.get("Owner", ""),
        source_risk_id=row.get("S/N", ""),
        source_file_name=source_file,
        department=department,
        project_type=project_type,
    )


def map_punuka_extended_row(
    row: dict[str, str], department: str, project_type: str, source_file: str
) -> MappedRisk:
    """Map PUNUKA Extended (11+ cols) to canonical fields."""
    likelihood = row.get("Likelihood", "")
    impact = row.get("Impact", "")

    return MappedRisk(
        risk_description=row.get("Risk Description", row.get("Risk", "")),
        risk_category=row.get("Risk Category", ""),
        likelihood=likelihood,
        impact=impact,
        risk_rating=compute_rating(likelihood, impact),
        project_lifecycle_stage=row.get("Project Lifecycle Stage", ""),
        response_strategy=row.get("Response Strategy", row.get("Mitigation Strategy", "")),
        response_plan=row.get("Risk Response Plan", ""),
        risk_owner=row.get("Risk Owner", ""),
        source_risk_id=row.get("Risk ID", ""),
        source_file_name=source_file,
        department=department,
        project_type=project_type,
    )


def map_prowweb_row(
    row: dict[str, str], department: str, project_type: str, source_file: str
) -> MappedRisk:
    """Map PROWEB-style (8 cols) to canonical fields.

    Headers: ID, PLC, Date, RISK, MATERIALIZED RISK?, PROBABILITY 1-5, IMPACT 1-5, PI SCORE
    """
    likelihood = map_numeric_to_level(row.get("PROBABILITY 1-5", ""))
    impact = map_numeric_to_level(row.get("IMPACT 1-5", ""))
    return MappedRisk(
        risk_description=row.get("RISK", ""),
        likelihood=likelihood,
        impact=impact,
        risk_rating=compute_rating(likelihood, impact),
        project_lifecycle_stage=row.get("PLC", ""),
        source_risk_id=row.get("ID", ""),
        source_file_name=source_file,
        department=department,
        project_type=project_type,
    )


def map_origin_row(
    row: dict[str, str], department: str, project_type: str, source_file: str
) -> MappedRisk:
    """Map ORIGIN-style (15 cols) to canonical fields.

    Probability format: "High (80%)", "Medium (40%)", etc.
    """
    likelihood = _extract_level_from_parens(row.get("Probability", ""))
    impact = _extract_level_from_parens(row.get("Impact", ""))

    return MappedRisk(
        risk_description=row.get("Description", ""),
        risk_category=row.get("Category", ""),
        likelihood=likelihood,
        impact=impact,
        risk_rating=compute_rating(likelihood, impact),
        response_strategy=row.get("Response Strategy", ""),
        risk_owner=row.get("Risk Owner", ""),
        source_risk_id=row.get("Risk ID", ""),
        source_file_name=source_file,
        department=department,
        project_type=project_type,
    )


def map_issues_log_row(
    row: dict[str, str], department: str, project_type: str, source_file: str
) -> MappedRisk:
    """Map Issues Log format to canonical fields (best-effort).

    These are issue logs, not risk registers. We extract what we can.
    """
    return MappedRisk(
        risk_description=row.get("Issue", row.get("RISK", "")),
        project_lifecycle_stage=row.get("PLC", ""),
        likelihood="Medium",
        impact="Medium",
        risk_rating="Medium",
        risk_owner=row.get("Owner", ""),
        source_risk_id=row.get("ID", row.get("Risk ID", "")),
        source_file_name=source_file,
        department=department,
        project_type=project_type,
    )


def map_generic_row(
    row: dict[str, str], department: str, project_type: str, source_file: str
) -> MappedRisk:
    """Best-effort mapping for unknown schemas."""
    description = _first_present(
        row, ("Risk Description", "Description of Risk", "Description",
              "Risk", "RISK", "Issue", "Risk Title")
    )
    likelihood = _first_level(
        row, ("Likelihood", "Probability", "PROBABILITY 1-5",
              "Probability (H/M/L)", "Probability (1-5)")
    )
    impact = _first_level(
        row, ("Impact", "IMPACT 1-5", "Impact (H/M/L)", "Impact (1-5)")
    )
    owner = _first_present(row, ("Risk Owner", "Risk owner", "Owner"))
    source_id = _first_present(row, ("Risk ID", "ID", "S/N"))
    category = _first_present(row, ("Risk Category", "Category"))
    response = _first_present(
        row, ("Response Strategy", "Mitigation Strategy", "Risk Response",
              "Risk Response Strategy", "Mitigation/Contingency Actions",
              "Risk Reponse", "Mitigation Steps", "Response")
    )

    return MappedRisk(
        risk_description=description,
        risk_category=category,
        likelihood=likelihood,
        impact=impact,
        risk_rating=compute_rating(likelihood, impact),
        response_strategy=response,
        risk_owner=owner,
        source_risk_id=source_id,
        source_file_name=source_file,
        department=department,
        project_type=project_type,
    )


def _first_present(row: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in row and row[key]:
            return row[key]
    return ""


def _first_level(row: dict[str, str], keys: tuple[str, ...]) -> str:
    """Find the first present likelihood/probability value, mapped to a level."""
    for key in keys:
        if key not in row or not row[key]:
            continue
        value = row[key]
        if key in ("Likelihood", "Impact"):
            return value
        if key in ("Probability",):
            return map_numeric_to_level(value) or map_hml_to_full(value)
        if key in ("PROBABILITY 1-5", "Probability (1-5)", "IMPACT 1-5", "Impact (1-5)"):
            return map_numeric_to_level(value)
        if key in ("Probability (H/M/L)", "Impact (H/M/L)"):
            return map_hml_to_full(value)
    return ""


def _extract_level_from_parens(value: str) -> str:
    """Extract risk level from formats like 'High (80%)', 'Medium-High', 'CRITICAL'."""
    cleaned = value.strip()
    if not cleaned:
        return ""

    # Extract word before parenthesis: "High (80%)" → "High"
    if "(" in cleaned:
        cleaned = cleaned.split("(")[0].strip()

    # Handle hyphenated: "Medium-High" → "High" (conservative), "Medium-Low" → "Medium"
    if "-" in cleaned:
        parts = cleaned.split("-")
        for p in parts:
            p = p.strip().title()
            if p == "High":
                return "High"
        for p in parts:
            p = p.strip().title()
            if p == "Medium":
                return "Medium"
        return "Medium"

    titled = cleaned.title()
    if titled in ("High", "Medium", "Low", "Critical"):
        return "High" if titled == "Critical" else titled

    return ""
