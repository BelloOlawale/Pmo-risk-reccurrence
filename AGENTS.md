# AGENTS.md

Project conventions for AI coding agents working on the **PMO Risk Recurrence
Predictor**. This file is auto-loaded at session start; keep it current.

## Issue lifecycle (must follow)

- Work items are markdown files in `Issues/` (e.g. `Issues/20-risk-catalog-write.md`).
- When an issue is **implemented** — acceptance criteria met and tests green — set its
  `Status:` to `DONE` and **move the file into `Issues/done/`**.
- Never delete an issue file. Archiving = moving it to `Issues/done/`.
- Do this at the end of the session that finishes the issue, not later.

## Where to look

- `CONTEXT.md` — domain glossary (Risk vs Project Risk vs Project, Active Risk Register).
- `Issues/17-risk-catalog-instance-prd.md` — parent PRD for the current data-model rebuild.
- `docs/adr/` — architectural decision records.
- Backend: `backend/` (FastAPI + SQLAlchemy + Alembic); tests in `backend/tests/`.
- Frontend: `frontend/` (Vite + React + TypeScript).

## Definition of done

Run from the repo root before marking an issue DONE:

```bash
cd backend && python -m pytest -q && python -m ruff check src tests && python -m mypy src
cd frontend && npm run typecheck
```
