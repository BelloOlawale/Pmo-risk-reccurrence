"""Copy every application table between two PostgreSQL databases.

Used by ``infra/move-postgres-region.sh`` to relocate the database to the same
region as the app. The target schema must already exist (run ``alembic upgrade
head`` against it first) and be empty.

Approach: copy the app's own SQLAlchemy tables in foreign-key dependency order,
then reset each identity sequence to ``MAX(id)`` so subsequent inserts don't
collide with the copied primary keys. This avoids depending on ``pg_dump``
being installed and keeps type handling (JSON, pgvector) consistent with the
application models.

Configuration is read from the environment so secrets never appear in argv:

    SOURCE_DATABASE_URL=postgresql+psycopg://... \
    TARGET_DATABASE_URL=postgresql+psycopg://... \
    PYTHONPATH=backend/src python infra/copy_postgres.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine

from riskapp.models import Base


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"error: {name} is required", file=sys.stderr)
        raise SystemExit(2)
    return value


def _count_rows(engine: Engine, table_name: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one())


def main() -> int:
    source = create_engine(_require_env("SOURCE_DATABASE_URL"), future=True)
    target = create_engine(_require_env("TARGET_DATABASE_URL"), future=True)

    tables = list(Base.metadata.sorted_tables)

    # Refuse to append into a database that already has rows: re-running against
    # a populated target would duplicate data or violate keys. The target must
    # be a freshly migrated (empty) schema.
    populated = [table.name for table in tables if _count_rows(target, table.name) > 0]
    if populated:
        print(
            "error: target already contains rows in: " + ", ".join(populated),
            file=sys.stderr,
        )
        print("       recreate the target schema (alembic upgrade head) first.", file=sys.stderr)
        return 1

    print(f"Copying {len(tables)} tables in dependency order...")

    with source.connect() as src, target.begin() as dst:
        for table in tables:
            rows = [dict(row._mapping) for row in src.execute(select(table))]
            if rows:
                dst.execute(table.insert(), rows)
            print(f"  {table.name:<28} {len(rows):>6} rows")

        # Reset identity sequences so the app can keep inserting after the copy.
        if dst.dialect.name == "postgresql":
            for table in tables:
                pk = list(table.primary_key.columns)
                if len(pk) == 1 and pk[0].name == "id":
                    dst.execute(
                        text(
                            "SELECT setval(pg_get_serial_sequence(:t, 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM {table.name}), 1))"
                        ),
                        {"t": table.name},
                    )

    # Sanity check: row counts must match on both sides.
    mismatches = [
        table.name
        for table in tables
        if _count_rows(source, table.name) != _count_rows(target, table.name)
    ]
    if mismatches:
        print(f"error: row-count mismatch after copy: {', '.join(mismatches)}", file=sys.stderr)
        return 1

    print("Copy complete; row counts match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
