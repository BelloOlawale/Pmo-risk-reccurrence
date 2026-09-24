#!/usr/bin/env bash
# =============================================================================
# Register / configure the PMO Risk Recurrence Predictor app in Entra ID
# =============================================================================
#
# Provisions everything the backend + SPA need for Entra SSO and RBAC:
#   * an app registration with an SPA redirect URI (MSAL) and a web redirect
#   * an exposed API scope (`access_as_user`) and v2 access tokens
#     (required: the backend validates the v2 issuer and audience = client id)
#   * a `groups` claim (groupMembershipClaims=SecurityGroup) for role mapping
#   * a service principal
#   * a client secret
#   * the three RBAC security groups, resolved (or created with --create-groups)
#
# Outputs / writes the four keys the backend needs:
#   RISKAPP_ENTRA_TENANT_ID, RISKAPP_ENTRA_CLIENT_ID,
#   RISKAPP_ENTRA_CLIENT_SECRET, RISKAPP_ENTRA_ROLE_GROUP_IDS
# plus the two SPA build args: VITE_ENTRA_CLIENT_ID, VITE_ENTRA_TENANT_ID
#
# USAGE
#   bash infra/register-entra-app.sh <dev|prod> <frontend-url>
#   bash infra/register-entra-app.sh dev https://app.example.com --output-env infra/deploy.dev.env
#   bash infra/register-entra-app.sh dev https://app.example.com --create-groups
#
# OPTIONS
#   --output-env <file>    append/replace the six keys in this env file
#   --create-groups        create the security groups if they don't exist
#                          (needs Groups Administrator; otherwise they are
#                           resolved from existing groups)
#   --display-name <name>  override the app display name
#   -h | --help
#
# REQUIRED PERMISSIONS
#   Application Administrator (create app + secret). Group creation needs
#   Groups Administrator; without it, existing groups are resolved by name.
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}==>${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
usage()   { sed -n '2,44p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

[[ $# -lt 2 ]] && usage 1
case "$1" in -h|--help) usage 0 ;; esac

ENV_NAME="$1"; FRONTEND_URL="$2"; shift 2
FRONTEND_URL="${FRONTEND_URL%/}"
OUTPUT_ENV=""
CREATE_GROUPS="false"
DISPLAY_NAME="PMO Risk Recurrence Predictor (${ENV_NAME})"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-env)    OUTPUT_ENV="$2"; shift 2 ;;
        --create-groups) CREATE_GROUPS="true"; shift ;;
        --display-name)  DISPLAY_NAME="$2"; shift 2 ;;
        -h|--help)       usage 0 ;;
        *) error "Unknown option: $1" ;;
    esac
done

# RBAC group display names (override with env vars if yours differ).
SYSTEM_ADMIN_GROUP="${SYSTEM_ADMIN_GROUP:-RiskApp - System Admin}"
PMO_LEAD_GROUP="${PMO_LEAD_GROUP:-RiskApp -PMO Lead}"
PROJECT_MANAGER_GROUP="${PROJECT_MANAGER_GROUP:-RiskApp - Project Manager}"

command -v az >/dev/null || error "Azure CLI (az) not found."
az account show >/dev/null 2>&1 || error "Not authenticated. Run 'az login'."

TENANT_ID=$(az account show --query tenantId -o tsv)
success "Tenant: $TENANT_ID"

# -----------------------------------------------------------------------------
# 1. App registration
# -----------------------------------------------------------------------------
info "Ensuring app registration: $DISPLAY_NAME"
APP_ID=$(az ad app list --display-name "$DISPLAY_NAME" --query "[0].appId" -o tsv 2>/dev/null || true)
if [[ -n "$APP_ID" ]]; then
    success "App exists: $APP_ID"
else
    APP_ID=$(az ad app create \
        --display-name "$DISPLAY_NAME" \
        --sign-in-audience AzureADMyOrg \
        --enable-access-token-issuance true \
        --enable-id-token-issuance true \
        --query appId -o tsv)
    success "App created: $APP_ID"
