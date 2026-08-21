"""Tests for the importer — walk → parse → detect → map → insert."""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.import_pipeline.importer import (
    SchemaType,
    detect_schema,
    import_directory,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestDetectSchema:
    def test_detects_punuka(self) -> None:
        headers = ["Risk ID", "Risk Description", "Risk Category",
                   "Likelihood", "Impact", "Mitigation Strategy", "Risk Owner"]
        assert detect_schema(headers) == SchemaType.PUNUKA

    def test_detects_punuka_extended(self) -> None:
        headers = ["Risk ID", "Risk Description", "Risk Category", "Likelihood",
                   "Impact", "Risk Rating", "Project Lifecycle Stage",
                   "Response Strategy", "Risk Response Plan", "Risk Owner", "Status"]
        assert detect_schema(headers) == SchemaType.PUNUKA_EXTENDED

    def test_detects_wacl(self) -> None:
        headers = ["ID", "Description of Risk", "Probability", "Impact",
                   "Risk Score", "Implication", "Risk Reponse", "Risk Level",
                   "Risk owner", "Notes"]
        assert detect_schema(headers) == SchemaType.WACL

    def test_detects_tnl(self) -> None:
        headers = ["Risk Description", "Probability (H/M/L)",
                   "Impact (H/M/L)", "Impact On", "Owner", "Mitigation Steps"]
        assert detect_schema(headers) == SchemaType.TNL

    def test_detects_seamless_hr(self) -> None:
        headers = ["S/N", "Risk Description", "Impact (1-5)",
                   "Probability (1-5)", "Rating (P X I)", "Owner", "Risk Response"]
        assert detect_schema(headers) == SchemaType.SEAMLESS_HR

    def test_detects_prowweb(self) -> None:
        headers = ["ID", "PLC", "Date (mm/dd/yyyy)", "RISK",
                   "MATERIALIZED RISK?", "PROBABILITY 1-5", "IMPACT 1-5", "PI SCORE"]
        assert detect_schema(headers) == SchemaType.PROWEB

    def test_detects_delifrost(self) -> None:
        headers = ["Risk ID", "Risk", "Risk Description", "Likelihood", "Impact",
                   "Risk Rating (Likelihood x Impact)", "Mitigation Strategy",
                   "Risk Owner", "Stakeholder Owner", "Triggers/Indicators",
                   "Contingency Plan", "Residual Risk", "Status"]
        assert detect_schema(headers) == SchemaType.PUNUKA_EXTENDED

    def test_detects_origin(self) -> None:
        headers = ["Risk ID", "Risk Title", "Category", "Description",
                   "Root Cause", "Probability", "Impact", "Risk Score",
                   "Risk Level", "Triggers", "Risk Owner", "Response Strategy",
                   "Recommended Actions", "Recommended Contingency", "Status"]
        assert detect_schema(headers) == SchemaType.ORIGIN

    def test_detects_issues_log(self) -> None:
        headers = ["ID", "PLC", "Risk ID", "Issue", "Status"]
        assert detect_schema(headers) == SchemaType.ISSUES_LOG

    def test_fallback_returns_generic(self) -> None:
        assert detect_schema(["Some Column", "Another Column", "Foo"]) == SchemaType.GENERIC


def _build_hierarchy(tmp_path: Path) -> Path:
    """Create a Project/<Dept>/<ProjType>/ hierarchy from the fixture files."""
    file_map = {
        "punuka_bpa.xlsx": ("BUSINESS SOLUTIONS", "Business Process Automation"),
        "wacl_bpa.xlsx": ("BUSINESS SOLUTIONS", "Business Process Automation"),
        "tnl_erp.xlsx": ("BUSINESS SOLUTIONS", "ERP Implementation"),
        "seamless_hr_ai.xlsx": ("BUSINESS SOLUTIONS", "AI Integration"),
    }
    for filename, (dept, pt) in file_map.items():
        dest = tmp_path / dept / pt
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES_DIR / filename, dest / filename)
    return tmp_path


class TestImportDirectory:
    def test_imports_all_files_from_fixtures(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        result = import_directory(db_session, str(_build_hierarchy(tmp_path)))

        # 3 unique (dept, project_type) pairs → 3 projects
        assert result.projects_created == 3
        # 12 + 7 + 5 + 4 = 28 risks
        assert result.risks_imported == 28
        assert result.files_parsed == 4
        assert result.files_skipped == 0

        # Departments and project types reconstructed from the folder hierarchy.
        departments = set(db_session.scalars(select(models.Department.name)).all())
        assert departments == {"BUSINESS SOLUTIONS"}
        project_types = set(db_session.scalars(select(models.ProjectType.name)).all())
        assert project_types == {
            "Business Process Automation",
            "ERP Implementation",
            "AI Integration",
        }

        # Every risk carries source traceability and a valid matrix rating.
        risks = db_session.scalars(select(models.Risk)).all()
        assert len(risks) == 28
        for risk in risks:
            assert risk.project_id is not None
            assert risk.source_file_name
            assert risk.status == "Closed"
            assert risk.source == "Historical"
            assert risk.likelihood in ("Low", "Medium", "High")
            assert risk.impact in ("Low", "Medium", "High")
            assert risk.risk_rating in ("Low", "Medium", "High")

        # Ratings follow the 3×3 matrix.
        for risk in risks:
            from riskapp.domain.scoring import compute_risk_rating

            assert risk.risk_rating == compute_risk_rating(risk.likelihood, risk.impact)

    def test_idempotent_rerun_does_not_duplicate(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        root = _build_hierarchy(tmp_path)

        first = import_directory(db_session, str(root))
        second = import_directory(db_session, str(root))

        assert first.projects_created == 3
        assert first.risks_imported == 28

        # Re-running finds the same projects/risks and creates nothing new.
        assert second.projects_created == 0
        assert second.risks_imported == 0

        project_count = db_session.scalar(
            select(func.count()).select_from(models.Project)
        )
        risk_count = db_session.scalar(select(func.count()).select_from(models.Risk))
        assert project_count == 3
        assert risk_count == 28

    def test_skips_ole2_and_corrupt_files_without_crashing(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        root = _build_hierarchy(tmp_path)
        corrupt_dir = tmp_path / "BUSINESS SOLUTIONS" / "Business Process Automation"
        (corrupt_dir / "corrupt.xlsx").write_bytes(
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100
        )

        result = import_directory(db_session, str(root))

        # The corrupt file is found but skipped; the other 4 still import.
        assert result.files_found == 5
        assert result.files_parsed == 4
        assert result.files_skipped == 1
        assert result.risks_imported == 28

    def test_ignores_non_excel_files(self, db_session: Session, tmp_path: Path) -> None:
        root = _build_hierarchy(tmp_path)
        notes = tmp_path / "BUSINESS SOLUTIONS" / "Business Process Automation" / "notes.pdf"
        notes.write_text("x")

        result = import_directory(db_session, str(root))
        assert result.files_found == 4  # the .pdf is not counted
        assert result.risks_imported == 28

    def test_project_name_from_hierarchy(self, db_session: Session, tmp_path: Path) -> None:
        import_directory(db_session, str(_build_hierarchy(tmp_path)))
        projects = db_session.scalars(select(models.Project)).all()
        names = {p.name for p in projects}
        assert "BUSINESS SOLUTIONS — Business Process Automation" in names
        assert "BUSINESS SOLUTIONS — ERP Implementation" in names
