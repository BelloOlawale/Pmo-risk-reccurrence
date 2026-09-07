"""Data-migration backfill for the Risk catalog and Project Risk entities.

This is the frozen helper used by the Alembic migration that introduces the
shared Risk catalog and the Project Risk instance. It references the *old*
``risks`` table as it existed at that migration revision, so treat it as pinned
migration code — do not edit the SQL in ways that would change its behaviour for
a historical revision.

The catalog is deduplicated by normalized description + category (one entry per
risk concept), and each existing project↔risk pairing becomes a Project Risk row.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

_CATALOG_INSERT = text(
    """
    INSERT INTO risk_catalog
        (name, description, category, subcategory, risk_source, created_at, updated_at)
    SELECT
        NULL,
        MIN(description),
        MIN(category),
        MIN(subcategory),
        MIN(risk_source),
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    FROM risks
    GROUP BY lower(trim(description)), lower(trim(coalesce(category, '')))
    """
)

_INSTANCE_INSERT = text(
    """
    INSERT INTO project_risks
        (project_id, risk_id, likelihood, impact, risk_rating,
         response_strategy, response_plan, owner_user_id, practice_lead_user_id,
         status, source, raised_by, identified_during,
         source_file_name, source_file_url, source_risk_id, llm_analysis,
         sla_deadline, sla_acknowledged, sla_manual_override,
         risk_start_date, risk_end_date, accepted_date, resolved_date, closed_date,
         root_cause, what_worked, resolution_category, created_at, updated_at)
    SELECT
        r.project_id, c.id, r.likelihood, r.impact, r.risk_rating,
        r.response_strategy, r.response_plan, r.owner_user_id, r.practice_lead_user_id,
        r.status, r.source, r.raised_by, r.identified_during,
        r.source_file_name, r.source_file_url, r.source_risk_id, r.llm_analysis,
        r.sla_deadline, r.sla_acknowledged, r.sla_manual_override,
        r.risk_start_date, r.risk_end_date, r.accepted_date, r.resolved_date, r.closed_date,
        r.root_cause, r.what_worked, r.resolution_category, r.created_at, r.updated_at
    FROM risks r
    JOIN risk_catalog c
      ON lower(trim(c.description)) = lower(trim(r.description))
     AND lower(trim(coalesce(c.category, ''))) = lower(trim(coalesce(r.category, '')))
    """
)


def backfill_risk_catalog(connection: Connection) -> None:
    """Populate ``risk_catalog`` and ``project_risks`` from the old ``risks`` table."""
    connection.execute(_CATALOG_INSERT)
    connection.execute(_INSTANCE_INSERT)
