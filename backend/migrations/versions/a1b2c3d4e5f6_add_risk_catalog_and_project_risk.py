"""add risk catalog and project risk

Revision ID: a1b2c3d4e5f6
Revises: 5b9c1a2d3e4f
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from riskapp.backfill import backfill_risk_catalog

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "5b9c1a2d3e4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the shared Risk catalog and Project Risk instance, then backfill."""
    op.create_table(
        "risk_catalog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("subcategory", sa.String(length=100), nullable=True),
        sa.Column("risk_source", sa.String(length=30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "project_risks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("risk_id", sa.Integer(), nullable=False),
        sa.Column("likelihood", sa.String(length=10), nullable=False),
        sa.Column("impact", sa.String(length=10), nullable=False),
        sa.Column("risk_rating", sa.String(length=10), nullable=False),
        sa.Column("response_strategy", sa.String(length=30), nullable=True),
        sa.Column("response_plan", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("practice_lead_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=True),
        sa.Column("raised_by", sa.String(length=255), nullable=True),
        sa.Column("identified_during", sa.String(length=100), nullable=True),
        sa.Column("source_file_name", sa.String(length=255), nullable=True),
        sa.Column("source_file_url", sa.String(length=1000), nullable=True),
        sa.Column("source_risk_id", sa.String(length=100), nullable=True),
        sa.Column("llm_analysis", sa.Text(), nullable=True),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_acknowledged", sa.Boolean(), nullable=False),
        sa.Column("sla_manual_override", sa.Boolean(), nullable=False),
        sa.Column("risk_start_date", sa.Date(), nullable=True),
        sa.Column("risk_end_date", sa.Date(), nullable=True),
        sa.Column("accepted_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("what_worked", sa.Text(), nullable=True),
        sa.Column("resolution_category", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["practice_lead_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["risk_id"], ["risk_catalog.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_project_risks_project_id"), "project_risks", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_project_risks_risk_id"), "project_risks", ["risk_id"], unique=False
    )
    op.create_index(op.f("ix_project_risks_status"), "project_risks", ["status"], unique=False)

    backfill_risk_catalog(op.get_bind())


def downgrade() -> None:
    """Drop the two new tables (the old ``risks`` table is untouched)."""
    op.drop_index(op.f("ix_project_risks_status"), table_name="project_risks")
    op.drop_index(op.f("ix_project_risks_risk_id"), table_name="project_risks")
    op.drop_index(op.f("ix_project_risks_project_id"), table_name="project_risks")
    op.drop_table("project_risks")
    op.drop_table("risk_catalog")
