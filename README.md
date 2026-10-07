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

Auth: the app signs in with an app-managed email + password (backend
`RISKAPP_LOCAL_LOGIN_ENABLED=true`). Set `VITE_AUTH_MODE=dev` in
`frontend/.env` to run locally with a role/user switcher in the sidebar instead
(mirrors the backend's header-based dev auth).

## Development conventions

- TDD: write tests first, then implement.
- `src/riskapp/domain/` holds pure, side-effect-free logic (no DB, no HTTP).
- Feedback loops before committing: `pytest`, `ruff check .`, `mypy .`
  (backend); `npm run typecheck` (frontend).
