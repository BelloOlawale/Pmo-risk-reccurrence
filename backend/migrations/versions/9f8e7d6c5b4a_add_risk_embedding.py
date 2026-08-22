"""add risk embedding vector column

Revision ID: 9f8e7d6c5b4a
Revises: 03d3f62cdf07
Create Date: 2026-08-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '9f8e7d6c5b4a'
down_revision: str | Sequence[str] | None = '03d3f62cdf07'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the pgvector column and cosine-distance HNSW index."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column('risks', sa.Column('embedding', Vector(1536), nullable=True))
    op.execute(
        "CREATE INDEX ix_risks_embedding ON risks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Drop the index and column (leave the shared extension in place)."""
    op.execute("DROP INDEX IF EXISTS ix_risks_embedding")
    op.drop_column('risks', 'embedding')
