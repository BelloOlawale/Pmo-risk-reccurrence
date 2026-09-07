"""Migration backfill: Risk catalog dedup and Project Risk relationship preservation.

The backfill is pinned migration code that reads the *old* ``risks`` table.
After the cut-over the ORM no longer maps that table, so these tests create it
with raw SQL to exercise the backfill against a simulated pre-migration state.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.backfill import backfill_risk_catalog

_CREATE_RISKS = text(
    """
    CREATE TABLE risks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        risk_code VARCHAR(50) NOT NULL,
        description TEXT NOT NULL,
        category VARCHAR(100),
        subcategory VARCHAR(100),
        risk_source VARCHAR(30),
        likelihood VARCHAR(10) NOT NULL,
        impact VARCHAR(10) NOT NULL,
        risk_rating VARCHAR(10) NOT NULL,
        response_strategy VARCHAR(30),
        response_plan TEXT,
        owner_user_id INTEGER,
        practice_lead_user_id INTEGER,
        status VARCHAR(30) NOT NULL,
        source VARCHAR(30),
        raised_by VARCHAR(255),
        identified_during VARCHAR(100),
        source_file_name VARCHAR(255),
        source_file_url VARCHAR(1000),
        source_risk_id VARCHAR(100),
        llm_analysis TEXT,
        sla_deadline DATETIME,
        sla_acknowledged BOOLEAN NOT NULL DEFAULT 0,
        sla_manual_override BOOLEAN NOT NULL DEFAULT 0,
        risk_start_date DATE,
        risk_end_date DATE,
        accepted_date DATETIME,
        resolved_date DATETIME,
        closed_date DATETIME,
        root_cause TEXT,
        what_worked TEXT,
        resolution_category VARCHAR(100),
        created_at DATETIME,
        updated_at DATETIME
    )
    """
)

_INSERT_RISK = text(
    """
    INSERT INTO risks
        (project_id, risk_code, description, category, likelihood, impact,
         risk_rating, status, created_at, updated_at)
    VALUES
        (:project_id, :risk_code, :description, :category, :likelihood,
         :impact, :risk_rating, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """
)


def _project(db: Session, code: str) -> models.Project:
    department = models.Department(name=f"D-{code}")
    project_type = models.ProjectType(name=f"T-{code}")
    db.add_all([department, project_type])
    db.flush()
    project = models.Project(name=f"P {code}", project_code=code, status="Active")
    project.department = department
    project.project_type = project_type
    db.add(project)
    db.flush()
    return project


def _risk(
    db: Session,
    project: models.Project,
    code: str,
    description: str,
    category: str | None,
) -> None:
    db.execute(
        _INSERT_RISK,
        {
            "project_id": project.id,
            "risk_code": code,
            "description": description,
            "category": category,
            "likelihood": "High",
            "impact": "High",
            "risk_rating": "High",
            "status": "Closed",
        },
    )


def _catalog_count(db: Session) -> int:
    return int(db.scalar(text("SELECT COUNT(*) FROM risk_catalog")) or 0)


def _instance_count(db: Session) -> int:
    return int(db.scalar(text("SELECT COUNT(*) FROM project_risks")) or 0)


def _seed_legacy_risks_table(db: Session) -> None:
    db.execute(_CREATE_RISKS)


def test_backfill_deduplicates_catalog_and_preserves_relationships(
    db_session: Session,
) -> None:
    _seed_legacy_risks_table(db_session)
    p1 = _project(db_session, "PRJ-1")
    p2 = _project(db_session, "PRJ-2")

    # Two projects share the same risk concept; one project has a distinct risk.
    _risk(db_session, p1, "RSK-1", "Vendor onboarding overdue", "Operational")
    _risk(db_session, p2, "RSK-2", "Vendor onboarding overdue", "Operational")
    _risk(db_session, p1, "RSK-3", "Budget variance", "Financial")
    db_session.commit()

    backfill_risk_catalog(db_session.connection())
    db_session.commit()

    # Deduplicated catalog: 2 concepts, not 3 rows.
    assert _catalog_count(db_session) == 2
    # Every old project↔risk pairing preserved as a Project Risk row.
    assert _instance_count(db_session) == 3

    # The shared concept links both Project Risks to the same catalog entry.
    shared_ids = db_session.scalars(
        text(
            "SELECT pr.risk_id FROM project_risks pr "
            "JOIN risk_catalog c ON c.id = pr.risk_id "
            "WHERE c.description = 'Vendor onboarding overdue'"
        )
    ).all()
    assert len(shared_ids) == 2
    assert shared_ids[0] == shared_ids[1]

    # Project association preserved: project 1 has 2 risks, project 2 has 1.
    p1_count = db_session.scalar(
        text("SELECT COUNT(*) FROM project_risks WHERE project_id = :pid"),
        {"pid": p1.id},
    )
    p2_count = db_session.scalar(
        text("SELECT COUNT(*) FROM project_risks WHERE project_id = :pid"),
        {"pid": p2.id},
    )
    assert p1_count == 2
    assert p2_count == 1


def test_backfill_normalizes_description_and_category_for_dedup(
    db_session: Session,
) -> None:
    _seed_legacy_risks_table(db_session)
    p1 = _project(db_session, "PRJ-1")
    p2 = _project(db_session, "PRJ-2")

    # Same concept written with different case/whitespace and category case.
    _risk(db_session, p1, "RSK-1", "Vendor onboarding overdue", "Operational")
    _risk(db_session, p2, "RSK-2", "  vendor onboarding overdue  ", "operational")
    db_session.commit()

    backfill_risk_catalog(db_session.connection())
    db_session.commit()

    assert _catalog_count(db_session) == 1
    assert _instance_count(db_session) == 2


def test_backfill_is_idempotent_after_old_table_is_cleared(db_session: Session) -> None:
    """The backfill only depends on ``risks``; running it on empty input is a no-op."""
    _seed_legacy_risks_table(db_session)
    backfill_risk_catalog(db_session.connection())
    db_session.commit()

    assert _catalog_count(db_session) == 0
    assert _instance_count(db_session) == 0
