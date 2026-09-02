"""add project status lifecycle

Revision ID: a1b2c3d4e5f6
Revises: 5b9c1a2d3e4f
Create Date: 2026-09-01 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = '5b9c1a2d3e4f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add project closure tracking.

    ``projects.status`` already existed as the project lifecycle field
    (``Active`` / ``Closed``); this migration records when/by whom a project
    was closed and guarantees every existing project has a valid status.
    """
    op.add_column(
        'projects',
        sa.Column('closed_date', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'projects',
        sa.Column('closed_by_user_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f('fk_projects_closed_by_user_id_users'),
        'projects',
        'users',
        ['closed_by_user_id'],
        ['id'],
    )

    # ``projects.status`` is NOT NULL, so no blanket status backfill is needed.
    # Status classification for seeded vs user-created projects is handled by
    # the ``b2c3d4e5f6a7`` migration using explicit provenance.


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_projects_closed_by_user_id_users'),
        'projects',
        type_='foreignkey',
    )
    op.drop_column('projects', 'closed_by_user_id')
    op.drop_column('projects', 'closed_date')
