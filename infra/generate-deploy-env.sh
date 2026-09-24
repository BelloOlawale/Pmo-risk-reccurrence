#!/usr/bin/env bash
# =============================================================================
# PMO Risk Recurrence Predictor — Generate a deployment environment file
# =============================================================================
#
# Creates a dedicated, git-ignored deployment env file (default:
# infra/deploy.<env>.env) with values read from the LIVE Azure resources, so
# deployment never depends on the local developer backend/.env.
#
# Azure-derived (always fresh, never copied from another file):
#   RISKAPP_DATABASE_URL        built from the PostgreSQL Flexible Server
#   RISKAPP_BLOB_ACCOUNT_NAME   the storage account in the resource group
#   RISKAPP_BLOB_ACCOUNT_KEY    a fresh key read from that account
#   RISKAPP_BLOB_CONTAINER
#   RISKAPP_APP_BASE_URL        https://<frontend app fqdn>
#   RISKAPP_CORS_ORIGINS
#   RISKAPP_ENVIRONMENT / RISKAPP_APP_TIMEZONE
#
# Seeded (external services not managed in this resource group). Pass
# --seed-from <file> to copy them from an existing env file, or set them with
# --env KEY=VALUE. DATABASE_URL / BLOB_* are NEVER copied from the seed file.
#
# USAGE
#   bash infra/generate-deploy-env.sh dev
#   bash infra/generate-deploy-env.sh dev --seed-from backend/.env
#   bash infra/generate-deploy-env.sh dev --reset-postgres-password
#   bash infra/generate-deploy-env.sh dev --postgres-password 'S3cret...'
#   bash infra/generate-deploy-env.sh dev --key-vault riskapp-dev-kv
#
# OPTIONS
#   --resource-group <rg>          default: rg-<prefix>-<env>
#   --prefix <p>                   default: riskapp
#   --location <region>            default: eastus
#   --output <path>                default: infra/deploy.<env>.env
#   --postgres-server <name>       default: first PostgreSQL server in the RG
#   --postgres-user <name>         default: riskappadmin
#   --postgres-db <name>           default: riskapp
#   --postgres-password <pw>       use an existing password (no reset)
#   --reset-postgres-password      generate a new password and set it on the server
#   --storage-account <name>       default: first storage account in the RG
#   --blob-container <name>        default: risk-registers
#   --seed-from <file>             copy external-service keys from this file
#   --env KEY=VALUE                set/override any key (repeatable)
#   --key-vault <name>             also upload secrets to Key Vault (best effort)
#   --allow-azure-services         add the PostgreSQL "allow Azure services" firewall rule
#   --timezone <tz>                default: Africa/Lagos
#   -h | --help
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Keys copied from --seed-from. Azure-derived keys are deliberately excluded so
# a stale/localhost DATABASE_URL can never leak into a deployment.
SEED_KEYS=(
  RISKAPP_REDIS_URL
  RISKAPP_AZURE_OPENAI_ENDPOINT
  RISKAPP_AZURE_OPENAI_API_KEY
  RISKAPP_AZURE_OPENAI_EMBEDDING_DEPLOYMENT
  RISKAPP_AZURE_OPENAI_CHAT_DEPLOYMENT
  RISKAPP_AZURE_OPENAI_API_VERSION
  RISKAPP_ACS_ENDPOINT
  RISKAPP_ACS_ACCESS_KEY
  RISKAPP_ACS_SENDER_EMAIL
  RISKAPP_ENTRA_TENANT_ID
  RISKAPP_ENTRA_CLIENT_ID
  RISKAPP_ENTRA_CLIENT_SECRET
  RISKAPP_ENTRA_ROLE_GROUP_IDS
  VITE_ENTRA_CLIENT_ID
  VITE_ENTRA_TENANT_ID
  RISKAPP_TEST_LOGIN_ENABLED
  RISKAPP_TEST_LOGIN_CODE
  RISKAPP_TEST_LOGIN_SECRET
  RISKAPP_LOCAL_LOGIN_ENABLED
)

# ---- Output helpers ---------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}==>${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

