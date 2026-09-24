#!/usr/bin/env bash
# =============================================================================
# PMO Risk Recurrence Predictor - Complete Azure Deployment Script
# =============================================================================
#
# Deploys the whole solution to Azure. Idempotent - safe to re-run at any time
# against any Azure subscription/account with sufficient permissions.
#
# REQUIREMENTS:
#   - Azure CLI (az), authenticated via `az login`
#   - Docker (for building/pushing images)
#   - Permissions: Contributor + User Access Administrator on the subscription
#     (or Owner), so role assignments and Key Vault RBAC can be created
#
# USAGE:
#   bash infra/deploy.sh dev                     # full deployment
#   bash infra/deploy.sh prod --stage all
#   bash infra/deploy.sh dev --stage infra       # infrastructure only
#   bash infra/deploy.sh dev --stage images      # build + push images
#   bash infra/deploy.sh dev --stage apps        # deploy/refresh container apps
#   bash infra/deploy.sh dev --location westus2
#   bash infra/deploy.sh dev --use-private-networking
#
# STAGES:
#   all     : infra -> images -> apps (default)
#   infra   : resource group + infrastructure (no container apps)
#   images  : build + push Docker images
#   apps    : (re)deploy container apps (runs the template with deployApps=true)
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"

usage() {
    sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
}

[[ $# -lt 1 ]] && usage

ENV_NAME="$1"
shift

# ---- Defaults (overridable by environment variables) ------------------------
STAGE="all"
IMAGE_TAG="${IMAGE_TAG:-latest}"
LOCATION="${AZURE_LOCATION:-eastus}"
PREFIX="${APP_PREFIX:-riskapp}"
ACR_NAME="${ACR_NAME:-}"
OPENAI_ACCOUNT_NAME="${OPENAI_ACCOUNT_NAME:-}"
UNIQUE_SUFFIX="${UNIQUE_SUFFIX:-}"
POSTGRES_ADMIN_PASSWORD="${POSTGRES_ADMIN_PASSWORD:-}"
POSTGRES_ADMIN_USER="${POSTGRES_ADMIN_USER:-riskappadmin}"
POSTGRES_STORAGE_GB="${POSTGRES_STORAGE_GB:-32}"
REDIS_SKU="${REDIS_SKU:-Basic}"
REDIS_CAPACITY="${REDIS_CAPACITY:-0}"
CHAT_MODEL_NAME="${CHAT_MODEL_NAME:-gpt-5.4}"
CHAT_MODEL_VERSION="${CHAT_MODEL_VERSION:-2026-03-05}"
CHAT_MODEL_SKU="${CHAT_MODEL_SKU:-GlobalStandard}"
CHAT_MODEL_CAPACITY="${CHAT_MODEL_CAPACITY:-10}"
EMBEDDING_MODEL_NAME="${EMBEDDING_MODEL_NAME:-text-embedding-3-small}"
EMBEDDING_MODEL_SKU="${EMBEDDING_MODEL_SKU:-GlobalStandard}"
EMBEDDING_MODEL_CAPACITY="${EMBEDDING_MODEL_CAPACITY:-10}"
OPENAI_API_VERSION="${OPENAI_API_VERSION:-2025-04-01-preview}"
CORS_ORIGINS="${CORS_ORIGINS:-*}"
USE_PRIVATE_NETWORKING="${USE_PRIVATE_NETWORKING:-false}"
SKIP_IMAGE_BUILD="${SKIP_IMAGE_BUILD:-false}"

BACKEND_IMAGE="riskapp-backend"
FRONTEND_IMAGE="riskapp-frontend"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stage) STAGE="$2"; shift 2 ;;
        --image-tag) IMAGE_TAG="$2"; shift 2 ;;
        --location) LOCATION="$2"; shift 2 ;;
        --prefix) PREFIX="$2"; shift 2 ;;
        --acr-name) ACR_NAME="$2"; shift 2 ;;
        --openai-account) OPENAI_ACCOUNT_NAME="$2"; shift 2 ;;
        --chat-model) CHAT_MODEL_NAME="$2"; CHAT_MODEL_VERSION="$3"; shift 3 ;;
        --postgres-password) POSTGRES_ADMIN_PASSWORD="$2"; shift 2 ;;
        --unique-suffix) UNIQUE_SUFFIX="$2"; shift 2 ;;
        --use-private-networking) USE_PRIVATE_NETWORKING="true" ;;
        --skip-image-build) SKIP_IMAGE_BUILD="true" ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

