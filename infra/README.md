# PMO Risk Intelligence — Azure Deployment Guide

Infrastructure as Code (Bicep) and deployment scripts for the PMO Risk
Intelligence app on Azure Container Apps.

> **One environment.** The integration environment (`int`) **is** the production
> environment. Everything runs in **UK South** in resource group
> **`rg-riskapp-int`**, in the `INT - Wragby AI Processes` subscription. There is
> no separate dev or prod.

- [**Deploy Runbook →**](./RUNBOOK.md) — the short version: which script to run when
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Deployment Options](#deployment-options)
- [Per-service deploys](#per-service-deploys)
- [Post-Deployment](#post-deployment)
- [Troubleshooting](#troubleshooting)
- [Cost Estimation](#cost-estimation)

---

## Quick Start

### Bash (recommended)

```bash
cd app
az login
az account set --subscription 853e06f6-36ff-4a98-9591-50d75629c9eb

# Deploy everything (infra -> images -> apps)
bash infra/deploy-service.sh int
```

### PowerShell

```powershell
cd app\infra
.\deploy-service.ps1 -Environment int
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│          Subscription: INT - Wragby AI Processes  (UK South)                 │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                     Resource Group: rg-riskapp-int                    │  │
│  │                                                                        │  │
│  │  ┌─────────────┐  ┌──────────────────────────────────────────────┐   │  │
│  │  │     ACR     │  │        Container Apps Environment             │   │  │
│  │  │ riskappint- │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐      │   │  │
│  │  │ acr…        │  │  │   Web    │ │  Worker  │ │   Beat   │      │   │  │
│  │  │             │  │  │ FastAPI  │ │  Celery  │ │  Beat    │      │   │  │
│  │  └─────────────┘  │  └──────────┘ └──────────┘ └──────────┘      │   │  │
│  │        │          │  ┌──────────┐                                  │   │  │
│  │        │          │  │Frontend  │                                  │   │  │
│  │        │          │  │  (nginx) │                                  │   │  │
│  │        │          │  └──────────┘                                  │   │  │
│  │        │          └──────────────────────────────────────────────┘   │  │
│  │        ▼                              ▼                               │  │
│  │  ┌──────────────────────────────────────────────────────────────┐    │  │
│  │  │  PostgreSQL (pgvector)  Redis  Blob  Key Vault  OpenAI  ACS  │    │  │
│  │  └──────────────────────────────────────────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

All resources are co-located in **UK South** so database round-trips are
same-region (a few ms per query).

### Resources

| Resource | Name | Purpose |
|----------|------|---------|
| Container Registry | `riskappintacr…` | Docker image storage |
| Container Apps Environment | `riskapp-int-env` | Container runtime |
| Web App (FastAPI) | `riskapp-int-web` | API + migrations |
| Worker (Celery) | `riskapp-int-worker` | Background jobs |
| Beat (Celery Beat) | `riskapp-int-beat` | Task scheduler |
| Frontend (nginx) | `riskapp-int-frontend` | React SPA |
| PostgreSQL Flexible Server | `riskapp-int-postgres` | Database + pgvector |
| Cache for Redis | `riskapp-int-redis…` | Celery broker |
| Blob Storage | `riskappintsa…` | File storage |
| Key Vault | `riskapp-int-kv` | Secrets |
| Azure OpenAI | `riskapp-int-openai…` | Chat + embeddings |
| Communication Services | `riskapp-int-acs` | Email |

---

## Prerequisites

1. **Azure CLI** (`az`) — `winget install Microsoft.AzureCLI`
2. **Docker Desktop** (running)
3. **Bicep** — auto-installed by the Azure CLI (`az bicep install`)
4. **Permissions** — Contributor on `rg-riskapp-int` (Owner / User Access
   Administrator if role assignments are needed), and Application Administrator
   in Entra for auth changes.

---

## Deployment Options

### 1. Per-service (normal day-to-day)

See [Per-service deploys](#per-service-deploys) — this is the script you use
almost every time.

### 2. Full stack

```powershell
.\deploy.ps1 -Environment int              # infra -> images -> apps
.\deploy.ps1 -Environment int -Stage infra # infrastructure only
.\deploy.ps1 -Environment int -Stage images
.\deploy.ps1 -Environment int -Stage apps
```

```bash
bash infra/deploy.sh int                   # bash equivalent
```

> `main-complete.bicep` (used by `deploy.sh` / `deploy.ps1`) is the only
> template that provisions PostgreSQL, Redis, Storage, Key Vault and OpenAI.
> `main.bicep` (used by `deploy-service.*`) deploys the registry, environment and
> the four container apps, and is the right choice once infrastructure exists.

---

## Per-service deploys

`deploy-service.sh` / `deploy-service.ps1` deploy any subset of `web`, `worker`,
`beat`, `frontend` (or `all`). Runtime configuration (`RISKAPP_*`) is read from
the environment and/or `infra/deploy.int.env`.

```bash
bash infra/deploy-service.sh int                          # everything
bash infra/deploy-service.sh int --service frontend       # only the SPA
bash infra/deploy-service.sh int --service web,worker     # API + Celery worker
bash infra/deploy-service.sh int --service beat --stage apps --no-build
bash infra/deploy-service.sh int --image-tag "$(git rev-parse --short HEAD)"
```

| Option | Bash | PowerShell | Description |
|--------|------|------------|-------------|
| Service(s) | `--service web,worker` | `-Services web,worker` | `web`, `worker`, `beat`, `frontend`, `all` (default) |
| Stage | `--stage apps` | `-Stage apps` | `all` (default), `infra`, `images`, `apps` |
| Image tag | `--image-tag <tag>` | `-ImageTag <tag>` | Default: commit short SHA (immutable) |
| Skip build | `--no-build` | `-NoBuild` | Reuse existing images |
| Config file | `--env-file <path>` | `-EnvFile <path>` | Default `backend/.env` |
| Override | `--env K=V` / `--secret K=V` | `-Env @{K='V'}` / `-Secret @{K='V'}` | Ad-hoc values |
| Managed identity | `--managed-identity <id>` | `-ManagedIdentity <id>` | Identity used by the apps |
| Registry identity | `--registry-identity <id>` | `-RegistryIdentity <id>` | Pull images without ACR admin creds |

> **The default image tag is the commit short SHA, not `latest`.** Container Apps
> will not roll a new revision for a tag string it has already seen. If you have
> *uncommitted* changes the SHA no longer identifies the code being shipped — pass
> an explicit tag, e.g. `--image-tag "$(git rev-parse --short HEAD)-$(date +%m%d%H%M)"`.

### Safety preflights (`deploy-service.sh`)

| Check | Behaviour |
|-------|-----------|
| `RISKAPP_DATABASE_URL` empty | **Refuses** — the API cannot start. |
| `RISKAPP_ENTRA_TENANT_ID` empty | **Refuses** — with no tenant the API refuses all requests (401). |
| Free disk < 3 GB before an image build | **Refuses** — a full disk makes `docker build` stall. |
| Uncommitted `frontend/`/`backend/` + default SHA tag | **Warns** — the tag may already exist, so no new revision would roll. |
| App-managed password login enabled | **Refuses** — bypasses Entra MFA and Conditional Access; override with `--allow-local-login`. |

> `deploy-service.ps1` does **not** implement these preflights. Prefer the bash
> script (or WSL) for deploys.

Which service maps to which image:

| Service | Image | Command |
|---------|-------|---------|
| `web` | `riskapp-backend` | `alembic upgrade head && uvicorn …` |
| `worker` | `riskapp-backend` | `celery … worker` |
| `beat` | `riskapp-backend` | `celery … beat` |
| `frontend` | `riskapp-frontend` | nginx (proxies `/api` to `web`) |

---

## Authentication (Entra ID SSO)

The production sign-in method is **Microsoft Entra ID SSO**. The SPA is built
with `VITE_AUTH_MODE=entra`; the API validates the OIDC token and maps the
`groups` claim to one of three roles via `RISKAPP_ENTRA_ROLE_GROUP_IDS`.

```bash
# Provision/refresh the app registration, scope, groups + write the keys
bash infra/register-entra-app.sh int \
  https://riskapp-int-frontend.wonderfulsky-6f3252fb.uksouth.azurecontainerapps.io \
  --output-env infra/deploy.int.env

# Refresh the user directory used by owner/PM pickers (safe to re-run)
bash infra/sync-entra-users.sh int
```

- B2B guest accounts (`#EXT#` UPNs) are excluded by default.
- App-managed email + password login (`RISKAPP_LOCAL_LOGIN_ENABLED`) is a
  supported sign-in option for people without Entra accounts. It bypasses MFA
  and requires deliberate enablement (`--allow-local-login`); see
  [`docs/AUTHENTICATION.md`](../docs/AUTHENTICATION.md).
- Changing `VITE_ENTRA_*` requires a **frontend rebuild**; changing
  `RISKAPP_ENTRA_*` / `RISKAPP_LOCAL_LOGIN_ENABLED` requires a **backend deploy**.

---

## Post-Deployment

```bash
# Verify container apps
az containerapp list -g rg-riskapp-int \
  --query "[].{name:name, image:properties.template.containers[0].image, ready:properties.latestReadyRevisionName}" -o table

# Health + auth gate (401 without a token is correct)
curl -s -o /dev/null -w "health:%{http_code}\n" https://riskapp-int-web.wonderfulsky-6f3252fb.uksouth.azurecontainerapps.io/health
curl -s -o /dev/null -w "auth:%{http_code}\n"   https://riskapp-int-web.wonderfulsky-6f3252fb.uksouth.azurecontainerapps.io/api/projects
```

---

## Troubleshooting

### Container App not starting

```bash
az containerapp revision list -g rg-riskapp-int -n riskapp-int-web --query "[0].properties.healthState"
az containerapp logs show -g rg-riskapp-int -n riskapp-int-web --tail 100
```

### Database connection issues

```bash
az postgres flexible-server show -g rg-riskapp-int -n riskapp-int-postgres \
  --query "{fqdn:fullyQualifiedDomainName,state:state}"
az postgres flexible-server firewall-rule list -g rg-riskapp-int -s riskapp-int-postgres -o table
```

### Image pull failures

```bash
az acr credential show -n riskappintacr5629c9eb
az acr repository show -n riskappintacr5629c9eb --image riskapp-backend:d2081f8
```

### Deploy said COMPLETE but nothing changed

You reused an image tag. Re-run with a fresh `--image-tag`.

---

## Cost Estimation

| Service | Tier | Est. monthly |
|---------|------|--------------|
| Container Apps | Consumption | $5–50 |
| PostgreSQL Flexible Server | Burstable B2s | $50–80 |
| Azure Cache for Redis | Basic C0 | $20–30 |
| Blob Storage | Standard LRS | $5 |
| Key Vault | Standard | $3 |
| Container Registry | Basic | $5 |
| Azure OpenAI | S0 | $50–200 |
| Log Analytics | Pay-as-you-go | $10 |
| **Total** | | **~$150–380/month** |

---

## File Structure

```
infra/
├── main-complete.bicep      # Full stack (infra + apps) — deploy.sh / deploy.ps1
├── main.bicep               # Registry + environment + apps — deploy-service.*
├── deploy.sh / deploy.ps1   # Full deployment
├── deploy-service.sh / .ps1 # Per-service deployment (normal deploys)
├── generate-deploy-env.sh   # Rebuild deploy.int.env from live Azure
├── register-entra-app.sh    # Entra app registration / SSO keys
├── sync-entra-users.sh      # Import Entra users into the users table
├── check-db-latency.sh      # Measure app → PostgreSQL round-trip
├── deploy.int.env           # Runtime config + secrets (git-ignored, generated)
├── deployment-info-int.json # Last deploy output (generated)
├── README.md                # This file
├── RUNBOOK.md               # Which script to run when (start here)
└── modules/                 # Bicep modules (container-app, environment, …)
```
