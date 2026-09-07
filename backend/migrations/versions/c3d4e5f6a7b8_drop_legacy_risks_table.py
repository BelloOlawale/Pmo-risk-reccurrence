"""drop the obsolete risks table (post-soak cut-over)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-03

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the legacy ``risks`` table after the cut-over has soaked."""
    op.execute("DROP INDEX IF EXISTS ix_risks_embedding")
    op.drop_index(op.f("ix_risks_status"), table_name="risks")
    op.drop_index(op.f("ix_risks_risk_code"), table_name="risks")
    op.drop_index(op.f("ix_risks_project_id"), table_name="risks")
    op.drop_table("risks")


def downgrade() -> None:
    """Best-effort inverse: the dropped table's data is gone, so this recreates
    an empty ``risks`` table with the schema it had before the cut-over."""
    import sqlalchemy as sa  # noqa: PLC0415

    op.create_table(
        "risks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("risk_code", sa.String(length=50), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("subcategory", sa.String(length=100), nullable=True),
        sa.Column("risk_source", sa.String(length=30), nullable=True),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_risks_project_id"), "risks", ["project_id"], unique=False)
    op.create_index(op.f("ix_risks_risk_code"), "risks", ["risk_code"], unique=True)
    op.create_index(op.f("ix_risks_status"), "risks", ["status"], unique=False)
