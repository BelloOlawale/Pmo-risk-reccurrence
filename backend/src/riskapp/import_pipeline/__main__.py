"""CLI entry for seeding the knowledge base with historical registers.

Usage:
    python -m riskapp.import_pipeline --project-root ../risk_reccurrence_predictor/Project
    python -m riskapp.import_pipeline --project-root Project --dry-run
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from riskapp import models
from riskapp.db import SessionLocal
from riskapp.import_pipeline.importer import ImportResult, import_directory


def _print_result(result: ImportResult) -> None:
    print("Historical data import complete")
    print(f"  Files found:   {result.files_found}")
    print(f"  Files parsed:  {result.files_parsed}")
    print(f"  Files skipped: {result.files_skipped}")
    print(f"  Projects:      {result.projects_created}")
    print(f"  Risks imported:{result.risks_imported}")
    print(f"  Risks skipped: {result.risks_skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed Postgres with historical risk registers.",
    )
    parser.add_argument(
        "--project-root",
        default="Project",
        help="Root folder of Project/<Department>/<ProjectType>/<file>.xlsx",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count without writing to the database",
    )
    args = parser.parse_args()

    root = Path(args.project_root)
    if not root.is_dir():
        raise SystemExit(f"ERROR: project root not found: {root}")

    if args.dry_run:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        models.Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    else:
        session = SessionLocal()

    try:
        result = import_directory(session, str(root))
        _print_result(result)
    finally:
        session.close()


if __name__ == "__main__":
    main()
