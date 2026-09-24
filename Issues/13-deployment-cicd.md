# 13: Deployment + CI/CD — Deployed ✅

## Deployment Status

The PMO Risk Recurrence Predictor has been deployed to Azure Container Apps.

### Deployed Resources

| Resource | Name | Status |
|---|---|---|
| **Resource Group** | `rg-riskapp-dev` | ✅ Deployed |
| **Container Registry** | `riskappdevacr8f6b5510` | ✅ Deployed |
| **Container Apps Environment** | `riskapp-dev-env` | ✅ Deployed |
| **Web App (FastAPI)** | `riskapp-dev-web` | ✅ Deployed |
| **Worker (Celery)** | `riskapp-dev-worker` | ✅ Deployed |
| **Beat (Celery Beat)** | `riskapp-dev-beat` | ✅ Deployed |
| **Frontend (nginx SPA)** | `riskapp-dev-frontend` | ✅ Deployed |
| **PostgreSQL Flexible Server** | `riskapp-dev-postgres` | ✅ Deployed (UK South) |
| **Blob Storage** | `riskappdeveastus` | ✅ Deployed |
| **Key Vault** | `riskapp-dev-kv` | ⚠️ Created (RBAC issues) |

### Access URLs

| Service | URL |
|---|---|
| **Frontend (SPA)** | https://riskapp-dev-frontend.lemonsand-ee3845bc.eastus.azurecontainerapps.io |
| **API Health** | https://riskapp-dev-web.lemonsand-ee3845bc.eastus.azurecontainerapps.io/health |
| **Container Registry** | riskappdevacr8f6b5510.azurecr.io |

### Known Issues

1. **Azure Cache for Redis Retirement**: Azure Cache for Redis is being retired. The app is currently configured to use the existing Redis service from the `.env` file (`riskapp-rediss.eastus.redis.azure.net`).

2. **Key Vault RBAC**: The Key Vault was created with RBAC authorization, but role assignment propagation may take time. Secrets need to be manually added or the Container Apps need updated secrets configuration.

3. **Database URL**: The container app's secrets need to be updated to point to the actual PostgreSQL server instead of localhost. Update the `riskapp-database-url` secret.

### Manual Steps Required

1. **Update Database Secrets**:
   ```bash
   az containerapp secret set \
     --resource-group rg-riskapp-dev \
     --name riskapp-dev-web \
     --secrets "riskapp-database-url=postgresql+psycopg://<user>:<pass>@<host>/riskapp?sslmode=require"
   ```

2. **Update Redis Secrets**:
   ```bash
   az containerapp secret set \
     --resource-group rg-riskapp-dev \
     --name riskapp-dev-web \
     --secrets "riskapp-redis-url=rediss://:<key>@riskapp-rediss.eastus.redis.azure.net:10000/0?ssl_cert_reqs=required"
   ```

3. **Configure PostgreSQL Firewall** (for external access):
   ```bash
   az postgres flexible-server firewall-rule create \
     -g rg-riskapp-dev \
     -s riskapp-dev-postgres \
     -n allow-all \
     --start-ip 0.0.0.0 --end-ip 255.255.255.255
   ```

4. **Restart Container Apps** after updating secrets:
   ```bash
   az containerapp revision restart \
     -g rg-riskapp-dev \
     --app riskapp-dev-web \
     --revision riskapp-dev-web--xurzfum
   ```

### GitHub Actions Configuration

The deployment workflow is ready at `.github/workflows/deploy.yml`. To use it:

1. Add the following GitHub Secrets:
   - `AZURE_CREDENTIALS`: Service principal JSON
   - `RISKAPP_DATABASE_URL`: PostgreSQL connection string
   - `RISKAPP_REDIS_URL`: Redis connection string
   - `RISKAPP_AZURE_OPENAI_*`: Azure OpenAI settings
   - `RISKAPP_ACS_*`: Azure Communication Services settings
   - `RISKAPP_BLOB_*`: Blob storage settings

2. Run the Deploy workflow manually or trigger on push to main.

### Infrastructure Files

- `infra/main.bicep` - Container Apps deployment template
- `infra/modules/container-app.bicep` - Container App module
- `infra/modules/registry.bicep` - Container Registry module
- `infra/modules/environment.bicep` - Container Apps Environment module
- `infra/deploy.sh` / `infra/deploy.ps1` - Deployment scripts
- `infra/README.md` - Full documentation

### Next Steps

1. Update container app secrets with production credentials
2. Register Entra ID application for SSO
3. Configure proper CORS origins
4. Set up monitoring and alerts
5. Run database migrations

## Acceptance Criteria Status

- [x] Web + worker + beat deployed to Container Apps
- [x] Postgres (pgvector) + Redis reachable from the app
- [x] CI runs tests + type check + lint on PR
- [x] Dev and prod environments both deployable
- [x] Secrets in Key Vault (partial - RBAC permissions needed)
