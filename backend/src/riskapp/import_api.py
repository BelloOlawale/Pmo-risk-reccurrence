"""Admin bulk-import API: upload → field mapping → import.

A two-step flow matching SPEC §8. Step one parses an uploaded register and
returns its detected columns plus a suggested canonical-field mapping. Step two
imports the rows with the confirmed mapping, computing the 3×3 risk rating for
every row and reporting per-row errors.

The parsed upload is held in a small in-memory registry. This is the single
process MVP shape; production can move it to Blob/Redis without changing the
API contract (see issue #13).
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.config import settings
from riskapp.domain.scoring import compute_risk_rating
from riskapp.domain.sla import compute_deadline, deadline_anchor
from riskapp.import_pipeline.field_mapper import (
    classify_response,
    map_hml_to_full,
    map_numeric_to_level,
)

# Canonical field → source header keywords (checked case-insensitively).
CANONICAL_KEYWORDS: dict[str, list[str]] = {
    "risk_description": [
        "risk description", "description of risk", "description",
        "risk title", "risk", "issue",
    ],
    "risk_category": ["risk category", "category"],
    "likelihood": ["likelihood", "probability"],
    "impact": ["impact"],
    "response_strategy": [
        "response strategy", "mitigation strategy", "risk response",
        "risk response strategy",
    ],
    "response_plan": [
        "risk response plan", "mitigation steps",
        "mitigation/contingency actions", "risk reponse", "mitigation",
    ],
    "risk_owner": ["risk owner", "owner"],
    "source_risk_id": ["risk id", "id", "s/n"],
}


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """Return a best-effort mapping from canonical field → detected header."""
    lower = [header.lower().strip() for header in headers]
    mapping: dict[str, str | None] = {}
    for canonical, keywords in CANONICAL_KEYWORDS.items():
        match: str | None = None
        for keyword in keywords:
            for index, candidate in enumerate(lower):
                if candidate == keyword or keyword in candidate:
                    match = headers[index]
                    break
            if match is not None:
                break
        mapping[canonical] = match
    return mapping


def _level(value: str) -> str:
    """Normalize a likelihood/impact value to Low/Medium/High."""
    cleaned = (value or "").strip()
    if not cleaned:
        return "Medium"
    titled = cleaned.title()
    if titled in ("Low", "Medium", "High"):
        return titled
    numeric = map_numeric_to_level(cleaned)
    if numeric:
        return numeric
    hml = map_hml_to_full(cleaned)
    if hml:
        return hml
    return "Medium"


@dataclass
class ImportJob:
    id: str
    project_id: int
    file_name: str
    headers: list[str]
    rows: list[dict[str, str]]


@dataclass(frozen=True)
class ImportRowError:
    row: int
    field: str
    message: str


@dataclass
class ImportReport:
    imported: int = 0
    skipped: int = 0
    errors: list[ImportRowError] = field(default_factory=list)


_REGISTRY: dict[str, ImportJob] = {}
_LOCK = threading.Lock()


def create_import_job(
    project_id: int, file_name: str, rows: list[dict[str, str]], headers: list[str]
) -> ImportJob:
    job = ImportJob(
        id=uuid.uuid4().hex,
        project_id=project_id,
        file_name=file_name,
        headers=headers,
        rows=rows,
    )
    with _LOCK:
        _REGISTRY[job.id] = job
    return job


def get_import_job(job_id: str) -> ImportJob | None:
    with _LOCK:
        return _REGISTRY.get(job_id)


def _cell(row: dict[str, str], mapping: dict[str, str], canonical: str) -> str:
    """Return the value for a canonical field using the confirmed mapping."""
    header = mapping.get(canonical)
    if not header:
        return ""
    return (row.get(header) or "").strip()


def run_import(db: Session, job: ImportJob, mapping: dict[str, str]) -> ImportReport:
    """Import the uploaded rows using the confirmed ``mapping``."""
    project = db.get(models.Project, job.project_id)
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    report = ImportReport()

    # Seed the counter once; rows are un-flushed until commit, so counting per
    # row would collide.
    code_counter = (
        db.scalar(
            select(func.count())
            .select_from(models.Risk)
            .where(models.Risk.risk_code.like("RSK-%"))
        )
        or 0
    )

    for index, row in enumerate(job.rows, start=1):
        description = _cell(row, mapping, "risk_description")
        if not description:
            report.skipped += 1
            report.errors.append(
                ImportRowError(index, "risk_description", "missing description")
            )
            continue

        likelihood = _level(_cell(row, mapping, "likelihood"))
        impact = _level(_cell(row, mapping, "impact"))
        rating = compute_risk_rating(likelihood, impact)
        strategy, plan = classify_response(_cell(row, mapping, "response_strategy"))
        code_counter += 1

        db.add(
            models.Risk(
                project_id=job.project_id,
                risk_code=f"RSK-{code_counter:03d}",
                description=description,
                category=_cell(row, mapping, "risk_category") or None,
                likelihood=likelihood,
                impact=impact,
                risk_rating=rating,
                response_strategy=strategy or None,
                response_plan=plan or None,
                owner_user_id=project.pm_user_id if project else None,
                status="Open",
                source="Custom",
                source_file_name=job.file_name,
                source_risk_id=_cell(row, mapping, "source_risk_id") or None,
                sla_deadline=compute_deadline(
                    rating, deadline_anchor(None, now, settings.tz)
                ),
            )
        )
        report.imported += 1

    db.commit()
    return report
