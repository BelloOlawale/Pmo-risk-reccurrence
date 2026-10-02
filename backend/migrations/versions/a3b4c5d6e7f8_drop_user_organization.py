"""drop the unused users.organization column

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-10-02 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the organization field from the external-owner workflow.

    External owners are captured with only a name and an email; the column was
    never used by internal directory sync, so it is safe to drop.
    """
    op.drop_column("users", "organization")


def downgrade() -> None:
    op.add_column("users", sa.Column("organization", sa.String(length=200), nullable=True))
