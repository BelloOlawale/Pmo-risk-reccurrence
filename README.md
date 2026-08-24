# PMO Risk Recurrence Predictor — App

Standalone web application merging the FRD and the PMO Risk Management Document.
See `SPEC.md` for the authoritative build spec.

## Structure

```
backend/   Python + FastAPI (modular monolith)
frontend/  React + TypeScript + Apache ECharts (dashboards)
```

## Backend quickstart

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest
```

## Frontend quickstart

```bash
cd frontend
npm install
npm run dev       # Vite dev server on :5173, proxies /api to :8000
npm run build     # type-check + production build
```

Auth: with `VITE_ENTRA_CLIENT_ID` + `VITE_ENTRA_TENANT_ID` set, the app signs
in via Entra  ID (MSAL). Without them it runs in dev mode with a role/user
switcher in the sidebar (mirrors the backend's header-based dev auth).

## Development conventions

- TDD: write tests first, then implement.
- `src/riskapp/domain/` holds pure, side-effect-free logic (no DB, no HTTP).
- Feedback loops before committing: `pytest`, `ruff check .`, `mypy .`
  (backend); `npm run typecheck` (frontend).
