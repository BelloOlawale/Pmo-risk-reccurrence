"""add project created_source and correct seeded statuses

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6a
Create Date: 2026-09-01 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: str | Sequence[str] | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Introduce project provenance and move seeded projects out of Active.

    ``created_source`` records whether a project entered the system via the
    historical import ("Historical") or through the application's Create
    Project workflow ("User"). The historical import never assigned a PM,
    customer or start date, and names imported projects as
    ``"{department} — {project type}"`` — that is the seed definition used
    here to correct the one-time backfill without touching user-created
    projects.
    """
    op.add_column(
        'projects',
        sa.Column(
            'created_source',
            sa.String(length=30),
            nullable=False,
            server_default='User',
        ),
    )

    # Seeded projects are not active work: they stay available for history but
    # must not satisfy the Active Risk Register filter.
    op.execute(
        "UPDATE projects "
        "SET created_source = 'Historical', status = 'Closed' "
        "WHERE pm_user_id IS NULL "
        "AND customer IS NULL "
        "AND start_date IS NULL "
        "AND name LIKE '% — %'"
    )


def downgrade() -> None:
    op.drop_column('projects', 'created_source')
