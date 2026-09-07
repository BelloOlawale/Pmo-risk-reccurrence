#!/usr/bin/env bash
# Deploy the PMO Risk Recurrence Predictor to Azure Container Apps.
#
# Prereqs: authenticated az CLI with Contributor on the target subscription/RG,
# docker available for the `images` stage. Bicep is auto-compiled by az (run
# `az bicep install` first if missing).
#
# Usage (from the repo root):
#   bash infra/deploy.sh <dev|prod> [--stage all|infra|images|apps]
#                          [--image-tag TAG] [--location LOC] [--prefix PREFIX]
#                          [--acr-name NAME]
#
# Stages:
#   infra  create resource group + ACR + Container Apps environment (no apps)
#   images build & push the backend and frontend images to ACR
#   apps   deploy the four container apps (web/worker/beat/frontend)
#   all    infra -> images -> apps (default)
#
# Configuration (see infra/README.md): runtime values come from RISKAPP_* env
# vars or backend/.env; naming can be overridden with APP_PREFIX / ACR_NAME /
# AZURE_LOCATION. VITE_ENTRA_* build args enable Entra SSO in the SPA build.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <dev|prod> [--stage all|infra|images|apps] [--image-tag TAG] [--acr-name NAME]"
  exit 2
fi

ENV_NAME="$1"
shift

STAGE="all"
IMAGE_TAG="${IMAGE_TAG:-}"
LOCATION="${AZURE_LOCATION:-eastus}"
PREFIX="${APP_PREFIX:-riskapp}"
ACR_NAME="${ACR_NAME:-}"
BACKEND_IMAGE="${BACKEND_IMAGE:-riskapp-backend}"
FRONTEND_IMAGE="${FRONTEND_IMAGE:-riskapp-frontend}"
DEPLOY_APPEND="$(date +%s)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stage) STAGE="$2"; shift 2 ;;
    --image-tag) IMAGE_TAG="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --acr-name) ACR_NAME="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$STAGE" in all|infra|images|apps) ;; *) echo "invalid --stage $STAGE" >&2; exit 2 ;; esac

RG="rg-${PREFIX}-${ENV_NAME}"
if [[ -z "$ACR_NAME" ]]; then
  SUB_ID="$(az account show --query id -o tsv | tr -d '-')"
  ACR_NAME="${PREFIX}${ENV_NAME}acr${SUB_ID: -8}"
fi
ACR_SERVER="${ACR_NAME}.azurecr.io"
IMAGE_TAG="${IMAGE_TAG:-latest}"

params_file="$(mktemp)"
trap 'rm -f "$params_file"' EXIT

make_params() {
  local deploy_apps="$1"
  local py=python3
  command -v "$py" >/dev/null 2>&1 || py=python
  "$py" "$SCRIPT_DIR/make_params.py" \
    --environment-name "$ENV_NAME" \
    --prefix "$PREFIX" \
    --location "$LOCATION" \
    --acr-name "$ACR_NAME" \
    --image-tag "$IMAGE_TAG" \
    --deploy-apps "$deploy_apps" \
    --output "$params_file"
}

phase_infra() {
  echo "==> [$ENV_NAME] resource group: $RG ($LOCATION)"
  az group create --name "$RG" --location "$LOCATION" --output none
  echo "==> [$ENV_NAME] ACR: $ACR_NAME"
  make_params "false"
  az deployment group create \
    --resource-group "$RG" \
    --name "${PREFIX}-${ENV_NAME}-infra-${DEPLOY_APPEND}" \
    --template-file "$SCRIPT_DIR/main.bicep" \
    --parameters @"$params_file" \
    --output none
}

phase_images() {
  echo "==> [$ENV_NAME] building and pushing images to $ACR_SERVER"
  az acr login --name "$ACR_NAME" >/dev/null
  (
    cd "$REPO_ROOT/backend"
    docker build -t "${ACR_SERVER}/${BACKEND_IMAGE}:${IMAGE_TAG}" .
    docker push "${ACR_SERVER}/${BACKEND_IMAGE}:${IMAGE_TAG}"
  )
  (
    cd "$REPO_ROOT/frontend"
    build_args=()
    [[ -n "${VITE_API_BASE_URL:-}" ]] && build_args+=(--build-arg "VITE_API_BASE_URL=$VITE_API_BASE_URL")
    [[ -n "${VITE_ENTRA_CLIENT_ID:-}" ]] && build_args+=(--build-arg "VITE_ENTRA_CLIENT_ID=$VITE_ENTRA_CLIENT_ID")
    [[ -n "${VITE_ENTRA_TENANT_ID:-}" ]] && build_args+=(--build-arg "VITE_ENTRA_TENANT_ID=$VITE_ENTRA_TENANT_ID")
    docker build "${build_args[@]}" -t "${ACR_SERVER}/${FRONTEND_IMAGE}:${IMAGE_TAG}" .
    docker push "${ACR_SERVER}/${FRONTEND_IMAGE}:${IMAGE_TAG}"
  )
}

phase_apps() {
  echo "==> [$ENV_NAME] deploying container apps"
  make_params "true"
  az deployment group create \
    --resource-group "$RG" \
    --name "${PREFIX}-${ENV_NAME}-apps-${DEPLOY_APPEND}" \
    --template-file "$SCRIPT_DIR/main.bicep" \
    --parameters @"$params_file" \
    --output none

  web_url="$(az containerapp show -g "$RG" -n "${PREFIX}-${ENV_NAME}-web" \
    --query "properties.configuration.ingress.fqdn" -o tsv)"
  frontend_url="$(az containerapp show -g "$RG" -n "${PREFIX}-${ENV_NAME}-frontend" \
    --query "properties.configuration.ingress.fqdn" -o tsv)"
  echo
  echo "==> [$ENV_NAME] deployed"
  echo "    App (SPA):    https://${frontend_url}"
  echo "    API (health): https://${web_url}/health"
}

case "$STAGE" in
  all)
    phase_infra
    phase_images
    phase_apps
    ;;
  infra) phase_infra ;;
  images) phase_images ;;
  apps) phase_apps ;;
esac