fi
OBJECT_ID=$(az ad app show --id "$APP_ID" --query id -o tsv)

SCOPE_ID=$(az rest --method GET --url "https://graph.microsoft.com/v1.0/applications/$OBJECT_ID" \
    --query "api.oauth2PermissionScopes[?value=='access_as_user'].id | [0]" -o tsv 2>/dev/null || true)
[[ -n "$SCOPE_ID" && "$SCOPE_ID" != "None" ]] || SCOPE_ID=$(python -c "import uuid;print(uuid.uuid4())" 2>/dev/null || echo "$(date +%s)-0000-0000-0000-000000000000")

# -----------------------------------------------------------------------------
# 2. App configuration: redirect URIs, API scope, v2 tokens, group claims
# -----------------------------------------------------------------------------
info "Configuring redirect URIs, exposed scope, v2 tokens and group claims..."
az ad app update --id "$APP_ID" \
    --identifier-uris "api://$APP_ID" \
    --set groupMembershipClaims=SecurityGroup \
    --output none

az rest --method PATCH \
    --url "https://graph.microsoft.com/v1.0/applications/$OBJECT_ID" \
    --headers "Content-Type=application/json" \
    --body "{
      \"spa\": {\"redirectUris\": [\"$FRONTEND_URL\", \"$FRONTEND_URL/auth/callback\"]},
      \"api\": {
        \"requestedAccessTokenVersion\": 2,
        \"oauth2PermissionScopes\": [{
          \"id\": \"$SCOPE_ID\",
          \"value\": \"access_as_user\",
          \"type\": \"User\",
          \"isEnabled\": true,
          \"adminConsentDisplayName\": \"Access PMO Risk as the signed-in user\",
          \"adminConsentDescription\": \"Allow the SPA to call the PMO Risk API on behalf of the signed-in user.\",
          \"userConsentDisplayName\": \"Access PMO Risk on your behalf\",
          \"userConsentDescription\": \"Allow this app to access the PMO Risk API as you.\"
        }],
        \"preAuthorizedApplications\": [
          { \"appId\": \"$APP_ID\", \"delegatedPermissionIds\": [\"$SCOPE_ID\"] }
        ]
      },
      \"requiredResourceAccess\": [
        { \"resourceAppId\": \"$APP_ID\", \"resourceAccess\": [ { \"id\": \"$SCOPE_ID\", \"type\": \"Scope\" } ] }
      ]
    }" \
    --output none
success "Configured (spa=$FRONTEND_URL, scope=access_as_user, tokens=v2, claims=SecurityGroup, self pre-authorized)"

# NOTE: without requiredResourceAccess + preAuthorizedApplications the SPA gets
# AADSTS650057 ("Invalid resource") on the token request, because the client has
# not declared the API it is calling.

# -----------------------------------------------------------------------------
# 3. Service principal
# -----------------------------------------------------------------------------
az ad sp create --id "$APP_ID" --query id -o tsv >/dev/null 2>&1 \
    && success "Service principal created" \
    || success "Service principal already exists"

# Grant tenant-wide delegated consent for the scope (also covered by
# preAuthorizedApplications, but explicit consent avoids per-user prompts).
az ad app permission grant --id "$APP_ID" --api "$APP_ID" --scope "access_as_user" --output none >/dev/null 2>&1 \
    && success "Delegated consent granted (access_as_user)" \
    || warn "Could not pre-grant consent (pre-authorization still applies)"

# -----------------------------------------------------------------------------
# 4. Client secret
# -----------------------------------------------------------------------------
info "Creating client secret..."
CLIENT_SECRET=$(az ad app credential reset --id "$APP_ID" --append \
    --display-name "deploy-$(date +%Y%m%d%H%M)" --query password -o tsv 2>/dev/null) \
    || error "Could not create a client secret."
[[ -n "$CLIENT_SECRET" ]] || error "Empty client secret returned."
success "Client secret created"