usage() { sed -n '2,49p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

# ---- Parse ------------------------------------------------------------------
[[ $# -lt 1 ]] && usage 1
case "$1" in -h|--help) usage 0 ;; esac
ENV_NAME="$1"; shift

PREFIX="${APP_PREFIX:-riskapp}"
LOCATION="${AZURE_LOCATION:-eastus}"
RG_NAME=""
OUTPUT=""
POSTGRES_SERVER=""
POSTGRES_USER="riskappadmin"
POSTGRES_DB="riskapp"
POSTGRES_PASSWORD="${POSTGRES_ADMIN_PASSWORD:-}"
RESET_PG="false"
STORAGE_ACCOUNT=""
BLOB_CONTAINER="risk-registers"
SEED_FROM=""
KEY_VAULT=""
ALLOW_AZURE="false"
APP_TIMEZONE="${APP_TIMEZONE:-Africa/Lagos}"
declare -a CLI_OVERRIDES=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --resource-group)     RG_NAME="$2"; shift 2 ;;
        --prefix)             PREFIX="$2"; shift 2 ;;
        --location)           LOCATION="$2"; shift 2 ;;
        --output)             OUTPUT="$2"; shift 2 ;;
        --postgres-server)    POSTGRES_SERVER="$2"; shift 2 ;;
        --postgres-user)      POSTGRES_USER="$2"; shift 2 ;;
        --postgres-db)        POSTGRES_DB="$2"; shift 2 ;;
        --postgres-password)  POSTGRES_PASSWORD="$2"; shift 2 ;;
        --reset-postgres-password) RESET_PG="true"; shift ;;
        --storage-account)    STORAGE_ACCOUNT="$2"; shift 2 ;;
        --blob-container)     BLOB_CONTAINER="$2"; shift 2 ;;
        --seed-from)          SEED_FROM="$2"; shift 2 ;;
        --env)                CLI_OVERRIDES+=("$2"); shift 2 ;;
        --key-vault)          KEY_VAULT="$2"; shift 2 ;;
        --allow-azure-services) ALLOW_AZURE="true"; shift ;;
        --timezone)           APP_TIMEZONE="$2"; shift 2 ;;
        -h|--help)            usage 0 ;;
        *) error "Unknown option: $1 (see --help)" ;;
    esac
done

RG_NAME="${RG_NAME:-rg-${PREFIX}-${ENV_NAME}}"
OUTPUT="${OUTPUT:-$SCRIPT_DIR/deploy.${ENV_NAME}.env}"

# ---- Prerequisites ----------------------------------------------------------
info "Checking prerequisites..."
command -v az >/dev/null || error "Azure CLI (az) not found."
az account show >/dev/null 2>&1 || error "Not authenticated. Run 'az login'."

PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 \
       && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"; break
    fi
done
[[ -n "$PYTHON_BIN" ]] || error "Python 3 is required."
success "Authenticated as $(az account show --query user.name -o tsv)"

RG_EXISTS="true"
az group show -n "$RG_NAME" >/dev/null 2>&1 || RG_EXISTS="false"
[[ "$RG_EXISTS" == "true" ]] || error "Resource group '$RG_NAME' not found. Deploy infrastructure first."

# ---- Discover live resources ------------------------------------------------
info "Discovering resources in $RG_NAME..."

if [[ -z "$POSTGRES_SERVER" ]]; then
    POSTGRES_SERVER=$(az postgres flexible-server list -g "$RG_NAME" --query "[0].name" -o tsv 2>/dev/null || true)
fi
[[ -n "$POSTGRES_SERVER" ]] && success "PostgreSQL : $POSTGRES_SERVER" || warn "No PostgreSQL server found in $RG_NAME"

if [[ -z "$STORAGE_ACCOUNT" ]]; then
    STORAGE_ACCOUNT=$(az storage account list -g "$RG_NAME" --query "[0].name" -o tsv 2>/dev/null || true)
fi
[[ -n "$STORAGE_ACCOUNT" ]] && success "Storage    : $STORAGE_ACCOUNT" || warn "No storage account found in $RG_NAME"

FRONTEND_FQDN=$(az containerapp show -g "$RG_NAME" -n "${PREFIX}-${ENV_NAME}-frontend" \
    --query 'properties.configuration.ingress.fqdn' -o tsv 2>/dev/null || true)
[[ -n "$FRONTEND_FQDN" ]] && success "Frontend   : https://$FRONTEND_FQDN" || warn "Frontend app not found (URL will be blank)"

# ---- PostgreSQL password + connection string --------------------------------
gen_password() {
    "$PYTHON_BIN" - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits
while True:
    pw = ''.join(secrets.choice(alphabet) for _ in range(24))
    if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
        break
print(pw)
PY
}

