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

Pass ``--verify`` to compare row counts between the two databases without
copying anything (useful before and after a cutover).
"""

from __future__ import annotations

import os
import sys
from typing import Any

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


def _compare(source: Engine, target: Engine, tables: list[Any]) -> int:
    """Print source/target row counts; return non-zero if any differ."""
    print(f"{'table':<28} {'source':>8} {'target':>8}")
    mismatches = []
    for table in tables:
        src_count = _count_rows(source, table.name)
        dst_count = _count_rows(target, table.name)
        flag = "" if src_count == dst_count else "  <-- MISMATCH"
        print(f"{table.name:<28} {src_count:>8} {dst_count:>8}{flag}")
        if src_count != dst_count:
            mismatches.append(table.name)
    if mismatches:
        print(f"error: row-count mismatch: {', '.join(mismatches)}", file=sys.stderr)
        return 1
    print("Row counts match.")
    return 0


def main() -> int:
    verify_only = "--verify" in sys.argv[1:]
    source = create_engine(_require_env("SOURCE_DATABASE_URL"), future=True)
    target = create_engine(_require_env("TARGET_DATABASE_URL"), future=True)

    tables = list(Base.metadata.sorted_tables)

    if verify_only:
        return _compare(source, target, tables)

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

    # Final sanity check: row counts must match on both sides.
    return _compare(source, target, tables)


if __name__ == "__main__":
    raise SystemExit(main())
 