# -----------------------------------------------------------------------------
# 5. RBAC security groups
# -----------------------------------------------------------------------------
resolve_group() {  # display-name -> object id
    local name="$1" id
    id=$(az ad group show --group "$name" --query id -o tsv 2>/dev/null || true)
    if [[ -n "$id" ]]; then printf '%s' "$id"; return; fi
    if [[ "$CREATE_GROUPS" == "true" ]]; then
        local nick; nick=$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')
        id=$(az ad group create --display-name "$name" --mail-nickname "$nick" --query id -o tsv 2>/dev/null || true)
        [[ -n "$id" ]] && printf '%s' "$id" && return
    fi
    printf ''
}

info "Resolving RBAC security groups..."
G_SYSADMIN=$(resolve_group "$SYSTEM_ADMIN_GROUP")
G_PMO=$(resolve_group "$PMO_LEAD_GROUP")
G_PM=$(resolve_group "$PROJECT_MANAGER_GROUP")

[[ -n "$G_SYSADMIN" ]] && success "System Admin    : $G_SYSADMIN" || warn "System Admin group '$SYSTEM_ADMIN_GROUP' not found"
[[ -n "$G_PMO" ]]      && success "PMO Lead        : $G_PMO"      || warn "PMO Lead group '$PMO_LEAD_GROUP' not found"
[[ -n "$G_PM" ]]       && success "Project Manager : $G_PM"       || warn "Project Manager group '$PROJECT_MANAGER_GROUP' not found"

ROLE_IDS="{"
SEP=""
[[ -n "$G_SYSADMIN" ]] && ROLE_IDS+="\"System Admin\":\"$G_SYSADMIN\"" && SEP=","
[[ -n "$G_PMO" ]]      && ROLE_IDS+="$SEP\"PMO Lead\":\"$G_PMO\"" && SEP=","
[[ -n "$G_PM" ]]       && ROLE_IDS+="$SEP\"Project Manager\":\"$G_PM\""
ROLE_IDS+="}"

# -----------------------------------------------------------------------------
# 6. Write / print the values
# -----------------------------------------------------------------------------
if [[ -n "$OUTPUT_ENV" ]]; then
    [[ -f "$OUTPUT_ENV" ]] || error "Output env file not found: $OUTPUT_ENV"
    info "Writing Entra keys to $OUTPUT_ENV"
    tmp=$(mktemp)
    grep -vE '^(RISKAPP_ENTRA_|VITE_ENTRA_)' "$OUTPUT_ENV" > "$tmp"
    {
        echo "RISKAPP_ENTRA_TENANT_ID=$TENANT_ID"
        echo "RISKAPP_ENTRA_CLIENT_ID=$APP_ID"
        echo "RISKAPP_ENTRA_CLIENT_SECRET=$CLIENT_SECRET"
        echo "RISKAPP_ENTRA_ROLE_GROUP_IDS=$ROLE_IDS"
        echo "VITE_ENTRA_CLIENT_ID=$APP_ID"
        echo "VITE_ENTRA_TENANT_ID=$TENANT_ID"
    } >> "$tmp"
    mv "$tmp" "$OUTPUT_ENV"
    success "Updated $OUTPUT_ENV"
fi

cat <<EOF

$(echo -e "${GREEN}")==============================================================================
ENTRA PROVISIONED
==============================================================================$(echo -e "${NC}")
App registration : $DISPLAY_NAME
Client ID        : $APP_ID
Tenant ID        : $TENANT_ID
Redirect URI     : $FRONTEND_URL
Scope            : api://$APP_ID/access_as_user

RISKAPP_ENTRA_TENANT_ID=$TENANT_ID
RISKAPP_ENTRA_CLIENT_ID=$APP_ID
RISKAPP_ENTRA_CLIENT_SECRET=<the secret just created>
RISKAPP_ENTRA_ROLE_GROUP_IDS=$ROLE_IDS

VITE_ENTRA_CLIENT_ID=$APP_ID
VITE_ENTRA_TENANT_ID=$TENANT_ID

Next: redeploy the backend (web/worker/beat) so it picks up the RISKAPP_ENTRA_*
values, and rebuild the frontend so VITE_ENTRA_* are baked into the SPA bundle.
EOF
