"""add external risk owners and acknowledgement timestamp

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-30 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add external-owner classification to ``users`` and the ack timestamp to ``risks``.

    External owners are ordinary ``users`` rows flagged ``owner_type='External'``
    so the existing ``risks.owner_user_id`` foreign key, SLA/escalation logic and
    notifications all keep working unchanged. ``acknowledged_at`` records when
    the owner (internal or external) acknowledged the risk.
    """
    op.add_column(
        "users",
        sa.Column(
            "owner_type",
            sa.String(length=20),
            nullable=False,
            server_default="Internal",
        ),
    )
    op.add_column("users", sa.Column("organization", sa.String(length=200), nullable=True))
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "risks",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("risks", "acknowledged_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "organization")
    op.drop_column("users", "owner_type")
