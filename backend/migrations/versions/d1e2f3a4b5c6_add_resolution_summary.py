"""add resolution summary to risks

Adds the Risk Owner's Resolution Summary (mandatory before a risk may be
submitted for resolution) plus the submitting user and timestamp. Earlier
submissions are preserved in the append-only ``risk_audit_log``.

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-10-14 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: str | Sequence[str] | None = 'c1d2e3f4a5b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the Resolution Summary and its submission metadata."""
    op.add_column('risks', sa.Column('resolution_summary', sa.Text(), nullable=True))
    op.add_column(
        'risks',
        sa.Column('resolution_submitted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'risks', sa.Column('resolution_submitted_by_user_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_risks_resolution_submitted_by_user_id_users',
        'risks',
        'users',
        ['resolution_submitted_by_user_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_risks_resolution_submitted_by_user_id_users', 'risks', type_='foreignkey'
    )
    op.drop_column('risks', 'resolution_submitted_by_user_id')
    op.drop_column('risks', 'resolution_submitted_at')
    op.drop_column('risks', 'resolution_summary')
