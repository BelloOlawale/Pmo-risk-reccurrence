"""Seed a few demo risks with active statuses and near-future SLA deadlines.

Gives the dashboards visible SLA countdown / breach states (the historical
import seeds only Closed risks). Idempotent: skips if demo risks already exist.

Run from backend/ (local pgvector Postgres must be up):
    python scripts/seed_demo_risks.py
"""

from __future__ import annotations

import datetime as dt
import sys

from sqlalchemy import select

from riskapp import models, schemas
from riskapp.db import SessionLocal
from riskapp.services import (
    accept_risk,
    acknowledge_risk,
    create_risk,
    get_project,
    transition_risk,
    update_risk,
)

MARKER = "Demo Seed"

# description, category, likelihood, impact, target_status, deadline_offset_hours, acknowledge
DEMO_RISKS: list[tuple[str, str, str, str, str, float, bool]] = [
    (
        "Customer data residency for the new region has not been validated",
        "Compliance",
        "High",
        "High",
        "Open",
        1.5,
        False,
    ),
    (
        "Privileged access review for the legacy admin group is overdue",
        "Security",
        "High",
        "Medium",
        "In Progress",
        20.0,
        False,
    ),
    (
        "Third-party integration rate limits may stall the nightly sync",
        "Technical",
        "Medium",
        "Medium",
        "Open",
        6.0,
        False,
    ),
    (
        "Model drift observed after the last retraining window",
        "Technical",
        "High",
        "High",
        "Escalated",
        -3.0,
        False,
    ),
    (
        "Vendor onboarding paperwork outstanding for Q3 delivery",
        "Operational",
        "Low",
        "Medium",
        "Open",
        72.0,
        False,
    ),
    (
        "Budget variance on the data-platform workstream",
        "Financial",
        "Medium",
        "High",
        "Escalated",
        -26.0,
        False,
    ),
    (
        "Access review completed and signed off with compliance",
        "Compliance",
        "High",
        "High",
        "In Progress",
        5.0,
        True,
    ),
]


def main() -> int:
    db = SessionLocal()
    try:
        project = get_project(db, 1)
        if project is None:
            print("Project 1 not found — run the historical import first.", file=sys.stderr)
            return 1

        existing = db.scalars(
            select(models.Risk).where(
                models.Risk.project_id == project.id,
                models.Risk.subcategory == MARKER,
            )
        ).all()
        if existing:
            print(f"Skipping: {len(existing)} demo risks already seeded on {project.project_code}.")
            return 0

        now = dt.datetime.now(dt.UTC)
        seeded = 0
        for (
            description,
            category,
            likelihood,
            impact,
            target_status,
            offset_hours,
            ack,
        ) in DEMO_RISKS:
            risk = create_risk(
                db,
                schemas.RiskCreate(
                    project_id=project.id,
                    description=description,
                    category=category,
                    subcategory=MARKER,
                    risk_source="Technical",
                    likelihood=likelihood,  # type: ignore[arg-type]
                    impact=impact,  # type: ignore[arg-type]
                    response_strategy="Mitigate",
                    source="Custom",
                ),
            )
            # Suggested -> Open (assigns owner + auto SLA deadline)
            risk = accept_risk(db, risk)
            if target_status != "Open":
                risk = transition_risk(db, risk, target_status)
            # Pin the deadline to a precise near-future / past instant (UTC).
            deadline = now + dt.timedelta(hours=offset_hours)
            update_risk(db, risk, schemas.RiskUpdate(sla_deadline=deadline))
            if ack:
                acknowledge_risk(db, risk)
            seeded += 1
            print(
                f"  {risk.risk_code:>8}  {risk.risk_rating:<6} "
                f"{risk.status:<11} deadline {deadline:%Y-%m-%d %H:%M} UTC"
            )

        print(f"Seeded {seeded} demo risks on {project.project_code}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
