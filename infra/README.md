# PMO Risk Recurrence Predictor — Azure Deployment Guide

This directory contains Infrastructure as Code (Bicep) templates and deployment scripts for deploying the PMO Risk Recurrence Predictor to Azure.

## Table of Contents

- [**Deploy Runbook →**](./RUNBOOK.md) — the short version: which script to run when
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Deployment Options](#deployment-options)
- [Detailed Usage](#detailed-usage)
- [Post-Deployment](#post-deployment)
- [Troubleshooting](#troubleshooting)
- [Cost Estimation](#cost-estimation)

---

## Quick Start

### Option 1: PowerShell (Windows)

```powershell
# Clone and navigate to the repo
cd app/infra

# Login to Azure
az login

# Deploy development environment
.\deploy.ps1 -Environment dev

# You'll be prompted for the PostgreSQL admin password
```

### Option 2: Bash (macOS/Linux)

```bash
# Clone and navigate to the repo
cd app/infra

# Login to Azure
az login

# Deploy development environment
bash deploy.sh dev

# You'll be prompted for the PostgreSQL admin password
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Azure Subscription                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                     Resource Group: rg-riskapp-{env}                 │  │
│  │                                                                        │  │
│  │  ┌─────────────┐  ┌──────────────────────────────────────────────┐   │  │
│  │  │     ACR     │  │        Container Apps Environment             │   │  │
│  │  │ (Registry)  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐      │   │  │
│  │  │             │  │  │   Web    │ │  Worker  │ │   Beat   │      │   │  │
│  │  │ riskapp-*   │  │  │ FastAPI  │ │  Celery  │ │  Beat    │      │   │  │
│  │  └─────────────┘  │  └──────────┘ └──────────┘ └──────────┘      │   │  │
│  │        │          │  ┌──────────┐                                  │   │  │
│  │        │          │  │Frontend  │                                  │   │  │
│  │        │          │  │  (nginx) │                                  │   │  │
│  │        │          │  └──────────┘                                  │   │  │
│  │        │          └──────────────────────────────────────────────┘   │  │
│  │        │                              │                               │  │
│  │        ▼                              ▼                               │  │
│  │  ┌──────────────────────────────────────────────────────────────┐    │  │
│  │  │                    Azure Managed Services                     │    │  │
│  │  │  ┌────────────┐  ┌────────┐  ┌────────┐  ┌────────────┐  ┌───────────┐   │    │  │
│  │  │  │ PostgreSQL │  │ Redis  │  │  Blob  │  │  Key Vault │  │Azure OpenAI│   │    │  │
│  │  │  │ Flexible   │  │ Cache  │  │ Storage│  │            │  │ (GPT-5.4)  │   │    │  │
│  │  │  │ (pgvector) │  │        │  │        │  │            │  └───────────┘   │    │  │
│  │  │  └────────────┘  └────────┘  └────────┘  └────────────┘                 │    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Resources Deployed

| Resource | Name Pattern | Purpose |
|----------|--------------|---------|
| Azure Container Registry | `{prefix}{env}acr{suffix}` | Docker image storage |
| Container Apps Environment | `{prefix}-{env}-env` | Container runtime |
| Web App (FastAPI) | `{prefix}-{env}-web` | API + migrations |
| Worker (Celery) | `{prefix}-{env}-worker` | Background jobs |
| Beat (Celery Beat) | `{prefix}-{env}-beat` | Task scheduler |
| Frontend (nginx) | `{prefix}-{env}-frontend` | React SPA |
| PostgreSQL Flexible Server | `{prefix}-{env}-postgres{suffix}` | Database + pgvector |
| Azure Cache for Redis | `{prefix}-{env}-redis{suffix}` | Celery broker |
| Blob Storage | `{prefix}{env}sa{suffix}` | File storage |
| Key Vault | `{prefix}-{env}-kv` | Secrets management |
| Azure OpenAI | `{prefix}-{env}-openai{suffix}` | AI models (GPT-5.4 + embeddings) |
| User-Assigned MI | `{prefix}-{env}-mi` | Managed identity |

---

## Prerequisites

### Required Tools

1. **Azure CLI** (`az`)
   ```bash
   # Install on Windows (winget)
   winget install Microsoft.AzureCLI

   # Install on macOS
   brew install azure-cli

   # Install on Linux
   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
   ```

2. **Docker Desktop** (for building images)
   ```bash
   # Download from: https://www.docker.com/products/docker-desktop/
   ```

3. **Bicep** (auto-installed by Azure CLI)
   ```bash
   az bicep install
   ```

### Azure Permissions

You need one of the following:

- **Subscription-level**: Contributor role
- **Resource Group-level**: Contributor on the target resource group

To check your role:
```bash
az role assignment list --assignee $(az ad signed-in-user show --query id -o tsv) --output table
```

---

## Deployment Options

### 1. Full Deployment (All Resources)

```powershell
# PowerShell
.\deploy.ps1 -Environment dev

# Bash
bash deploy.sh dev
```

### 2. Staged Deployment

Deploy in stages for better control:

```powershell
# Stage 1: Infrastructure only
.\deploy.ps1 -Environment dev -Stage infra

# Stage 2: Build and push images
.\deploy.ps1 -Environment dev -Stage images

# Stage 3: Deploy container apps
.\deploy.ps1 -Environment dev -Stage apps
```

### 3. Custom Location

```powershell
.\deploy.ps1 -Environment dev -Location westus2
```

### 4. Production Environment

```powershell
.\deploy.ps1 -Environment prod -Location eastus
```

### 5. Private Networking (VNet + Private Endpoints)

```powershell
.\deploy.ps1 -Environment dev -UsePrivateNetworking
```

### 6. Skip Image Build (if images already exist)

```powershell
.\deploy.ps1 -Environment dev -SkipImageBuild
```

---

## Deploy a Single Service (any service)

`deploy-service.sh` / `deploy-service.ps1` drive `main.bicep` to deploy **any
subset of services** — `web`, `worker`, `beat`, `frontend` — or all of them. Use
them for day-to-day releases (one image, one app) after the infrastructure
already exists. Runtime configuration (`RISKAPP_*`) is read from the environment
and/or `backend/.env` and wired in as plain env vars plus Container App secrets.

```bash
# Everything (infra -> images -> apps)
bash infra/deploy-service.sh dev

# Only the frontend
bash infra/deploy-service.sh dev --service frontend

# API + Celery worker only
bash infra/deploy-service.sh dev --service web,worker

# Re-deploy an existing image without rebuilding
bash infra/deploy-service.sh dev --service beat --stage apps --no-build

# Tag the release with the commit SHA
bash infra/deploy-service.sh prod --image-tag "$(git rev-parse --short HEAD)"
```

```powershell
.\deploy-service.ps1 -Environment dev
.\deploy-service.ps1 -Environment dev -Services frontend
.\deploy-service.ps1 -Environment dev -Services web,worker -Stage apps -NoBuild
```

| Option | Bash | PowerShell | Description |
|--------|------|------------|-------------|
| Service(s) | `--service web,worker` | `-Services web,worker` | `web`, `worker`, `beat`, `frontend`, `all` (default) |
| Stage | `--stage apps` | `-Stage apps` | `all` (default), `infra`, `images`, `apps` |
| Image tag | `--image-tag <tag>` | `-ImageTag <tag>` | Default: commit short SHA (immutable — see below) |
| Skip build | `--no-build` | `-NoBuild` | Reuse existing images |
| Config file | `--env-file <path>` | `-EnvFile <path>` | Default `backend/.env` |
| Override | `--env K=V` / `--secret K=V` | `-Env @{K='V'}` / `-Secret @{K='V'}` | Ad-hoc values |
| Managed identity | `--managed-identity <id>` | `-ManagedIdentity <id>` | Identity used by the apps |
| Registry identity | `--registry-identity <id>` | `-RegistryIdentity <id>` | Pull images without ACR admin creds |
| Allow dev auth | `--allow-dev-auth` | *(not implemented)* | Opt out of the tenant preflight (**bash only**) |

> **The default image tag is the commit short SHA, not `latest`.** Container Apps
> will not roll a new revision for a tag string it has already seen, so a mutable
> tag like `latest` makes redeploys silently do nothing. If you have *uncommitted*
> changes the SHA no longer identifies the code being shipped — the script warns
> and you should pass an explicit tag, e.g. `--image-tag "$(git rev-parse --short HEAD)-$(date +%m%d%H%M)"`.

### Safety preflights (`deploy-service.sh`)

The bash script performs these checks before it touches Azure, so a misconfigured
run fails fast instead of half-deploying or hanging:

| Check | Behaviour |
|-------|-----------|
| `RISKAPP_DATABASE_URL` empty | **Refuses** — the API cannot start. |
| `RISKAPP_ENTRA_TENANT_ID` empty | **Refuses** — with no tenant the API trusts unauthenticated `X-User-Role` headers (`get_principal` in `backend/src/riskapp/auth.py`), so anyone reaching the URL is an administrator. Override only deliberately with `--allow-dev-auth`. |
| Free disk < 3 GB before an image build | **Refuses** — a full disk makes `docker build` stall for tens of minutes rather than reporting `ENOSPC`. |
| Uncommitted changes under `frontend/` or `backend/` with a default SHA tag | **Warns** — the tag may already exist, so no new revision would roll. |
| Test login / password login enabled for a non-`dev` environment | **Warns** — these bypass Entra MFA and Conditional Access. |

> `deploy-service.ps1` does **not** implement these preflights yet. Until it does,
> prefer the bash script (or WSL) for deploys, and never bypass the tenant check on
> a shared environment.

Which service maps to which image:

| Service | Image | Command |
|---------|-------|---------|
| `web` | `riskapp-backend` | `alembic upgrade head && uvicorn …` |
| `worker` | `riskapp-backend` | `celery … worker` |
| `beat` | `riskapp-backend` | `celery … beat` |
| `frontend` | `riskapp-frontend` | nginx (proxies `/api` to `web`) |

---

## Sync the Entra ID user directory

Risk owners are stored as a foreign key to the local `users` table, so the owner
picker only shows people who exist there. `sync-entra-users.sh` imports **every
user in the Entra ID tenant** so the dropdown is populated without anyone
having to sign in first.

```bash
bash infra/sync-entra-users.sh dev        # uses the signed-in Azure CLI Graph token
bash infra/sync-entra-users.sh dev --source graph   # app-only (needs User.Read.All + admin consent)
```

- Existing rows are matched case-insensitively by UPN and **never deleted**, so
  it is safe to re-run (e.g. from a scheduled job) to pick up joiners/leavers.
- **B2B guest accounts are excluded** (`#EXT#` UPNs): they are skipped on import
  and any already in the table are pruned. Pass `--include-guests` to keep them.
- The default source reuses your `az login` session — no extra permissions to grant.
- Underlying CLI: `python -m riskapp.sync_users --source graph` (or
  `--source file --file users.json` for an offline export).

---

## Detailed Usage

### Command-Line Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `-Environment` | string | required | `dev` or `prod` |
| `-Stage` | string | `all` | `all`, `infra`, `images`, or `apps` |
| `-Location` | string | `eastus` | Azure region |
| `-Prefix` | string | `riskapp` | Resource name prefix |
| `-ImageTag` | string | `latest` | Docker image tag |
| `-AcrName` | string | auto | Container Registry name |
| `-OpenAiAccountName` | string | auto | Azure OpenAI account name |
| `-ChatModelName` | string | `gpt-5.4` | Chat model name |
| `-ChatModelVersion` | string | `2026-03-05` | Chat model version |
| `-ChatModelSku` | string | `GlobalStandard` | Chat deployment SKU |
| `-ChatModelCapacity` | int | `10` | Chat capacity (thousands of TPM) |
| `-EmbeddingModelName` | string | `text-embedding-3-small` | Embedding model |
| `-OpenAiApiVersion` | string | `2025-04-01-preview` | Azure OpenAI REST API version |
| `-PostgresPassword` | SecureString | prompted | PostgreSQL admin password |
| `-UniqueSuffix` | string | auto | Unique suffix for resources |
| `-UsePrivateNetworking` | switch | false | Enable VNet and private endpoints |
| `-SkipImageBuild` | switch | false | Skip Docker image build |

### Environment Variables

The deployment scripts also respect these environment variables:

| Variable | Description |
|----------|-------------|
| `AZURE_LOCATION` | Azure region (alternative to `-Location`) |
| `APP_PREFIX` | Resource name prefix (alternative to `-Prefix`) |
| `CHAT_MODEL_NAME` / `CHAT_MODEL_VERSION` | Chat model overrides (bash script) |
| `POSTGRES_ADMIN_PASSWORD` | PostgreSQL password (skips the prompt) |
| `SKIP_IMAGE_BUILD` | `true` to skip image build/push (bash script) |
| `VITE_ENTRA_CLIENT_ID` | Entra Client ID (for frontend build) |
| `VITE_ENTRA_TENANT_ID` | Entra Tenant ID (for frontend build) |

### Examples

```powershell
# Deploy with custom prefix
.\deploy.ps1 -Environment dev -Prefix myapp

# Deploy to West US 2
.\deploy.ps1 -Environment prod -Location westus2

# Deploy only infrastructure (no images or apps)
.\deploy.ps1 -Environment dev -Stage infra

# Use existing images
.\deploy.ps1 -Environment dev -SkipImageBuild -Stage apps

# Custom PostgreSQL password via pipeline
$pw = ConvertTo-SecureString "MySecurePassword123!" -AsPlainText -Force
.\deploy.ps1 -Environment dev -PostgresPassword $pw
```

---

## Post-Deployment

### 1. Verify Deployment

```bash
# Check container app status
az containerapp show -g rg-riskapp-dev -n riskapp-dev-web --query "properties.provisioningState"

# Test health endpoint
curl https://<frontend-fqdn>/health
```

### 2. Configure Entra ID Security Groups

1. Create security groups in Entra ID:
   - `PMO Risk - System Admins`
   - `PMO Risk - PMO Leads`
   - `PMO Risk - Project Managers`

2. Get the group Object IDs:
   ```bash
   az ad group list --display-name "PMO Risk" --query "[].{name:displayName,id:objectId}" -o table
   ```

3. Update the Key Vault secret `entra-role-group-ids`:
   ```json
   {
     "System Admin": "<group-object-id>",
     "PMO Lead": "<group-object-id>",
     "Project Manager": "<group-object-id>"
   }
   ```

### 3. Update Key Vault Secrets

Required secrets in Key Vault:

| Secret Name | Description |
|-------------|-------------|
| `postgresql-connection-string` | PostgreSQL connection string |
| `postgresql-host` | PostgreSQL server hostname |
| `redis-connection-string` | Redis connection string |
| `entra-client-id` | Entra app client ID |
| `entra-tenant-id` | Entra tenant ID |
| `entra-client-secret` | Entra app client secret |
| `azure-openai-endpoint` | Azure OpenAI endpoint |
| `azure-openai-api-key` | Azure OpenAI API key |
| `azure-openai-embedding-deployment` | Embedding model deployment name |
| `azure-openai-chat-deployment` | Chat model deployment name |
| `acs-endpoint` | Azure Communication Services endpoint |
| `acs-access-key` | Azure Communication Services access key |
| `blob-account-name` | Storage account name |
| `blob-account-key` | Storage account key |

### 4. Configure Entra ID App Registration

1. Go to **Azure Portal → Entra ID → App registrations**
2. Select your app (e.g., `PMO Risk Recurrence Predictor (dev)`)
3. **Token configuration → Add groups claim**
4. Select **Security groups**
5. **Manifest** - ensure `groupMembershipClaims` is set to `"GroupMembershipClaims": "SecurityGroup"`

### 5. Update CORS Origins

Update the `CORS_ORIGINS` environment variable in the container app to include your frontend URL.

---

## Azure OpenAI Setup

### Important: Quota Requirements

Azure OpenAI is a quota-controlled service. Before deploying, ensure you have access:

1. **Request Access**: Go to [Azure OpenAI Service](https://aka.ms/azure-openai-access) and complete the intake form
2. **Wait for Approval**: Usually 1-2 business days
3. **Deploy Models**: After approval, models are auto-deployed via Bicep

### Auto-Deployed Models

| Model | Purpose | Version | SKU |
|-------|---------|---------|-----|
| **gpt-5.4** | Chat completions, risk suggestions, citation audit | 2026-03-05 | GlobalStandard |
| **text-embedding-3-small** | Semantic search, risk similarity matching | 1 | GlobalStandard |

> **Important**: GPT-5.x models do **not** support the legacy `Standard` SKU. They require a
> global or data-zone SKU (`GlobalStandard`, `DataZoneStandard`, etc.). The templates already
> default to `GlobalStandard`.
>
> To use a different chat model, override `chatModelName`, `chatModelVersion`, and
> `chatModelSkuName` (see the [Detailed Usage](#detailed-usage) section).

### Choosing a Different Chat Model

The chat model is fully parameterized. Example overrides:

| Model | Version | SKU |
|-------|---------|-----|
| `gpt-5.4` | `2026-03-05` | `GlobalStandard` |
| `gpt-5.4-mini` | `2026-03-17` | `GlobalStandard` |
| `gpt-5.4-nano` | `2026-03-17` | `GlobalStandard` |
| `gpt-5.2` | `2025-12-11` | `GlobalStandard` |
| `gpt-4.1-mini` | `2025-04-14` | `Standard` |

```powershell
# PowerShell example: use gpt-5.4-mini
.\deploy.ps1 -Environment dev -ChatModelName gpt-5.4-mini -ChatModelVersion 2026-03-17
```

```bash
# Bash example: use gpt-5.4-mini
CHAT_MODEL_NAME=gpt-5.4-mini CHAT_MODEL_VERSION=2026-03-17 bash deploy.sh dev
```

> **Application compatibility**: GPT-5.x models use `max_completion_tokens` instead of the
> deprecated `max_tokens`, ignore `temperature`/`top_p` on reasoning paths, and support
> `reasoning_effort`. Verify the backend LLM client handles these differences before
> switching the production chat model.

### Post-Deployment Verification

```bash
# Verify OpenAI account exists
az cognitiveservices account show \
  --name "riskapp-dev-openai" \
  --resource-group "rg-riskapp-dev"

# List deployed models
az cognitiveservices account deployment list \
  --name "riskapp-dev-openai"
```

### Key Vault Secrets (Auto-Stored)

After deployment, these secrets are automatically stored in Key Vault:

| Secret Name | Description |
|-------------|-------------|
| `azure-openai-api-key` | API key for OpenAI |
| `azure-openai-endpoint` | Full endpoint URL |
| `azure-openai-chat-deployment` | Chat deployment name (e.g. `gpt-5.4`) |
| `azure-openai-embedding-deployment` | Embedding deployment name |

### Manual Model Deployment (if auto-deploy fails)

If the Bicep template doesn't auto-deploy models:

```bash
# Deploy gpt-5.4 (note: GlobalStandard SKU, not Standard)
az cognitiveservices account deployment create \
  --name "riskapp-dev-openai" \
  --resource-group "rg-riskapp-dev" \
  --deployment-name "gpt-5.4" \
  --model-name "gpt-5.4" \
  --model-version "2026-03-05" \
  --model-format "OpenAI" \
  --sku-name "GlobalStandard" \
  --sku-capacity 10

# Deploy text-embedding-3-small
az cognitiveservices account deployment create \
  --name "riskapp-dev-openai" \
  --resource-group "rg-riskapp-dev" \
  --deployment-name "text-embedding-3-small" \
  --model-name "text-embedding-3-small" \
  --model-version "1" \
  --model-format "OpenAI" \
  --sku-name "GlobalStandard" \
  --sku-capacity 10
```

---

## Troubleshooting

### Container App Not Starting

```bash
# Check revision logs
az containerapp revision list -g rg-riskapp-dev -n riskapp-dev-web --query "[0].properties.logs"

# Get deployment status
az containerapp show -g rg-riskapp-dev -n riskapp-dev-web --query "properties.template"
```

### Database Connection Issues

```bash
# Test PostgreSQL connectivity
az postgres flexible-server execute \
  -g rg-riskapp-dev \
  -s riskapp-dev-postgres \
  -d riskapp \
  -q "SELECT 1;"

# Check firewall rules
az postgres flexible-server firewall-rule list -g rg-riskapp-dev -s riskapp-dev-postgres -o table
```

### Image Pull Failures

```bash
# Verify ACR credentials
az acr credential show -n riskappdevacr

# Check image exists
az acr repository show -n riskappdevacr --image riskapp-backend:latest
```

### Key Vault Access Issues

```bash
# Check current user has access
az keyvault show --name riskapp-dev-kv --query "properties.accessPolicies"

# Grant yourself Key Vault Administrator role
az role assignment create \
  --role "Key Vault Administrator" \
  --assignee $(az ad signed-in-user show --query id -o tsv) \
  --scope $(az keyvault show --name riskapp-dev-kv --query id -o tsv)
```

---

## Cost Estimation

### Estimated Monthly Costs (Pay-as-you-go)

| Service | Tier | Est. Monthly |
|---------|------|-------------|
| Container Apps | Consumption | $5-50 |
| PostgreSQL Flexible Server | Burstable B2s | $50-80 |
| Azure Cache for Redis | Basic C0 | $20-30 |
| Blob Storage | Standard LRS | $5 |
| Key Vault | Standard | $3 |
| Container Registry | Basic | $5 |
| Azure OpenAI | S0 (Pay-as-you-go) | $50-200 |
| Log Analytics | Pay-as-you-go | $10 |
| **Total** | | **~$150-380/month** |

### Cost Optimization Tips

1. **Scale to zero**: Container Apps can scale to zero outside business hours
2. **Use Burstable tier**: PostgreSQL B2s is sufficient for most workloads
3. **Monitor usage**: Use Azure Cost Management to track spending
4. **Reserve instances**: Consider reserved capacity for production

---

## File Structure

```
infra/
├── main-complete.bicep      # Full deployment (infra + apps) — used by deploy.sh/.ps1
├── main.bicep               # Deploy any service (web/worker/beat/frontend) — used by deploy-service.*
├── deploy.sh                # Full deployment (bash)
├── deploy.ps1               # Full deployment (PowerShell)
├── deploy-service.sh        # Per-service deployment (bash)
├── deploy-service.ps1       # Per-service deployment (PowerShell)
├── generate-deploy-env.sh   # Rebuild deploy.<env>.env from live Azure
├── register-entra-app.sh    # Entra app registration / SSO keys
├── sync-entra-users.sh      # Import Entra users into the users table
├── deploy.<env>.env         # Runtime config + secrets (git-ignored, generated)
├── deployment-info-*.json   # Deployment output files (generated)
├── README.md                # This file
├── RUNBOOK.md               # Which script to run when (start here)
└── modules/
    ├── container-app.bicep  # Container App                    (used by main.bicep)
    ├── environment.bicep    # Container Apps Environment + Log Analytics (used by main.bicep)
    ├── registry.bicep       # Container Registry               (used by main.bicep)
    ├── entra.bicep          # Entra ID app registration reference
    ├── keyvault.bicep       # Key Vault + RBAC
    ├── network.bicep        # Virtual Network + subnets
    ├── openai.bicep         # Azure OpenAI + model deployments
    ├── postgres.bicep       # PostgreSQL Flexible Server + pgvector
    ├── redis.bicep          # Azure Cache for Redis
    └── storage.bicep        # Blob Storage
```

> Only the first three modules are referenced by `main.bicep` (the per-service
> deploy path). The rest are pulled in by `main-complete.bicep`, which is the
> **only** template that provisions Postgres, Redis, OpenAI, Storage, Key Vault
> and the VNet — i.e. what you use to stand the environment up from scratch.

---

## Security Considerations

1. **Use Managed Identity**: Container Apps use user-assigned managed identity for Azure resource access
2. **Key Vault RBAC**: Key Vault uses RBAC (not access policies) for fine-grained permissions
3. **TLS 1.2+**: All services require TLS 1.2 minimum
4. **No public passwords**: Secrets are stored in Key Vault, not in environment variables
5. **Private networking** (optional): Use VNet and private endpoints for additional isolation

---

## Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section above
2. Review Azure Portal diagnostic logs
3. Check container app logs in Azure Portal or via CLI:
   ```bash
   az containerapp logs show -g rg-riskapp-dev -n riskapp-dev-web --follow
   ```
