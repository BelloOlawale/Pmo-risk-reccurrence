"""add issues table

Revision ID: c7d9e1f2a3b4
Revises: b2c3d4e5f6a7
Create Date: 2026-09-07 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7d9e1f2a3b4'
down_revision: str | Sequence[str] | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the issues table.

    Each Issue is created automatically from a materialized (Event) risk and
    inherits the risk's business fields. The unique ``source_risk_id``
    constraint is the idempotency guard: a risk generates exactly one Issue.
    """
    op.create_table(
        'issues',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('issue_code', sa.String(length=50), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('source_risk_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('subcategory', sa.String(length=100), nullable=True),
        sa.Column('risk_source', sa.String(length=30), nullable=True),
        sa.Column('likelihood', sa.String(length=10), nullable=False),
        sa.Column('impact', sa.String(length=10), nullable=False),
        sa.Column('risk_rating', sa.String(length=10), nullable=False),
        sa.Column('response_strategy', sa.String(length=30), nullable=True),
        sa.Column('response_plan', sa.Text(), nullable=True),
        sa.Column('owner_user_id', sa.Integer(), nullable=True),
        sa.Column('identified_during', sa.String(length=100), nullable=True),
        sa.Column('risk_start_date', sa.Date(), nullable=True),
        sa.Column('risk_end_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name='fk_issues_owner_user_id'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name='fk_issues_project_id'),
        sa.ForeignKeyConstraint(['source_risk_id'], ['risks.id'], name='fk_issues_source_risk_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_risk_id', name='uq_issues_source_risk_id'),
    )
    op.create_index(op.f('ix_issues_issue_code'), 'issues', ['issue_code'], unique=True)
    op.create_index(op.f('ix_issues_project_id'), 'issues', ['project_id'], unique=False)
    op.create_index(op.f('ix_issues_source_risk_id'), 'issues', ['source_risk_id'], unique=False)
    op.create_index(op.f('ix_issues_status'), 'issues', ['status'], unique=False)


def downgrade() -> None:
    """Drop the issues table."""
    op.drop_index(op.f('ix_issues_status'), table_name='issues')
    op.drop_index(op.f('ix_issues_source_risk_id'), table_name='issues')
    op.drop_index(op.f('ix_issues_project_id'), table_name='issues')
    op.drop_index(op.f('ix_issues_issue_code'), table_name='issues')
    op.drop_table('issues')
