# Deployment

The application runs as four Azure Container Apps in a **single production
environment: `int`** (UK South). See [`infra/README.md`](infra/README.md) for
the full deployment guide and [`infra/RUNBOOK.md`](infra/RUNBOOK.md) for the
"which script do I run" reference.

## 1. Repository layout

```
app/
├── backend/
│   ├── Dockerfile                 # FastAPI web + Celery worker + Celery beat
│   ├── .dockerignore
│   ├── alembic.ini
│   ├── migrations/
│   ├── pyproject.toml
│   └── src/riskapp/
├── frontend/
│   ├── Dockerfile                 # Node build → nginx serve
│   ├── nginx.conf                 # standalone SPA config (proxy commented out)
│   ├── nginx.compose.conf         # Compose config (proxy enabled)
│   ├── nginx.prod.conf.template   # Container Apps config (rendered from $API_UPSTREAM)
│   ├── start-nginx.sh             # renders template when API_UPSTREAM is set
│   └── .dockerignore
├── infra/                         # Azure Container Apps IaC
│   ├── main-complete.bicep        # Full stack: infra + the four apps
│   ├── main.bicep + modules/      # Registry + environment + apps (per-service)
│   ├── deploy.sh / deploy.ps1     # Full deploy: infra → images → apps
│   ├── deploy-service.sh/.ps1     # Per-service deploy (normal releases)
│   ├── generate-deploy-env.sh     # Rebuild deploy.int.env from live Azure
│   ├── register-entra-app.sh      # Entra app registration / SSO keys
│   ├── sync-entra-users.sh        # Import Entra users into the users table
│   └── README.md / RUNBOOK.md     # Full guide / quick deploy reference
├── .github/workflows/
│   ├── ci.yml                     # PR CI (pytest/ruff/mypy, typecheck/build)
│   └── deploy.yml                 # manual Container Apps deploy (workflow_dispatch)
└── docker-compose.yml             # full local stack (developer convenience)
```

## 2. Backend image (`backend/Dockerfile`)

One image, three entrypoints.

| Role | Command |
|---|---|
| web (default) | `alembic upgrade head && uvicorn riskapp.main:app --host 0.0.0.0 --port 8000` |
| worker | `celery -A riskapp.celery_app:celery_app worker --loglevel=INFO` |
| beat | `celery -A riskapp.celery_app:celery_app beat --loglevel=INFO` |

The image includes `alembic.ini` and `migrations/`, so database migrations are
applied when the web app starts.

## 3. Frontend image (`frontend/Dockerfile`)

Multi-stage build:

1. `node:20-alpine` — installs dependencies with `npm ci`, runs `npm run build`.
2. `nginx:1.27-alpine` — serves the built `dist/` bundle with SPA fallback.

`VITE_AUTH_MODE=entra` is baked in at build time for the production SPA (Microsoft
Entra ID SSO). The Container Apps nginx config (`nginx.prod.conf.template`) is
rendered at start-up from `$API_UPSTREAM` and proxies `/api/` to the `web` app.

## 4. Local stack (`docker-compose.yml`)

Developer convenience only — the deployed environment is `int`.

```bash
cd app
docker compose up --build
```

| Service | Image / build | Port | Purpose |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | `5433` | PostgreSQL + pgvector |
| `redis` | `redis:7-alpine` | `6379` | Celery broker / result backend |
| `web` | build `./backend` | `8000` | FastAPI (runs `alembic upgrade head` then uvicorn) |
| `worker` | build `./backend` | — | Celery worker |
| `beat` | build `./backend` | — | Celery beat scheduler |
| `frontend` | build `./frontend` | `8080` | React SPA via nginx, proxies `/api/` to `web` |

After start-up: frontend <http://localhost:8080>, API <http://localhost:8000>,
API docs <http://localhost:8000/docs>.

## 5. Azure deployment (`int`)

```bash
cd app
az login
bash infra/deploy-service.sh int                 # everything
bash infra/deploy-service.sh int --service web   # one service
```

The runtime configuration (`RISKAPP_*`) is read from the process environment,
`infra/deploy.int.env` (git-ignored, generated), or `backend/.env`. See
[`infra/README.md`](infra/README.md) for prerequisites, per-service options and
troubleshooting.

### Safety preflights

`deploy-service.sh` refuses to deploy an API with no database URL or no Entra
tenant, refuses to deploy with app-managed password login enabled (unless
`--allow-local-login` is passed), refuses to build when the host disk is nearly
full, and warns on an uncommitted tree when the image tag is the commit SHA.

## 6. GitHub Actions

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | pull request, push to `main`/`master` | `pytest`, `ruff`, `mypy`; `npm run typecheck`, `npm run build` |
| `deploy.yml` | manual (`workflow_dispatch`) | Deploy `int` via `infra/deploy-service.sh` |

The deploy workflow requires the `AZURE_CREDENTIALS` service principal plus the
`RISKAPP_*` secrets and `VITE_ENTRA_*` build values. Microsoft Entra ID SSO is
the production sign-in method.

## 7. Required configuration

These are read from the environment (or Key Vault references, once wired) and
must never be committed:

```
RISKAPP_DATABASE_URL
RISKAPP_REDIS_URL
RISKAPP_AZURE_OPENAI_ENDPOINT
RISKAPP_AZURE_OPENAI_API_KEY
RISKAPP_AZURE_OPENAI_EMBEDDING_DEPLOYMENT
RISKAPP_AZURE_OPENAI_CHAT_DEPLOYMENT
RISKAPP_AZURE_OPENAI_API_VERSION
RISKAPP_ACS_ENDPOINT
RISKAPP_ACS_ACCESS_KEY
RISKAPP_ACS_SENDER_EMAIL
RISKAPP_BLOB_ACCOUNT_NAME
RISKAPP_BLOB_ACCOUNT_KEY
RISKAPP_BLOB_CONTAINER
RISKAPP_ENTRA_TENANT_ID
RISKAPP_ENTRA_CLIENT_ID
RISKAPP_ENTRA_CLIENT_SECRET
RISKAPP_ENTRA_ROLE_GROUP_IDS
RISKAPP_APP_BASE_URL
RISKAPP_CORS_ORIGINS
RISKAPP_APP_TIMEZONE
RISKAPP_ENVIRONMENT
RISKAPP_LOCAL_LOGIN_SECRET        # token signing secret (acks + local login)
RISKAPP_LOCAL_LOGIN_ENABLED       # true = allow app-managed email + password sign-in
```

## 8. Hardening status

- Secrets are supplied as Container App secrets; `infra/deploy.int.env` is
  git-ignored and never committed.
- The API refuses every request when no Entra tenant is configured, unless the
  explicit test-only `RISKAPP_ALLOW_HEADER_AUTH=true` escape hatch is set.
- Token signing has no built-in fallback key; a secret must be configured.
- Local-account passwords are stored as salted **scrypt** hashes and can never
  be read back; provisioning is documented in
  [`docs/AUTHENTICATION.md`](docs/AUTHENTICATION.md).
- The deploy refuses to enable app-managed password login unless
  `--allow-local-login` is passed deliberately.
- Key Vault purge protection is enabled for the production environment.