case "$STAGE" in all|infra|images|apps) ;; *) echo "Invalid --stage: $STAGE"; exit 1 ;; esac

# ---- Output helpers ---------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; NC='\033[0m'
info()    { echo -e "${CYAN}==>${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# =============================================================================
# PREREQUISITES
# =============================================================================

info "Checking prerequisites..."
command -v az     >/dev/null || error "Azure CLI (az) not found."
command -v docker >/dev/null || error "Docker not found."
docker info       >/dev/null 2>&1 || error "Docker is not running."

az account show >/dev/null 2>&1 || error "Not authenticated. Run 'az login'."
ACCOUNT_NAME=$(az account show --query name -o tsv)
ACCOUNT_USER=$(az account show --query user.name -o tsv)
ACCOUNT_TENANT=$(az account show --query tenantId -o tsv)
ACCOUNT_ID=$(az account show --query id -o tsv)

success "Authenticated as $ACCOUNT_USER"
info "Subscription: $ACCOUNT_NAME ($ACCOUNT_ID)"
info "Tenant: $ACCOUNT_TENANT"

az bicep install >/dev/null 2>&1 || true

# =============================================================================
# NAMING
# =============================================================================

RG="rg-${PREFIX}-${ENV_NAME}"

if [[ -z "$UNIQUE_SUFFIX" ]]; then
    UNIQUE_SUFFIX=$(printf '%s' "$ACCOUNT_ID" | tr -d '-' | tail -c 8 | tr '[:upper:]' '[:lower:]')
fi

[[ -z "$ACR_NAME" ]] && ACR_NAME="${PREFIX}${ENV_NAME}acr${UNIQUE_SUFFIX}"
[[ -z "$OPENAI_ACCOUNT_NAME" ]] && OPENAI_ACCOUNT_NAME="${PREFIX}-${ENV_NAME}-openai${UNIQUE_SUFFIX}"

ACR_SERVER="${ACR_NAME}.azurecr.io"
KEYVAULT_NAME="${PREFIX}-${ENV_NAME}-kv"
STORAGE_ACCOUNT="${PREFIX}${ENV_NAME}sa${UNIQUE_SUFFIX}"
POSTGRES_SERVER="${PREFIX}-${ENV_NAME}-postgres${UNIQUE_SUFFIX}"
REDIS_CACHE="${PREFIX}-${ENV_NAME}-redis${UNIQUE_SUFFIX}"
WEB_APP="${PREFIX}-${ENV_NAME}-web"
WORKER_APP="${PREFIX}-${ENV_NAME}-worker"
BEAT_APP="${PREFIX}-${ENV_NAME}-beat"
FRONTEND_APP="${PREFIX}-${ENV_NAME}-frontend"

if [[ -z "$POSTGRES_ADMIN_PASSWORD" ]]; then
    read -r -p "Enter PostgreSQL admin password (min 8 chars): " -s POSTGRES_ADMIN_PASSWORD
    echo ""
fi
[[ ${#POSTGRES_ADMIN_PASSWORD} -lt 8 ]] && error "PostgreSQL password must be at least 8 characters."

# =============================================================================
# BICEP DEPLOYMENT (shared by the infra and apps stages)
# =============================================================================

deploy_bicep() {
    local deploy_apps="$1"
    local kind; [[ "$deploy_apps" == "true" ]] && kind="apps" || kind="infra"
    local deployment_name="${PREFIX}-${ENV_NAME}-${kind}-$(date +%Y%m%d%H%M%S)"
    local current_user
    current_user=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || echo "")

    info "Deploying template (deployApps=${deploy_apps}) as '${deployment_name}'..."
    az deployment group create \
        --resource-group "$RG" \
        --name "$deployment_name" \
        --template-file "$SCRIPT_DIR/main-complete.bicep" \
        --parameters \
            environmentName="$ENV_NAME" \
            location="$LOCATION" \
            prefix="$PREFIX" \
            acrName="$ACR_NAME" \
            imageTag="$IMAGE_TAG" \
            backendImageName="$BACKEND_IMAGE" \
            frontendImageName="$FRONTEND_IMAGE" \
            deployApps="$deploy_apps" \
            postgresAdminUsername="$POSTGRES_ADMIN_USER" \
            postgresAdminPassword="$POSTGRES_ADMIN_PASSWORD" \
            postgresStorageGb="$POSTGRES_STORAGE_GB" \
            redisSkuName="$REDIS_SKU" \
            redisCapacity="$REDIS_CAPACITY" \
            keyVaultName="$KEYVAULT_NAME" \
            storageAccountName="$STORAGE_ACCOUNT" \
            uniqueSuffix="$UNIQUE_SUFFIX" \
            usePrivateNetworking="$USE_PRIVATE_NETWORKING" \
            keyVaultAdminObjectId="$current_user" \
            openAiAccountName="$OPENAI_ACCOUNT_NAME" \
            chatModelName="$CHAT_MODEL_NAME" \
            chatModelVersion="$CHAT_MODEL_VERSION" \
            chatModelDeploymentName="$CHAT_MODEL_NAME" \
            chatModelSkuName="$CHAT_MODEL_SKU" \
            chatModelCapacity="$CHAT_MODEL_CAPACITY" \
            embeddingModelDeploymentName="$EMBEDDING_MODEL_NAME" \
            embeddingModelSkuName="$EMBEDDING_MODEL_SKU" \
            embeddingModelCapacity="$EMBEDDING_MODEL_CAPACITY" \
            azureOpenAiApiVersion="$OPENAI_API_VERSION" \
            corsOrigins="$CORS_ORIGINS" \
        --output none \
        || error "Bicep deployment failed. Inspect: az deployment group show -g $RG -n $deployment_name"
    success "Template deployed (deployApps=${deploy_apps})"
}

# =============================================================================
# STAGE: INFRA
# =============================================================================

if [[ "$STAGE" == "all" || "$STAGE" == "infra" ]]; then
    info "Ensuring resource group '$RG' in $LOCATION..."
    if az group show --name "$RG" >/dev/null 2>&1; then
        success "Resource group exists: $RG"
    else
        az group create --name "$RG" --location "$LOCATION" --output none
        success "Resource group created: $RG"
    fi

    deploy_bicep false
fi

# =============================================================================
# STAGE: IMAGES
# =============================================================================

if [[ "$SKIP_IMAGE_BUILD" != "true" ]] && [[ "$STAGE" == "all" || "$STAGE" == "images" ]]; then
    info "Building and pushing images to $ACR_SERVER..."
    az acr login --name "$ACR_NAME" >/dev/null || error "az acr login failed"

    info "Building backend image..."
    docker build -t "${ACR_SERVER}/${BACKEND_IMAGE}:${IMAGE_TAG}" "$BACKEND_DIR" || error "Backend build failed"
    docker push "${ACR_SERVER}/${BACKEND_IMAGE}:${IMAGE_TAG}"                     || error "Backend push failed"
    success "Pushed ${ACR_SERVER}/${BACKEND_IMAGE}:${IMAGE_TAG}"

    info "Building frontend image..."
    build_args=()
    [[ -n "${VITE_ENTRA_CLIENT_ID:-}" ]] && build_args+=(--build-arg "VITE_ENTRA_CLIENT_ID=${VITE_ENTRA_CLIENT_ID}")
    [[ -n "${VITE_ENTRA_TENANT_ID:-}" ]] && build_args+=(--build-arg "VITE_ENTRA_TENANT_ID=${VITE_ENTRA_TENANT_ID}")
    docker build "${build_args[@]}" -t "${ACR_SERVER}/${FRONTEND_IMAGE}:${IMAGE_TAG}" "$FRONTEND_DIR" || error "Frontend build failed"
    docker push "${ACR_SERVER}/${FRONTEND_IMAGE}:${IMAGE_TAG}"                                      || error "Frontend push failed"
    success "Pushed ${ACR_SERVER}/${FRONTEND_IMAGE}:${IMAGE_TAG}"
fi

# =============================================================================
# STAGE: APPS
# =============================================================================

if [[ "$STAGE" == "all" || "$STAGE" == "apps" ]]; then
    deploy_bicep true
fi

# =============================================================================
# ENTRA ID APP REGISTRATION
# =============================================================================

info "Checking Entra ID app registration..."
ENTRA_APP_NAME="PMO Risk Recurrence Predictor (${ENV_NAME})"
ENTRA_TENANT_ID="$ACCOUNT_TENANT"
ENTRA_CLIENT_ID=""

ENTRA_CLIENT_ID=$(az ad app list --display-name "$ENTRA_APP_NAME" --query "[0].appId" -o tsv 2>/dev/null || echo "")
if [[ -n "$ENTRA_CLIENT_ID" ]]; then
    success "Entra app already exists: $ENTRA_CLIENT_ID"
else
    FRONTEND_URL=$(az containerapp show -g "$RG" -n "$FRONTEND_APP" \
        --query 'properties.configuration.ingress.fqdn' -o tsv 2>/dev/null || echo "")
    if [[ -n "$FRONTEND_URL" ]]; then
        ENTRA_CALLBACK="https://${FRONTEND_URL}"
    else
        ENTRA_CALLBACK="http://localhost:5173"
    fi

    info "Creating Entra app registration..."
    if ENTRA_CLIENT_ID=$(az ad app create \
            --display-name "$ENTRA_APP_NAME" \
            --web-redirect-uris "$ENTRA_CALLBACK" \
            --enable-access-token-issuance true \
            --enable-id-token-issuance true \
            --sign-audience AzureADMyOrg \
            --query appId -o tsv 2>/dev/null) && [[ -n "$ENTRA_CLIENT_ID" ]]; then
        success "Entra app created: $ENTRA_CLIENT_ID"

        SECRET_VALUE=$(az ad app credential reset --id "$ENTRA_CLIENT_ID" --append \
            --query password -o tsv 2>/dev/null || echo "")
        if [[ -n "$SECRET_VALUE" ]]; then
            az keyvault secret set --vault-name "$KEYVAULT_NAME" \
                --name 'entra-client-secret' --value "$SECRET_VALUE" --output none \
                && success "Client secret stored in Key Vault" \
                || warn "Could not store client secret in Key Vault"
        else
            warn "Could not create Entra client secret"
        fi
    else
        ENTRA_CLIENT_ID=""
        warn "Could not create Entra app registration (need Application Administrator)"
    fi
fi

if [[ -n "$ENTRA_CLIENT_ID" ]]; then
    az keyvault secret set --vault-name "$KEYVAULT_NAME" --name 'entra-client-id'   --value "$ENTRA_CLIENT_ID"   --output none 2>/dev/null || true
    az keyvault secret set --vault-name "$KEYVAULT_NAME" --name 'entra-tenant-id'   --value "$ENTRA_TENANT_ID"   --output none 2>/dev/null || true
    success "Entra configuration stored in Key Vault"
fi

# =============================================================================
# SUMMARY
# =============================================================================

WEB_FQDN=$(az containerapp show -g "$RG" -n "$WEB_APP" \
    --query 'properties.configuration.ingress.fqdn' -o tsv 2>/dev/null || echo "")
FRONTEND_FQDN=$(az containerapp show -g "$RG" -n "$FRONTEND_APP" \
    --query 'properties.configuration.ingress.fqdn' -o tsv 2>/dev/null || echo "")
OPENAI_ENDPOINT=$(az cognitiveservices account show -g "$RG" -n "$OPENAI_ACCOUNT_NAME" \
    --query 'properties.endpoint' -o tsv 2>/dev/null || echo "")

cat <<EOF

$(echo -e "${MAGENTA}")==============================================================================
DEPLOYMENT COMPLETE
==============================================================================$(echo -e "${NC}")
Resource group : $RG
Location       : $LOCATION

Endpoints
---------
Frontend       : ${FRONTEND_FQDN:+https://$FRONTEND_FQDN}
API health     : ${WEB_FQDN:+https://$WEB_FQDN/health}
API docs       : ${WEB_FQDN:+https://$WEB_FQDN/docs}

Azure resources
---------------
Container Registry : ${ACR_SERVER}
Key Vault          : ${KEYVAULT_NAME}
PostgreSQL         : ${POSTGRES_SERVER}
Redis              : ${REDIS_CACHE}
Storage account    : ${STORAGE_ACCOUNT}
Azure OpenAI       : ${OPENAI_ACCOUNT_NAME}

Models
------
Chat               : ${CHAT_MODEL_NAME} (${CHAT_MODEL_VERSION}, ${CHAT_MODEL_SKU})
Embeddings         : ${EMBEDDING_MODEL_NAME} (${EMBEDDING_MODEL_SKU})
Endpoint           : ${OPENAI_ENDPOINT}

Entra ID
--------
App registration   : ${ENTRA_APP_NAME}
Client ID          : ${ENTRA_CLIENT_ID:-<not created>}
Tenant ID          : ${ENTRA_TENANT_ID}
Callback URL       : ${ENTRA_CALLBACK:-<frontend URL>}

Images
------
Backend            : ${ACR_SERVER}/${BACKEND_IMAGE}:${IMAGE_TAG}
Frontend           : ${ACR_SERVER}/${FRONTEND_IMAGE}:${IMAGE_TAG}

Next steps
----------
1. Create Entra security groups and store their IDs in the 'entra-role-group-ids' secret.
2. Set remaining secrets (ACS, blob) - see infra/README.md.
3. If the frontend was built before the Entra app existed, rebuild it with
   VITE_ENTRA_CLIENT_ID / VITE_ENTRA_TENANT_ID and re-run --stage images.
EOF

cat > "$SCRIPT_DIR/deployment-info-${ENV_NAME}.json" <<JSON
{
  "resourceGroup": "$RG",
  "location": "$LOCATION",
  "environment": "$ENV_NAME",
  "frontendUrl": "${FRONTEND_FQDN:+https://$FRONTEND_FQDN}",
  "apiUrl": "${WEB_FQDN:+https://$WEB_FQDN}",
  "acrServer": "$ACR_SERVER",
  "keyVaultName": "$KEYVAULT_NAME",
  "openAiAccountName": "$OPENAI_ACCOUNT_NAME",
  "openAiEndpoint": "$OPENAI_ENDPOINT",
  "openAiChatModel": "$CHAT_MODEL_NAME",
  "openAiChatModelVersion": "$CHAT_MODEL_VERSION",
  "openAiEmbeddingModel": "$EMBEDDING_MODEL_NAME",
  "entraClientId": "$ENTRA_CLIENT_ID",
  "entraTenantId": "$ENTRA_TENANT_ID",
  "deploymentDate": "$(date -Iseconds)"
}
JSON
success "Deployment info written to deployment-info-${ENV_NAME}.json"
