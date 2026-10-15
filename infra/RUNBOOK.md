# Deploy Runbook — PMO Risk Intelligence

Operational quick reference. Full detail lives in `README.md`.

All commands are run from the **`app/`** directory (where the git repo,
`infra/`, `backend/` and `frontend/` live).

> **One environment.** The integration environment (`int`) **is** the production
> environment. There is no separate dev or prod. The deploy scripts accept only
> `int` and default to the UK South region.

---

## 0. Environment facts

| Thing | Value |
|---|---|
| Subscription | `INT - Wragby AI Processes` (`853e06f6-…`) |
| Tenant | `7085725b-…` |
| Resource group | **`rg-riskapp-int`** |
| Region | **UK South** (app + PostgreSQL co-located) |
| ACR | `riskappintacr5629c9eb.azurecr.io` |
| Frontend | https://riskapp-int-frontend.wonderfulsky-6f3252fb.uksouth.azurecontainerapps.io |
| API | https://riskapp-int-web.wonderfulsky-6f3252fb.uksouth.azurecontainerapps.io |
| Postgres | `riskapp-int-postgres.postgres.database.azure.com` |
| Entra app | `PMO Risk Intelligence` (client `fe7b73a3-…`) |
| Sign-in | **Microsoft Entra ID SSO** (production) |
| Runtime config | `infra/deploy.int.env` — git-ignored, generated, contains secrets |

---

## 1. Once per session

```bash
cd app
az login                              # skip if already signed in
az account set --subscription 853e06f6-36ff-4a98-9591-50d75629c9eb
az account show                       # confirm: INT - Wragby AI Processes
docker info >/dev/null && echo "docker OK"
```

The deploy needs **Azure CLI, Docker running, and ~3 GB free disk**. The script
checks disk space itself and refuses to build when the host is nearly full.

---

## 2. The only script you normally need

### `infra/deploy-service.sh` — deploy one service, a few, or everything

```bash
bash infra/deploy-service.sh int [options]
```

| Service | Image | When to deploy it |
|---------|-------|-------------------|
| `frontend` | `riskapp-frontend` | any UI/CSS change |
| `web` | `riskapp-backend` | API change (also runs `alembic upgrade head`) |
| `worker` | `riskapp-backend` | Celery task change |
| `beat` | `riskapp-backend` | schedule change |
| `all` | both | default |

> `web`, `worker` and `beat` **share one image**. Deploy them together so they
> never drift: `--service web,worker,beat`.

### Everyday recipes

```bash
# UI change
bash infra/deploy-service.sh int --service frontend --image-tag "ui-$(date +%m%d%H%M)"

# API change (one image covers all three)
bash infra/deploy-service.sh int --service web,worker,beat --image-tag "api-$(date +%m%d%H%M)"

# Everything
bash infra/deploy-service.sh int

# Reuse an image that is already in the registry (no build, fast)
bash infra/deploy-service.sh int --service frontend --stage apps --no-build --image-tag <existing-tag>

# Infrastructure only, or images only
bash infra/deploy-service.sh int --stage infra
bash infra/deploy-service.sh int --stage images
```

### Pass `--image-tag` whenever you have uncommitted changes

The default tag is the **git commit short SHA**. Container Apps will **not** roll
a new revision for a tag string it has already seen — so if you edited files
without committing, the default tag points at an image that already exists and
your change silently never ships. The script warns when `frontend/` or
`backend/` are dirty and you used the default tag. Obey the warning.

### Safety preflights (automatic, bash only)

The script refuses to deploy when the result would be broken or insecure:

| Condition | Result |
|-----------|--------|
| `RISKAPP_DATABASE_URL` empty | **Refuses** — API cannot start |
| `RISKAPP_ENTRA_TENANT_ID` empty | **Refuses** — with no tenant the API refuses all requests (401); this guards against an accidentally unauthenticated deployment |
| < 3 GB free disk before a build | **Refuses** — a full disk makes `docker build` hang |
| Uncommitted `frontend/`/`backend/` + default SHA tag | **Warns** — no new revision would roll |
| App-managed password login enabled | **Refuses** — bypasses Entra MFA and Conditional Access; override with `--allow-local-login` |

---

## 3. Configuration changes

Runtime config lives in **`infra/deploy.int.env`** (git-ignored, generated).

Re-generate it from the **live** Azure resources after changing infrastructure
(DB, storage, URLs). External values (OpenAI, ACS, Entra) are seeded from
`backend/.env` or passed with `--env`:

```bash
bash infra/generate-deploy-env.sh int --seed-from backend/.env
```

Then deploy normally. Verify what it resolved without printing secrets:

```bash
grep -oE '^[A-Z_]+=' infra/deploy.int.env        # names only
awk -F= '/^VITE_/{print $1, length($2)" chars"}' infra/deploy.int.env
```

---

## 4. Entra ID (auth)

Microsoft Entra ID SSO is the production sign-in method. The SPA is built with
`VITE_AUTH_MODE=entra`; the API validates the token and resolves roles from the
`groups` claim.

