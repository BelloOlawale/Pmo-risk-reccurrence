# Deploy Runbook — PMO Risk Recurrence Predictor

Quick reference for deploying. Full detail lives in `README.md`.

All commands are run from the **`app/`** directory (that is where the git repo,
`infra/`, `backend/` and `frontend/` live).

---

## 0. Once per session

```bash
cd app
az login                              # skip if already signed in
az account show                       # confirm: Datazone@alawani_wragby / e56d44da-…
docker info >/dev/null && echo "docker OK"
```

The deploy needs **Azure CLI, Docker running, and ~3 GB free disk**. The script
checks disk space itself and refuses to build when the host is nearly full.

---

## 1. The only script you normally need

### `infra/deploy-service.sh` — deploy one service, a few, or everything

```bash
bash infra/deploy-service.sh <dev|prod> [options]
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
bash infra/deploy-service.sh dev --service frontend --image-tag "ui-$(date +%m%d%H%M)"

# API change (one image covers all three)
bash infra/deploy-service.sh dev --service web,worker,beat --image-tag "api-$(date +%m%d%H%M)"

# Everything
bash infra/deploy-service.sh dev

# Reuse an image that is already in the registry (no build, fast)
bash infra/deploy-service.sh dev --service frontend --stage apps --no-build --image-tag <existing-tag>

# Infrastructure only, or images only
bash infra/deploy-service.sh dev --stage infra
bash infra/deploy-service.sh dev --stage images
```

### Pass `--image-tag` whenever you have uncommitted changes

The default tag is the **git commit short SHA**. Container Apps will **not** roll
a new revision for a tag string it has already seen — so if you edited files
without committing, the default tag points at an image that already exists and
your change silently never ships.

The script now warns when `frontend/` or `backend/` are dirty and you used the
default tag. Obey the warning: pass `--image-tag`.

### Safety preflights (automatic, bash only)

The script refuses to deploy when the result would be broken or insecure:

| Condition | Result |
|-----------|--------|
| `RISKAPP_DATABASE_URL` empty | **Refuses** — API cannot start |
| `RISKAPP_ENTRA_TENANT_ID` empty | **Refuses** — API would trust unauthenticated `X-User-Role` headers, making anyone who can reach the URL an admin |
| < 3 GB free disk before a build | **Refuses** — a full disk makes `docker build` hang |
| Uncommitted `frontend/`/`backend/` + default SHA tag | **Warns** — no new revision would roll |
| Test/password login enabled for non-`dev` | **Warns** — bypasses Entra MFA |

To intentionally deploy an API with no tenant (local/dev only):

```bash
bash infra/deploy-service.sh dev --allow-dev-auth
```

---

## 2. Configuration changes

Runtime config lives in **`infra/deploy.dev.env`** (git-ignored, generated).

Re-generate it from the **live** Azure resources after changing infrastructure
(DB, storage, URLs). External values (OpenAI, ACS, Entra) are seeded from
`backend/.env` or passed with `--env`:

```bash
bash infra/generate-deploy-env.sh dev --seed-from backend/.env
```

Then deploy normally. Verify what it resolved without printing secrets:

```bash
grep -oE '^[A-Z_]+=' infra/deploy.dev.env        # names only
awk -F= '/^VITE_/{print $1, length($2)" chars"}' infra/deploy.dev.env
```

---

## 3. Entra ID (only when auth changes)

```bash
# Provision/refresh the app registration, scope, groups + write the six keys
bash infra/register-entra-app.sh dev https://riskapp-dev-frontend.lemonsand-ee3845bc.eastus.azurecontainerapps.io \
  --output-env infra/deploy.dev.env

# Refresh the user directory shown in owner/PM pickers (safe to re-run)
bash infra/sync-entra-users.sh dev

# Include B2B guests (excluded by default)
bash infra/sync-entra-users.sh dev --include-guests
```

> Changing `VITE_ENTRA_*` requires a **frontend rebuild** (build-time values).
> Changing `RISKAPP_ENTRA_*` requires a **backend deploy** (runtime values).

---

## 4. Verify a deploy

```bash
# What is running right now (images + revisions)
az containerapp list -g rg-riskapp-dev \
  --query "[].{name:name, image:properties.template.containers[0].image, ready:properties.latestReadyRevisionName}" -o table

# What the last run actually deployed
cat infra/deployment-info-dev.json

# Health + auth gate (401 without a token is correct)
curl -s -o /dev/null -w "health:%{http_code}\n"  https://riskapp-dev-web.lemonsand-ee3845bc.eastus.azurecontainerapps.io/health
curl -s -o /dev/null -w "auth:%{http_code}\n"    https://riskapp-dev-web.lemonsand-ee3845bc.eastus.azurecontainerapps.io/api/projects
```

Frontend: <https://riskapp-dev-frontend.lemonsand-ee3845bc.eastus.azurecontainerapps.io>
API docs: <https://riskapp-dev-web.lemonsand-ee3845bc.eastus.azurecontainerapps.io/docs>

---

## 5. Other scripts

| Script | Use it for |
|--------|-----------|
| `infra/deploy-service.sh` | **Normal deploys** (above) |
| `infra/deploy-service.ps1` | PowerShell twin — **no safety preflights** |
| `infra/generate-deploy-env.sh` | Rebuild `deploy.<env>.env` from live Azure |
| `infra/register-entra-app.sh` | Entra app registration / SSO keys |
| `infra/sync-entra-users.sh` | Import Entra users into the `users` table |
| `infra/deploy.sh` | Legacy whole-stack (infra + images + apps) |
| `docker-compose.yml` | Local stack (see below) |

### Local stack (not Azure)

```bash
cd app
docker compose up -d --build          # frontend :8080  api :8000  postgres :5433  redis :6379
docker compose logs -f web
docker compose down
```

The local frontend has **no** `VITE_ENTRA_*` build args, so it runs in dev mode
(no sign-in page, role switcher in the sidebar).

### CI

GitHub → **Actions → Deploy → Run workflow** (`workflow_dispatch`), choosing
environment / stage / service. It calls `deploy-service.sh` with
`--image-tag ${{ github.sha }}` and reads `RISKAPP_*` from repo secrets.

---

## 6. If something goes wrong

```bash
# Recent app deployments and their outcome (filters out Azure Policy noise)
az deployment group list -g rg-riskapp-dev \
  --query "[?starts_with(name,'riskapp-dev-')].{name:name,state:properties.provisioningState,time:properties.timestamp} | sort_by(@, &time)[-4:]" -o table

# Why one failed
az deployment group show -g rg-riskapp-dev -n <deployment-name> \
  --query "properties.error" -o json

# Container logs
az containerapp logs show -g rg-riskapp-dev -n riskapp-dev-web --tail 100
az containerapp logs show -g rg-riskapp-dev -n riskapp-dev-frontend --tail 50
```

**Disk full / build hangs for 20+ minutes** → the host disk is out of space.
`docker builder prune -f`, delete stale temp files, re-run.

**Deploy said COMPLETE but nothing changed** → you reused an image tag. Re-run
with a fresh `--image-tag`.

**Roll back** → redeploy the previous tag:
`bash infra/deploy-service.sh dev --service frontend --stage apps --no-build --image-tag <previous-tag>`
