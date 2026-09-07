# Deployment & Local Containerization

This document covers the Docker artifacts and local full-stack setup for the
PMO Risk Recurrence Predictor. It corresponds to `Issues/13-deployment-cicd.md`.

> Status:
> - **Dockerfiles + local Docker Compose implemented.**
> - **GitHub Actions PR CI implemented** (`.github/workflows/ci.yml`).
> - **Azure provisioning drafted** — Bicep templates + deploy scripts under
>   `infra/` (ACR, Container Apps environment, web/worker/beat/frontend apps)
>   and a `workflow_dispatch` deploy workflow (`.github/workflows/deploy.yml`).
>   See [`infra/README.md`](infra/README.md) for usage.
> - Azure provisioning is still pending execution (needs an Azure login with
>   Contributor on the target subscription — see [Next steps](#next-steps)).

---

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
│   ├── start-nginx.sh            # renders template when API_UPSTREAM is set
│   └── .dockerignore
├── infra/                         # Azure Container Apps IaC (issue #13)
│   ├── main.bicep + modules/      # ACR, environment, container apps
│   ├── deploy.sh / deploy.ps1     # staged deploy: infra → images → apps
│   ├── make_params.py             # builds deployment parameters from env / .env
│   └── README.md
├── .github/workflows/
│   ├── ci.yml                     # PR CI (pytest/ruff/mypy, typecheck/build)
│   └── deploy.yml                 # manual Container Apps deploy (workflow_dispatch)
└── docker-compose.yml             # full local stack
```

---

## 2. Backend image (`backend/Dockerfile`)

One image, three entrypoints.

| Role | Command |
|---|---|
| web (default) | `uvicorn riskapp.main:app --host 0.0.0.0 --port 8000` |
| worker | `celery -A riskapp.celery_app:celery_app worker --loglevel=INFO` |
| beat | `celery -A riskapp.celery_app:celery_app beat --loglevel=INFO` |

The image includes `alembic.ini` and `migrations/`, so database migrations can be
applied at deploy time with:

```bash
alembic upgrade head
```

### Build / run the backend image directly

```powershell
cd app/backend
docker build -t riskapp-backend .

# Web
docker run --rm -p 8000:8000 --env-file .env riskapp-backend

# Worker
docker run --rm --env-file .env riskapp-backend `
  celery -A riskapp.celery_app:celery_app worker --loglevel=INFO

# Beat
docker run --rm --env-file .env riskapp-backend `
  celery -A riskapp.celery_app:celery_app beat --loglevel=INFO
```

---

## 3. Frontend image (`frontend/Dockerfile`)

Multi-stage build:

1. `node:20-alpine` — installs dependencies with `npm ci`, runs `npm run build`.
2. `nginx:1.27-alpine` — serves the built `dist/` bundle with SPA fallback.

The default `nginx.conf` has the `/api/` proxy commented out. In Compose, the
`nginx.compose.conf` is mounted instead and enables same-origin proxying to the
`web` service.

### Build / run the frontend image directly

```powershell
cd app/frontend
docker build -t riskapp-frontend .
docker run --rm -p 8080:80 riskapp-frontend
```

---

## 4. Full local stack (`docker-compose.yml`)

Run from the `app/` directory:

```powershell
cd app
docker compose up --build
```

| Service | Image / build | Port | Purpose |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | `5433` | PostgreSQL + pgvector (reuses `backend_riskapp_pgdata`) |
| `redis` | `redis:7-alpine` | `6379` | Celery broker / result backend |
| `web` | build `./backend` | `8000` | FastAPI (runs `alembic upgrade head` then uvicorn) |
| `worker` | build `./backend` | — | Celery worker |
| `beat` | build `./backend` | — | Celery beat scheduler |
| `frontend` | build `./frontend` | `8080` | React SPA via nginx, proxies `/api/` to `web` |

After startup:

- Frontend: http://localhost:8080
- API: http://localhost:8000
- API docs: http://localhost:8000/docs

### Environment handling

- `backend/.env` is loaded by `web`, `worker`, and `beat`.
- The Postgres service mounts the existing external volume
  `backend_riskapp_pgdata`, so local data created by the previous
  `backend/docker-compose.yml` setup is preserved.
- Compose overrides only the local infrastructure URLs:

```yaml
RISKAPP_DATABASE_URL: postgresql+psycopg://riskapp:riskapp@postgres:5432/riskapp
RISKAPP_REDIS_URL:   redis://redis:6379/0
RISKAPP_CORS_ORIGINS: http://localhost:8080,http://localhost:5173
```

- The frontend calls `/api` same-origin through the mounted nginx config, so no
  CORS issues arise locally.

### Useful commands

```powershell
# Stop everything (keep volumes)
docker compose down

# Rebuild a single service
docker compose build web
```

> Note: `docker compose down -v` will **not** remove the external
> `backend_riskapp_pgdata` volume, so local project data survives.

---

## 5. Migrating from the old Postgres-only compose

If `riskapp-postgres` is already running from `backend/docker-compose.yml`, stop
it first (its data volume is kept), then start the full stack from `app/`:

```powershell
# 1. Stop the old Postgres container (keeps backend_riskapp_pgdata)
cd app/backend
docker compose down

# 2. Free port 8000 if a leftover backend container is running
docker rm -f elegant_lamarr   # adjust name if needed

# 3. Start the full stack
cd ..
docker compose up --build
```

The new `postgres` service mounts the same `backend_riskapp_pgdata` volume, so
projects and risks remain intact.

---

## 6. GitHub Actions PR CI

Implemented in `.github/workflows/ci.yml`. It runs on pull requests and pushes
to `main`/`master`:

| Job | Commands |
|---|---|
| `backend` | `pytest`, `ruff check .`, `mypy src` |
| `frontend` | `npm ci`, `npm run typecheck`, `npm run build` |

Both jobs run in parallel on `ubuntu-latest` using Python 3.11 and Node 20.

---

## 7. What is still pending

- **Execution** of the drafted Azure deployment (needs an Azure login with
  Contributor on the target subscription/resource group):
  1. Provision ACR + Container Apps environment — `bash infra/deploy.sh dev --stage infra`
  2. Build & push images — `bash infra/deploy.sh dev --stage images`
  3. Deploy the four container apps — `bash infra/deploy.sh dev --stage apps`
- Key Vault-backed secrets + managed-identity image pulls (hardening).
- Dev + prod environments, custom domains/TLS if required.

---

## 8. Next steps

1. **Azure provisioning** — `infra/main.bicep` + `infra/deploy.{sh,ps1}`
   provision ACR, the Container Apps environment, and the web/worker/beat/
   frontend apps (see [`infra/README.md`](infra/README.md)).
2. **Build/deploy workflow** — `.github/workflows/deploy.yml` runs the staged
   deploy from CI (`workflow_dispatch`, dev/prod).
3. **Secrets** — store all `RISKAPP_*` values as GitHub secrets for the deploy
   workflow; move them into Key Vault references once hardened.

---

## 9. Required secrets (for Azure deployment)

These are read from the backend configuration and should live in Key Vault, not
the repository:

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
```