DATABASE_URL=""
if [[ -n "$POSTGRES_SERVER" ]]; then
    if [[ "$RESET_PG" == "true" ]]; then
        info "Generating a new PostgreSQL admin password and applying it..."
        POSTGRES_PASSWORD="$(gen_password)"
        az postgres flexible-server update -g "$RG_NAME" -n "$POSTGRES_SERVER" \
            --admin-password "$POSTGRES_PASSWORD" --output none \
            || error "Failed to reset the PostgreSQL admin password."
        success "PostgreSQL admin password rotated"
    fi

    # Preserve continuity: if a previous run already wrote a DATABASE_URL, reuse
    # its password instead of losing it on a re-run.
    if [[ -z "$POSTGRES_PASSWORD" ]] && [[ "$RESET_PG" != "true" ]] && [[ -f "$OUTPUT" ]]; then
        existing_url=$(grep -E '^RISKAPP_DATABASE_URL=' "$OUTPUT" | head -1 | cut -d= -f2- || true)
        if [[ -n "$existing_url" ]]; then
            POSTGRES_PASSWORD=$(printf '%s' "$existing_url" | sed -E 's#^[a-z+]+://[^:]+:([^@]+)@.*#\1#')
            [[ "$POSTGRES_PASSWORD" == "$existing_url" ]] && POSTGRES_PASSWORD=""
            [[ -n "$POSTGRES_PASSWORD" ]] && success "Reusing the PostgreSQL password from $OUTPUT"
        fi
    fi

    if [[ -z "$POSTGRES_PASSWORD" ]] && [[ -n "$KEY_VAULT" ]]; then
        POSTGRES_PASSWORD=$(az keyvault secret show --vault-name "$KEY_VAULT" \
            --name postgresql-admin-password --query value -o tsv 2>/dev/null || true)
        [[ -n "$POSTGRES_PASSWORD" ]] && success "Read PostgreSQL password from Key Vault"
    fi

    if [[ -z "$POSTGRES_PASSWORD" ]]; then
        if [[ -t 0 ]]; then
            read -r -s -p "Enter existing PostgreSQL admin password (blank to leave TODO): " POSTGRES_PASSWORD; echo ""
        else
            warn "No PostgreSQL password supplied (use --postgres-password or --reset-postgres-password)"
        fi
    fi

    PG_FQDN=$(az postgres flexible-server show -g "$RG_NAME" -n "$POSTGRES_SERVER" \
        --query fullyQualifiedDomainName -o tsv 2>/dev/null || true)
    if [[ -n "$POSTGRES_PASSWORD" ]] && [[ -n "$PG_FQDN" ]]; then
        DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${PG_FQDN}:5432/${POSTGRES_DB}?sslmode=require"
        success "Built RISKAPP_DATABASE_URL for $PG_FQDN"
    fi

    if [[ "$ALLOW_AZURE" == "true" ]]; then
        info "Allowing Azure services through the PostgreSQL firewall..."
        az postgres flexible-server firewall-rule create -g "$RG_NAME" --server-name "$POSTGRES_SERVER" \
            --name allow-azure-services --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 \
            --output none >/dev/null 2>&1 && success "Firewall rule ensured" \
            || warn "Could not create the firewall rule"
    fi
fi

# ---- Blob storage -----------------------------------------------------------
BLOB_ACCOUNT_KEY=""
if [[ -n "$STORAGE_ACCOUNT" ]]; then
    BLOB_ACCOUNT_KEY=$(az storage account keys list -g "$RG_NAME" -n "$STORAGE_ACCOUNT" \
        --query "[0].value" -o tsv 2>/dev/null || true)
    [[ -n "$BLOB_ACCOUNT_KEY" ]] && success "Read blob account key" || warn "Could not read the storage account key"
fi

# ---- Seeded external values -------------------------------------------------
declare -A SEED=()
if [[ -n "$SEED_FROM" ]]; then
    [[ -f "$SEED_FROM" ]] || error "Seed file not found: $SEED_FROM"
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
        key="${line%%=*}"; val="${line#*=}"
        key="$(echo "$key" | tr -d '[:space:]')"
        val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
        SEED["$key"]="$val"
    done < "$SEED_FROM"
    info "Seeding external-service keys from $SEED_FROM"
fi

declare -A OVERRIDE=()
for pair in "${CLI_OVERRIDES[@]:-}"; do
    [[ -n "$pair" ]] && OVERRIDE["${pair%%=*}"]="${pair#*=}"
done

