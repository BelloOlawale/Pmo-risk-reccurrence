# Azure Container Apps deployment

Deploys the PMO Risk Recurrence Predictor to **Azure Container Apps**
(consumption plan) using Bicep. This is the container-hosting layer for
issue #13 — the data-plane services (PostgreSQL, Redis, Azure OpenAI, ACS,
Blob Storage) already exist and are referenced by `backend/.env`.

## Topology

One resource group per environment (`rg-riskapp-{dev|prod}`) containing:

| Resource | Purpose |
|---|---|
| `riskapp{env}acr` | Azure Container Registry (admin account enabled for image pulls) |
| `riskapp-{env}-env` | Container Apps environment (consumption) + Log Analytics |
| `riskapp-{env}-web` | FastAPI + `alembic upgrade head` on start. Public HTTPS. |
| `riskapp-{env}-worker` | Celery worker (no ingress) |
| `riskapp-{env}-beat` | Celery beat (no ingress, min 1 replica) |
| `riskapp-{env}-frontend` | nginx SPA. Public HTTPS. Proxies `/api` → web container app (`API_UPSTREAM` env var) |

The browser only ever talks to the frontend origin (same-origin `/api`), so no
CORS issues between the SPA and the API.

```
Browser ──https──▶ frontend (nginx SPA, public)
                       │ /api proxy (nginx → web FQDN)
                       ▼
                   web (FastAPI, public HTTPS)
                   worker / beat (internal, no ingress)
```

## Prerequisites

- `az login` with an account that has **Contributor** (or Owner) on the target
  subscription / resource group.
- `docker` for the `images` stage.
- `az bicep install` once (the CLI auto-compiles the templates).
- Bicep requires the **Microsoft.App** and **Microsoft.ContainerRegistry**
  providers registered on the subscription (both already are).

For the GitHub Actions workflow the service principal needs **Contributor** on
the resource group (deploys) **and AcrPush** on the registry (image pushes).
`az acr login`/`docker push` authenticate with the AAD identity, so
Contributor alone is not enough to push images.

## Runtime configuration

All `RISKAPP_*` values are read, highest-priority first, from:

1. environment variables, then
2. `backend/.env`

and are stored as container-app secrets, exposed as env vars of the same name
on every deployed app (`infra/make_params.py` builds the parameter file).
`RISKAPP_ENVIRONMENT` is set to the environment name (`dev`/`prod`) by the
template. `RISKAPP_APP_BASE_URL` and `RISKAPP_CORS_ORIGINS` (plain env vars)
are passed through when present.

> **Note:** the current template passes values as container-app secrets. The
> cleaner end state is Key Vault references — swap the `secrets` array for
> `keyVaultUrl`/managed identity entries when hardening.

## Deploy

From the repo root:

```bash
# Everything (infra -> images -> apps) using the current backend/.env values
bash infra/deploy.sh dev --image-tag latest

# Or PowerShell on Windows
.\infra\deploy.ps1 dev -Stage all
```

Staged (used by CI, also useful when iterating):

```bash
bash infra/deploy.sh dev --stage infra     # RG + ACR + environment
bash infra/deploy.sh dev --stage images    # build + push images to ACR
bash infra/deploy.sh dev --stage apps      # create/update the 4 container apps
```

Overridable naming/config: `--location`, `--prefix`, `--acr-name`,
`--image-tag`, and env vars `APP_PREFIX`, `ACR_NAME`, `AZURE_LOCATION`,
`VITE_API_BASE_URL`, `VITE_ENTRA_CLIENT_ID`, `VITE_ENTRA_TENANT_ID`
(frontend build args, optional).

The deploy finishes by printing the SPA URL and the API health URL.

## GitHub Actions

`.github/workflows/deploy.yml` runs the same stages on demand
(`workflow_dispatch` with `dev`/`prod`). It needs these repo secrets:

| Secret | Purpose |
|---|---|
| `AZURE_CREDENTIALS` | JSON service principal with Contributor on the target RG/subscription |
| `RISKAPP_DATABASE_URL`, `RISKAPP_REDIS_URL`, `RISKAPP_AZURE_OPENAI_*`, `RISKAPP_ACS_*`, `RISKAPP_BLOB_*`, `RISKAPP_ENTRA_*` | Runtime values (same names as `backend/.env`) |
| `VITE_ENTRA_CLIENT_ID`, `VITE_ENTRA_TENANT_ID` (optional) | Enable Entra SSO in the SPA build |

and optionally the repo variables `AZURE_LOCATION`, `RISKAPP_APP_BASE_URL`,
`RISKAPP_CORS_ORIGINS`.

## Post-deploy checklist

1. **PostgreSQL firewall** — allow the Container Apps environment's outbound IPs
   (or enable “Allow public access from any Azure service”) so `web`/`worker`
   can reach the Flexible Server.
2. **Entra app registration (SSO)** — add the frontend URL
   `https://<frontend-fqdn>` as a SPA redirect URI, and point the
   `RISKAPP_ENTRA_*` secrets at the right groups/client.
3. **Health check** — open `https://<web-fqdn>/health` and sign in via the SPA.
4. **Scale to zero (later)** — replace the `minReplicas` defaults with KEDA
   rules (worker on the Redis queue length; web cold-start acceptable off-hours).

## Teardown

```bash
az group delete --name rg-riskapp-dev --yes --no-wait
```
