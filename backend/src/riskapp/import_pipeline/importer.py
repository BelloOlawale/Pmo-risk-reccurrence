"""Historical data import orchestrator.

Walks ``Project/<Department>/<ProjectType>/<file>.xlsx``, reconstructs the
Department / ProjectType / Project hierarchy from the folder layout, and
inserts risks with ``source="Historical"`` plus source traceability.

Idempotent: a project is created once per unique (department, project_type)
pair, and a risk is deduplicated by (project, source_file, source_risk_id).
Risks without a source ID (e.g. the TNL schema) fall back to their description
as the dedup key.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from itertools import count
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.scoring import compute_risk_rating
from riskapp.import_pipeline.excel_parser import parse_excel
from riskapp.import_pipeline.field_mapper import (
    MappedRisk,
    map_generic_row,
    map_issues_log_row,
    map_origin_row,
    map_prowweb_row,
    map_punuka_extended_row,
    map_punuka_row,
    map_seamless_hr_row,
    map_tnl_row,
    map_wacl_row,
    normalize_level,
)
from riskapp.services import get_or_create_department, get_or_create_project_type

# Historical rows are seeded as Closed — they are past learnings, not active.
HISTORICAL_RISK_STATUS = "Closed"
HISTORICAL_RISK_SOURCE = "Historical"

# Source risk IDs are short identifiers ("R1", "BA-001"). Anything sentence-long
# means the header detection mis-aligned a stray row (e.g. section headers or
# notes at the bottom of a sheet); those rows are not real risks and are skipped.
_MAX_SOURCE_ID_LENGTH = 20

_EXCEL_SUFFIXES = (".xlsx", ".xlsm")


class SchemaType(Enum):
    """Known Excel schema types."""

    PUNUKA = auto()
    PUNUKA_EXTENDED = auto()
    WACL = auto()
    TNL = auto()
    SEAMLESS_HR = auto()
    PROWEB = auto()
    ORIGIN = auto()
    ISSUES_LOG = auto()
    GENERIC = auto()


@dataclass
class ImportResult:
    """Counts produced by :func:`import_directory`."""

    files_found: int = 0
    files_parsed: int = 0
    files_skipped: int = 0
    projects_created: int = 0
    risks_imported: int = 0
    risks_skipped: int = 0


def detect_schema(headers: list[str]) -> SchemaType:
    """Detect Excel schema from header row."""
    headers_lower = [h.lower().strip() for h in headers]

    # PROWEB-style: has "RISK" as a column (not "Risk ID" or "Risk Description")
    has_risk_column = "risk" in headers_lower and not any(
        h in ("risk id", "risk description") for h in headers_lower
    )
    if has_risk_column and any("probability" in h for h in headers_lower):
        return SchemaType.PROWEB

    # ORIGIN-style: has "risk title" or "root cause" or "triggers" + "recommended"
    if any("root cause" in h for h in headers_lower) and any(
        "risk title" in h for h in headers_lower
    ):
        return SchemaType.ORIGIN

    # Issues log format: no risk description, has "issue" header
    has_issue_header = any(h == "issue" for h in headers_lower)
    has_risk_desc = any(
        h in headers_lower
        for h in ["risk description", "description of risk", "risk", "description"]
    )
    if has_issue_header and not has_risk_desc:
        return SchemaType.ISSUES_LOG

    # TNL: has "Probability (H/M/L)" or "Impact (H/M/L)"
    if any("(h/m/l)" in h for h in headers_lower):
        return SchemaType.TNL

    # Seamless HR: has "S/N" and "(1-5)" in probability/impact
    if "s/n" in headers_lower and any("(1-5)" in h for h in headers_lower):
        return SchemaType.SEAMLESS_HR

    # WACL: has "ID", "Description of Risk", "Risk Score" / "Risk Level"
    if "id" in headers_lower and "description of risk" in headers_lower:
        return SchemaType.WACL

    # PUNUKA_EXTENDED: has extra fields like "Risk Rating" or "Project Lifecycle Stage"
    if "risk id" in headers_lower and "risk description" in headers_lower:
        has_extended = any(
            kw in h
            for h in headers_lower
            for kw in ["risk rating", "project lifecycle stage", "response strategy"]
        )
        return SchemaType.PUNUKA_EXTENDED if has_extended else SchemaType.PUNUKA

    return SchemaType.GENERIC


def import_directory(db: Session, root_path: str) -> ImportResult:
    """Walk the folder hierarchy and import all historical risks into the DB."""
    root = Path(root_path)
    result = ImportResult()

    year = dt.date.today().year
    project_codes = count(start=_count_project_codes(db, year) + 1)
    risk_codes = count(start=_count_risk_codes(db) + 1)

    def next_project_code() -> str:
        return f"PRJ-{year}-{next(project_codes):03d}"

    def next_risk_code() -> str:
        return f"RSK-{next(risk_codes):03d}"

    for dept_path in sorted(root.iterdir()):
        if not dept_path.is_dir():
            continue
        department_name = dept_path.name

        for pt_path in sorted(dept_path.iterdir()):
            if not pt_path.is_dir():
                continue
            project_type_name = pt_path.name

            project = _get_or_create_project(
                db, department_name, project_type_name, next_project_code, result
            )

            for file_path in sorted(pt_path.iterdir()):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in _EXCEL_SUFFIXES:
                    continue

                result.files_found += 1
                try:
                    rows = parse_excel(str(file_path))
                except Exception:
                    rows = []

                if not rows:
                    result.files_skipped += 1
                    continue

                result.files_parsed += 1
                headers = list(rows[0].keys())
                schema = detect_schema(headers) if headers else SchemaType.GENERIC

                for row in rows:
                    mapped = _map_row(
                        row, schema, department_name, project_type_name, file_path.name
                    )
                    if not mapped or not mapped.get("risk_description"):
                        result.risks_skipped += 1
                        continue

                    source_risk_id = (mapped.get("source_risk_id") or "").strip()
                    if len(source_risk_id) > _MAX_SOURCE_ID_LENGTH:
                        # Mis-aligned stray row (section header / note), not a risk.
                        result.risks_skipped += 1
                        continue

                    if _risk_exists(db, project.id, mapped):
                        result.risks_skipped += 1
                        continue

                    db.add(_build_risk(project.id, mapped, next_risk_code))
                    result.risks_imported += 1

    db.commit()
    return result


def _get_or_create_project(
    db: Session,
    department_name: str,
    project_type_name: str,
    next_project_code: Callable[[], str],
    result: ImportResult,
) -> models.Project:
    department = get_or_create_department(db, department_name)
    project_type = get_or_create_project_type(db, project_type_name)

    existing = db.scalar(
        select(models.Project).where(
            models.Project.department_id == department.id,
            models.Project.project_type_id == project_type.id,
        )
    )
    if existing is not None:
        return existing

    project = models.Project(
        project_code=next_project_code(),
        name=f"{department_name} — {project_type_name}",
        status="Active",
    )
    project.department = department
    project.project_type = project_type
    db.add(project)
    db.flush()
    result.projects_created += 1
    return project


def _risk_exists(db: Session, project_id: int, mapped: MappedRisk) -> bool:
    source_file = mapped.get("source_file_name", "")
    source_risk_id = mapped.get("source_risk_id", "")

    if source_risk_id:
        stmt = select(models.Risk.id).where(
            models.Risk.project_id == project_id,
            models.Risk.source_file_name == source_file,
            models.Risk.source_risk_id == source_risk_id,
        )
    else:
        stmt = select(models.Risk.id).where(
            models.Risk.project_id == project_id,
            models.Risk.source_file_name == source_file,
            models.Risk.source_risk_id.is_(None),
            models.Risk.description == mapped.get("risk_description", ""),
        )

    return db.scalar(stmt) is not None


def _build_risk(
    project_id: int, mapped: MappedRisk, next_risk_code: Callable[[], str]
) -> models.Risk:
    likelihood = normalize_level(mapped.get("likelihood", ""))
    impact = normalize_level(mapped.get("impact", ""))
    rating = compute_risk_rating(likelihood, impact)

    return models.Risk(
        project_id=project_id,
        risk_code=next_risk_code(),
        description=mapped.get("risk_description", ""),
        category=mapped.get("risk_category") or None,
        likelihood=likelihood,
        impact=impact,
        risk_rating=rating,
        response_strategy=mapped.get("response_strategy") or None,
        response_plan=mapped.get("response_plan") or None,
        status=HISTORICAL_RISK_STATUS,
        source=HISTORICAL_RISK_SOURCE,
        source_file_name=mapped.get("source_file_name") or None,
        source_risk_id=mapped.get("source_risk_id") or None,
        identified_during=mapped.get("project_lifecycle_stage") or None,
    )


def _map_row(
    row: dict[str, str],
    schema: SchemaType,
    department: str,
    project_type: str,
    source_file: str,
) -> MappedRisk | None:
    """Dispatch to the appropriate mapper based on schema type."""
    try:
        if schema == SchemaType.PUNUKA:
            return map_punuka_row(row, department, project_type, source_file)
        if schema == SchemaType.PUNUKA_EXTENDED:
            return map_punuka_extended_row(row, department, project_type, source_file)
        if schema == SchemaType.WACL:
            return map_wacl_row(row, department, project_type, source_file)
        if schema == SchemaType.TNL:
            return map_tnl_row(row, department, project_type, source_file)
        if schema == SchemaType.SEAMLESS_HR:
            return map_seamless_hr_row(row, department, project_type, source_file)
        if schema == SchemaType.PROWEB:
            return map_prowweb_row(row, department, project_type, source_file)
        if schema == SchemaType.ORIGIN:
            return map_origin_row(row, department, project_type, source_file)
        if schema == SchemaType.ISSUES_LOG:
            return map_issues_log_row(row, department, project_type, source_file)
        return map_generic_row(row, department, project_type, source_file)
    except Exception:
        return None


def _count_project_codes(db: Session, year: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(models.Project)
            .where(models.Project.project_code.like(f"PRJ-{year}-%"))
        )
        or 0
    )


def _count_risk_codes(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(models.Risk)
            .where(models.Risk.risk_code.like("RSK-%"))
        )
        or 0
    )
