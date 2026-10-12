"""add last_reminder_on to risks

Tracks the last business day on which a daily acknowledgement reminder was sent
for a risk, so the reminder job stays idempotent within a day.

Revision ID: c1d2e3f4a5b6
Revises: b4c5d6e7f8a9
Create Date: 2026-10-08 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: str | Sequence[str] | None = 'b4c5d6e7f8a9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the per-risk reminder dedupe date."""
    op.add_column('risks', sa.Column('last_reminder_on', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('risks', 'last_reminder_on')
