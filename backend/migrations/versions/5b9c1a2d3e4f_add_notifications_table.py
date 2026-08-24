"""add notifications table

Revision ID: 5b9c1a2d3e4f
Revises: 9f8e7d6c5b4a
Create Date: 2026-08-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b9c1a2d3e4f"
down_revision: str | Sequence[str] | None = "9f8e7d6c5b4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("risk_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["risk_id"], ["risks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notifications_recipient_user_id"),
        "notifications",
        ["recipient_user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_notifications_risk_id"), "notifications", ["risk_id"], unique=False)
    op.create_index(
        op.f("ix_notifications_project_id"), "notifications", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_project_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_risk_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_recipient_user_id"), table_name="notifications")
    op.drop_table("notifications")
