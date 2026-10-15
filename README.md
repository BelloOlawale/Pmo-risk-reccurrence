# PMO Risk Intelligence

Standalone web application merging the FRD and the PMO Risk Management
Document. See `SPEC.md` for the authoritative build spec,
`ARCHITECTURE.md` for the design, and `infra/README.md` for deployment.

Deployed as a single **production** Azure Container Apps environment in UK
South (`int`, resource group `rg-riskapp-int`).

## Structure

```
backend/   Python + FastAPI (modular monolith)
frontend/  React + TypeScript + Apache ECharts (dashboards)
infra/     Azure Container Apps infrastructure (Bicep) + deploy scripts
```

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

## Frontend

```bash
cd frontend
npm install
npm run build     # type-check + production build
npm run typecheck
```

## Authentication

See [`docs/AUTHENTICATION.md`](docs/AUTHENTICATION.md) for the full model.

**Microsoft Entra ID SSO** (MSAL) is the default production sign-in. Set
`VITE_AUTH_MODE=entra` with `VITE_ENTRA_CLIENT_ID` / `VITE_ENTRA_TENANT_ID` for
the SPA, and the matching `RISKAPP_ENTRA_*` values for the API. Roles are
resolved server-side from the Entra `groups` claim.

**App-managed email + password** sign-in is also supported: set
`RISKAPP_LOCAL_LOGIN_ENABLED=true` on the API, build the SPA with
`VITE_AUTH_MODE=password`, and provision accounts with
`python -m riskapp.provision_users --file people.csv`. Passwords are stored as
salted scrypt hashes and can never be read back.

## Development conventions

- TDD: write tests first, then implement.
- `src/riskapp/domain/` holds pure, side-effect-free logic (no DB, no HTTP).
- Feedback loops before committing: `pytest`, `ruff check .`, `mypy src`
  (backend); `npm run typecheck` (frontend).