```bash
# Provision/refresh the app registration, scope, groups + write the keys
bash infra/register-entra-app.sh int \
  https://riskapp-int-frontend.wonderfulsky-6f3252fb.uksouth.azurecontainerapps.io \
  --output-env infra/deploy.int.env

# Refresh the user directory shown in owner/PM pickers (safe to re-run)
bash infra/sync-entra-users.sh int
```

> Changing `VITE_AUTH_MODE` / `VITE_ENTRA_*` requires a **frontend rebuild**
> (build-time value). Changing `RISKAPP_ENTRA_*` or
> `RISKAPP_LOCAL_LOGIN_ENABLED` requires a **backend deploy** (runtime value).

**App-managed email + password.** For people without an Entra account, the app
can hold the password itself. Full detail and the provisioning workflow are in
[`docs/AUTHENTICATION.md`](../docs/AUTHENTICATION.md); the short version:

```bash
# 1. Provision people from a CSV (email,name,role) — creates/updates rows
cd backend && .venv/Scripts/python.exe -m riskapp.provision_users \
    --file ../../people.csv --out ../../provisioned-credentials.csv

# 2. Set in infra/deploy.int.env:
#      RISKAPP_LOCAL_LOGIN_ENABLED=true
#      VITE_AUTH_MODE=password

# 3. Deploy (the flag acknowledges the MFA/Conditional-Access trade-off)
bash infra/deploy-service.sh int --allow-local-login
```

Passwords are stored as salted scrypt hashes and cannot be read back, so the
generated credentials CSV must be delivered to each person out-of-band and then
deleted. The deploy refuses to enable local login without `--allow-local-login`.

---

## 5. Verify a deploy

```bash
# What is running right now (images + revisions)
az containerapp list -g rg-riskapp-int \
  --query "[].{name:name, image:properties.template.containers[0].image, ready:properties.latestReadyRevisionName}" -o table

# What the last run actually deployed
cat infra/deployment-info-int.json

# Health + auth gate (401 without a token is correct)
curl -s -o /dev/null -w "health:%{http_code}\n"  https://riskapp-int-web.wonderfulsky-6f3252fb.uksouth.azurecontainerapps.io/health
curl -s -o /dev/null -w "auth:%{http_code}\n"    https://riskapp-int-web.wonderfulsky-6f3252fb.uksouth.azurecontainerapps.io/api/projects
```

Frontend: <https://riskapp-int-frontend.wonderfulsky-6f3252fb.uksouth.azurecontainerapps.io>
API docs: <https://riskapp-int-web.wonderfulsky-6f3252fb.uksouth.azurecontainerapps.io/docs>

---

## 6. Other scripts

| Script | Use it for |
|--------|-----------|
| `infra/deploy-service.sh` | **Normal deploys** (above) |
| `infra/deploy-service.ps1` | PowerShell twin — **no safety preflights** |
| `infra/generate-deploy-env.sh` | Rebuild `deploy.int.env` from live Azure |
| `infra/register-entra-app.sh` | Entra app registration / SSO keys |
| `infra/sync-entra-users.sh` | Import Entra users into the `users` table |
| `infra/check-db-latency.sh` | Measure app → PostgreSQL round-trip |
| `infra/deploy.sh` | Legacy whole-stack (infra + images + apps) |
| `docker-compose.yml` | Local stack (not Azure) |

### Local stack (not Azure)

```bash
cd app
docker compose up -d --build          # frontend :8080  api :8000  postgres :5433  redis :6379
docker compose logs -f web
docker compose down
```

Set `VITE_AUTH_MODE=password` to exercise the fallback sign-in locally, or point
`RISKAPP_ENTRA_*` at the tenant to mirror production SSO.

### CI

GitHub → **Actions → Deploy → Run workflow** (`workflow_dispatch`). It calls
`deploy-service.sh int` with `--image-tag ${{ github.sha }}` and reads
`RISKAPP_*` from repo secrets.

---

## 7. If something goes wrong

```bash
# Recent app deployments and their outcome (filters out Azure Policy noise)
az deployment group list -g rg-riskapp-int \
  --query "[?starts_with(name,'riskapp-int-')].{name:name,state:properties.provisioningState,time:properties.timestamp} | sort_by(@, &time)[-4:]" -o table

# Why one failed
az deployment group show -g rg-riskapp-int -n <deployment-name> \
  --query "properties.error" -o json

# Container logs
az containerapp logs show -g rg-riskapp-int -n riskapp-int-web --tail 100
az containerapp logs show -g rg-riskapp-int -n riskapp-int-frontend --tail 50
```

**Disk full / build hangs for 20+ minutes** → the host disk is out of space.
`docker builder prune -f`, delete stale temp files, re-run.

**Deploy said COMPLETE but nothing changed** → you reused an image tag. Re-run
with a fresh `--image-tag`.

**Roll back** → redeploy the previous tag:
`bash infra/deploy-service.sh int --service frontend --stage apps --no-build --image-tag <previous-tag>`

**Performance** → the Container Apps and PostgreSQL both run in **UK South**, so
queries are same-region. Confirm with `bash infra/check-db-latency.sh int`
(expect single-digit ms per query).
