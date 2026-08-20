# 00: Foundation — Scaffold, Domain Core, Data Model, API Tracer Bullet

- **Type:** AFK
- **Spec:** SPEC.md §2–§5
- **Blocked by:** None
- **Status:** DONE (commit `1c3012e`)

## What was built

- Backend scaffold: Python + FastAPI + SQLAlchemy 2.0 + Alembic (PostgreSQL-ready, SQLite in tests).
- Pure domain core (`src/riskapp/domain/`):
  - `scoring.py` — 3×3 Likelihood × Impact → Risk Rating matrix.
  - `status.py` — lifecycle `Suggested → Open → In Progress → Escalated → Event → Resolved → Closed` (+ Dismissed), valid transitions, "Event → Materialized" label.
  - `sla.py` — 24h/48h/120h deadlines, 4h/12h/24h warnings, activity detection.
- Data model (`models.py`): department, project_type, project, risk, risk_audit_log (append-only), user, practice_lead, setting, suggestion_dismissal.
- Schemas (`schemas.py`) with `Literal`-validated fields; services (`services.py`); FastAPI endpoints (health, departments, project-types, projects, risks).

## Acceptance criteria

- [x] `pytest` green (87 tests)
- [x] `mypy .` strict clean
- [x] `ruff check .` clean
- [x] Alembic initial migration generated and applies (`alembic upgrade head`)
- [x] Project creation auto-generates `PRJ-YYYY-NNN`; risk creation auto-computes rating + `RSK-NNN`
- [x] Git repo initialized and committed
