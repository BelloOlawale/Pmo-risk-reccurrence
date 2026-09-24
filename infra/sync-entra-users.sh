#!/usr/bin/env bash
# =============================================================================
# Sync the Entra ID directory into the app's users table
# =============================================================================
#
# The owner picker lists rows from the local `users` table (risk ownership is a
# foreign key). This script imports every user in the Entra ID tenant so the
# dropdown is populated without anyone having to sign in first.
#
# Two sources:
#   az-token (default) obtains a Microsoft Graph token from the signed-in Azure
#            CLI session and reads the directory with it — no extra permissions
#            to grant, and UTF-8 clean.
#   graph    calls Microsoft Graph with the app's client credentials — requires
#            the Microsoft Graph application permission User.Read.All + admin consent
#            and RISKAPP_ENTRA_* in the env file.
#
# Existing rows are matched case-insensitively by UPN and never deleted, so this
# is safe to re-run (e.g. from a scheduled job / CI) at any time.
#
# USAGE
#   bash infra/sync-entra-users.sh                 # dev, source=az-token
#   bash infra/sync-entra-users.sh prod            # prod, source=az-token
#   bash infra/sync-entra-users.sh dev --source graph
#   bash infra/sync-entra-users.sh dev --env-file infra/deploy.dev.env
#   bash infra/sync-entra-users.sh dev --include-guests
#
# B2B guest accounts (#EXT# UPNs) are excluded and any already in the table are
# pruned, unless --include-guests is passed.
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}==>${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
usage()   { sed -n '2,31p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

[[ $# -lt 1 ]] && usage 1
case "$1" in -h|--help) usage 0 ;; esac
ENV_NAME="$1"; shift

SOURCE="az-token"
ENV_FILE="$SCRIPT_DIR/deploy.${ENV_NAME}.env"
INCLUDE_GUESTS="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)         SOURCE="$2"; shift 2 ;;
        --env-file)       ENV_FILE="$2"; shift 2 ;;
        --include-guests) INCLUDE_GUESTS="true"; shift ;;
        -h|--help)        usage 0 ;;
        *) error "Unknown option: $1" ;;
    esac
done

case "$SOURCE" in az-token|graph) ;; *) error "Invalid --source: $SOURCE (az-token|graph)" ;; esac

command -v az >/dev/null || error "Azure CLI (az) not found."
az account show >/dev/null 2>&1 || error "Not authenticated. Run 'az login'."
[[ -f "$ENV_FILE" ]] || error "Env file not found: $ENV_FILE (generate it with generate-deploy-env.sh)"

# Pick the backend interpreter (venv preferred, then python on PATH).
PYTHON_BIN=""
for candidate in "$BACKEND_DIR/.venv/Scripts/python.exe" "$BACKEND_DIR/.venv/bin/python"; do
    [[ -x "$candidate" ]] && PYTHON_BIN="$candidate" && break
done
if [[ -z "$PYTHON_BIN" ]]; then
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 \
           && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[0]==3 else 1)' >/dev/null 2>&1; then
            PYTHON_BIN="$candidate"; break
        fi
    done
fi
[[ -n "$PYTHON_BIN" ]] || error "Python 3 not found."
[[ -n "${PYTHON_BIN}" ]] || error "no python"

# Load RISKAPP_* (DB URL, and Entra creds for the graph source) into the env.
set -a
while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    export "$line"
done < "$ENV_FILE"
set +a

# The CLI runs from the backend package root. Use a *relative* temp path so
# both the shell and the (native) Python interpreter resolve it identically on
# Windows/Git Bash as well as Linux.
cd "$BACKEND_DIR"

# Force UTF-8 so display names with accents are not mangled by the console codec.
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

CLI_ARGS=()
if [[ "$INCLUDE_GUESTS" == "true" ]]; then
    CLI_ARGS+=(--include-guests)
else
    CLI_ARGS+=(--prune-guests)
fi

if [[ "$SOURCE" == "graph" ]]; then
    info "Reading the directory from Microsoft Graph (app-only credentials)..."
    "$PYTHON_BIN" -m riskapp.sync_users --source graph "${CLI_ARGS[@]}"
else
    info "Requesting a Microsoft Graph token from the Azure CLI session..."
    GRAPH_ACCESS_TOKEN=$(az account get-access-token --resource https://graph.microsoft.com \
        --query accessToken -o tsv 2>/dev/null) \
        || error "Could not get a Graph token (run 'az login')."
    export GRAPH_ACCESS_TOKEN
    info "Reading the directory from Microsoft Graph..."
    "$PYTHON_BIN" -m riskapp.sync_users --source graph "${CLI_ARGS[@]}"
fi

success "Users table synced from Entra ID"
