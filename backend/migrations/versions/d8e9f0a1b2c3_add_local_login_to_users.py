"""add local email+password login columns to users

Revision ID: d8e9f0a1b2c3
Revises: c7d9e1f2a3b4
Create Date: 2026-09-22 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: str | Sequence[str] | None = 'c7d9e1f2a3b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add app-managed credentials so users can sign in with email + password.

    ``password_hash`` holds a scrypt hash (null = no local login); ``role`` is
    the role a local account is granted. Both stay null for Entra users, whose
    roles come from the token's group claims.
    """
    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('role', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'role')
    op.drop_column('users', 'password_hash')
