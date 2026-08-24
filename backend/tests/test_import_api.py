"""Tests for the admin bulk-import API (upload → mapping → import)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.import_api import ImportJob, run_import, suggest_mapping
from riskapp.import_pipeline.excel_parser import parse_excel

FIXTURE = Path(__file__).parent / "fixtures" / "punuka_bpa.xlsx"


def _project(db: Session, *, pm_user_id: int | None = None) -> models.Project:
    dept = models.Department(name="Digital Advisory")
    ptype = models.ProjectType(name="Business Process Automation")
    db.add_all([dept, ptype])
    db.flush()
    project = models.Project(
        name="Punuka BPA", project_code="PRJ-UP", status="Active", pm_user_id=pm_user_id
    )
    project.department = dept
    project.project_type = ptype
    db.add(project)
    db.flush()
    db.commit()
    return project


class TestSuggestMapping:
    def test_maps_canonical_fields_to_headers(self) -> None:
        headers = [
            "Risk ID", "Risk Description", "Risk Category",
            "Likelihood", "Impact", "Mitigation Strategy", "Risk Owner",
        ]
        mapping = suggest_mapping(headers)
        assert mapping["source_risk_id"] == "Risk ID"
        assert mapping["risk_description"] == "Risk Description"
        assert mapping["likelihood"] == "Likelihood"
        assert mapping["impact"] == "Impact"
        assert mapping["response_strategy"] == "Mitigation Strategy"

    def test_unknown_fields_are_none(self) -> None:
        mapping = suggest_mapping(["Something", "Else"])
        assert mapping["risk_description"] is None


class TestRunImport:
    def _job(self, project_id: int) -> ImportJob:
        rows = parse_excel(str(FIXTURE))
        return ImportJob(
            id="job-1",
            project_id=project_id,
            file_name="punuka_bpa.xlsx",
            headers=list(rows[0].keys()),
            rows=rows,
        )

    def test_imports_rows_with_computed_rating(self, db_session: Session) -> None:
        project = _project(db_session)
        job = self._job(project.id)
        mapping = suggest_mapping(job.headers)

        report = run_import(db_session, job, mapping)
        assert report.imported > 0
        assert report.skipped == 0

        risks = db_session.scalars(select(models.Risk)).all()
        assert len(risks) == report.imported
        assert all(r.risk_rating in ("Low", "Medium", "High") for r in risks)
        assert all(r.source_file_name == "punuka_bpa.xlsx" for r in risks)

    def test_missing_description_is_reported(self, db_session: Session) -> None:
        project = _project(db_session)
        job = ImportJob(
            id="job-2",
            project_id=project.id,
            file_name="empty.xlsx",
            headers=["Risk ID", "Description"],
            rows=[{"Risk ID": "1", "Description": ""}],
        )
        mapping = {"risk_description": "Description", "source_risk_id": "Risk ID"}
        report = run_import(db_session, job, mapping)
        assert report.imported == 0
        assert report.skipped == 1
        assert report.errors[0].field == "risk_description"


class TestImportApi:
    def test_initiate_and_confirm(self, client: TestClient, db_session: Session) -> None:
        project = _project(db_session)
        data = FIXTURE.read_bytes()

        resp = client.post(
            "/api/imports",
            data={"project_id": str(project.id)},
            files={"file": ("punuka_bpa.xlsx", data)},
            headers={"X-User-Role": "System Admin"},
        )
        assert resp.status_code == 200
        initiated = resp.json()
        assert initiated["columns"]
        assert initiated["suggested_mapping"]["risk_description"] == "Risk Description"

        confirm = client.post(
            f"/api/imports/{initiated['import_id']}/confirm",
            json={"mapping": initiated["suggested_mapping"]},
            headers={"X-User-Role": "System Admin"},
        )
        assert confirm.status_code == 200
        report = confirm.json()
        assert report["imported"] > 0
        assert report["skipped"] == 0

    def test_non_admin_cannot_import(self, client: TestClient, db_session: Session) -> None:
        project = _project(db_session)
        resp = client.post(
            "/api/imports",
            data={"project_id": str(project.id)},
            files={"file": ("x.xlsx", b"")},
            headers={"X-User-Role": "Project Manager"},
        )
        assert resp.status_code == 403
