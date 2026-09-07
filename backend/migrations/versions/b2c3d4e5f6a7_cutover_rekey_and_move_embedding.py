"""cut over: re-key audit to project risks and move embedding to catalog

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Move the semantic embedding onto the catalog and re-key the audit log."""
    # 1. Embedding moves to the shared catalog (deduplicated by concept).
    op.add_column("risk_catalog", sa.Column("embedding", Vector(1536), nullable=True))
    op.execute(
        """
        UPDATE risk_catalog c
        SET embedding = (
            SELECT r.embedding FROM risks r
            WHERE lower(trim(r.description)) = lower(trim(c.description))
              AND lower(trim(coalesce(r.category, ''))) =
                  lower(trim(coalesce(c.category, '')))
              AND r.embedding IS NOT NULL
            LIMIT 1
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_risk_catalog_embedding ON risk_catalog "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # 2. Re-key audit history and notifications from risks.id to project_risks.id.
    # Best-effort data mapping via per-source traceability, which both tables carry.
    op.execute(
        """
        UPDATE risk_audit_log a
        SET risk_id = pr.id
        FROM risks r
        JOIN project_risks pr
          ON pr.project_id = r.project_id
         AND pr.source_file_name IS NOT DISTINCT FROM r.source_file_name
         AND pr.source_risk_id IS NOT DISTINCT FROM r.source_risk_id
        WHERE a.risk_id = r.id
        """
    )
    op.execute(
        """
        UPDATE notifications n
        SET risk_id = pr.id
        FROM risks r
        JOIN project_risks pr
          ON pr.project_id = r.project_id
         AND pr.source_file_name IS NOT DISTINCT FROM r.source_file_name
         AND pr.source_risk_id IS NOT DISTINCT FROM r.source_risk_id
        WHERE n.risk_id = r.id
        """
    )

    # 3. Repoint the foreign keys at project_risks.
    op.drop_constraint("risk_audit_log_risk_id_fkey", "risk_audit_log", type_="foreignkey")
    op.drop_constraint("notifications_risk_id_fkey", "notifications", type_="foreignkey")
    op.create_foreign_key(
        "risk_audit_log_risk_id_fkey", "risk_audit_log", "project_risks",
        ["risk_id"], ["id"],
    )
    op.create_foreign_key(
        "notifications_risk_id_fkey", "notifications", "project_risks",
        ["risk_id"], ["id"],
    )


def downgrade() -> None:
    """Reverse: point FKs back at risks and move the embedding back."""
    op.drop_constraint("risk_audit_log_risk_id_fkey", "risk_audit_log", type_="foreignkey")
    op.drop_constraint("notifications_risk_id_fkey", "notifications", type_="foreignkey")
    op.create_foreign_key(
        "risk_audit_log_risk_id_fkey", "risk_audit_log", "risks",
        ["risk_id"], ["id"],
    )
    op.create_foreign_key(
        "notifications_risk_id_fkey", "notifications", "risks",
        ["risk_id"], ["id"],
    )
    op.execute("DROP INDEX IF EXISTS ix_risk_catalog_embedding")
    op.drop_column("risk_catalog", "embedding")