# Values already present in a previous output file are reused when not supplied
# again, so a plain re-run never drops a secret it cannot regenerate.
declare -A EXISTING=()
if [[ -f "$OUTPUT" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
        EXISTING["${line%%=*}"]="${line#*=}"
    done < "$OUTPUT"
fi

resolve_seed() {
    local name="$1"
    if [[ -n "${OVERRIDE[$name]:-}" ]]; then printf '%s' "${OVERRIDE[$name]}"; return; fi
    if [[ -n "${SEED[$name]:-}" ]]; then printf '%s' "${SEED[$name]}"; return; fi
    printf '%s' "${EXISTING[$name]:-}"
}

# ---- Write the file ---------------------------------------------------------
umask 077
: > "$OUTPUT"
{
    echo "# Generated by infra/generate-deploy-env.sh on $(date -Iseconds)"
    echo "# Environment: $ENV_NAME   Resource group: $RG_NAME"
    echo "# NOTE: git-ignored. Do not commit. Regenerate rather than edit by hand."
    echo ""
    echo "# ---- Azure-derived (regenerated from live resources) ----"
} >> "$OUTPUT"

emit()          { printf '%s=%s\n' "$1" "$2" >> "$OUTPUT"; }
emit_missing()  { printf '# %s=\n#   TODO: %s\n' "$1" "$2" >> "$OUTPUT"; }

[[ -n "$DATABASE_URL" ]] && emit RISKAPP_DATABASE_URL "$DATABASE_URL" \
    || emit_missing RISKAPP_DATABASE_URL "run with --reset-postgres-password or --postgres-password"
[[ -n "$STORAGE_ACCOUNT" ]] && emit RISKAPP_BLOB_ACCOUNT_NAME "$STORAGE_ACCOUNT" \
    || emit_missing RISKAPP_BLOB_ACCOUNT_NAME "no storage account found"
[[ -n "$BLOB_ACCOUNT_KEY" ]] && emit RISKAPP_BLOB_ACCOUNT_KEY "$BLOB_ACCOUNT_KEY" \
    || emit_missing RISKAPP_BLOB_ACCOUNT_KEY "storage key unavailable"
emit RISKAPP_BLOB_CONTAINER "$BLOB_CONTAINER"
emit RISKAPP_ENVIRONMENT "$ENV_NAME"
emit RISKAPP_APP_TIMEZONE "$APP_TIMEZONE"
[[ -n "$FRONTEND_FQDN" ]] && emit RISKAPP_APP_BASE_URL "https://$FRONTEND_FQDN"
[[ -n "$FRONTEND_FQDN" ]] && emit RISKAPP_CORS_ORIGINS "https://$FRONTEND_FQDN"

{
    echo ""
    echo "# ---- External services (seeded / overridden; not managed in this RG) ----"
} >> "$OUTPUT"

for name in "${SEED_KEYS[@]}"; do
    val="$(resolve_seed "$name")"
    if [[ -n "$val" ]]; then emit "$name" "$val"; else emit_missing "$name" "provide via --seed-from or --env $name=..."; fi
done

success "Wrote $OUTPUT"

# ---- Optional Key Vault upload ---------------------------------------------
if [[ -n "$KEY_VAULT" ]]; then
    info "Uploading secrets to Key Vault '$KEY_VAULT' (best effort)..."
    kv_set() {
        local secret_name; secret_name="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
        az keyvault secret set --vault-name "$KEY_VAULT" --name "$secret_name" --value "$2" --output none 2>/dev/null \
            && success "  $secret_name" || warn "  could not set $secret_name"
    }
    [[ -n "$DATABASE_URL" ]] && kv_set RISKAPP_DATABASE_URL "$DATABASE_URL"
    [[ -n "$BLOB_ACCOUNT_KEY" ]] && kv_set RISKAPP_BLOB_ACCOUNT_KEY "$BLOB_ACCOUNT_KEY"
    for name in "${SEED_KEYS[@]}"; do
        val="$(resolve_seed "$name")"
        [[ -n "$val" ]] && kv_set "$name" "$val"
    done
fi

# ---- Summary ----------------------------------------------------------------
set_keys=$(grep -c '^RISKAPP_' "$OUTPUT" || true)
todo_keys=$(grep -c '^# RISKAPP_' "$OUTPUT" || true)
cat <<EOF

$(echo -e "${GREEN}")==============================================================================
DEPLOYMENT ENV GENERATED
==============================================================================$(echo -e "${NC}")
File       : $OUTPUT
Populated  : ${set_keys} keys
TODO       : ${todo_keys} keys

Next:
  1. Fill or seed any TODO keys above.
  2. Deploy with this file:
     bash infra/deploy-service.sh $ENV_NAME --service web,worker,beat --env-file "$OUTPUT"
EOF
