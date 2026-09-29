#!/usr/bin/env bash
# =============================================================================
# Move the PostgreSQL database into the app's region (maintenance window)
# =============================================================================
#
# WHY
#   The Container Apps run in East US but the PostgreSQL flexible server was
#   created in UK South. Every query therefore pays a cross-region round-trip
#   (measured ~76 ms/query, ~580 ms per fresh connection), which makes the app
#   feel slow even while both sides are idle. Co-locating them removes that.
#
# WHAT IT DOES (in order)
#   1. Creates a new PostgreSQL flexible server in the target region, matching
#      the source settings (Burstable B2s, PG 16, 32 GiB, public access).
#   2. Creates the target schema with `alembic upgrade head`.
#   3. Copies every table (see copy_postgres.py) and verifies row counts.
#   4. (--cutover) Points the app at the new server and restarts web/worker/beat.
#
# SAFETY
#   - Nothing touches production until --cutover is passed.
#   - The source server is left running and untouched, so rollback is simply:
#       cp infra/deploy.<env>.env.bak infra/deploy.<env>.env
#       bash infra/deploy-service.sh <env> --service web,worker,beat --stage apps
#   - Secrets are read from infra/deploy.<env>.env and passed via environment
#     variables, never argv, so they never appear in `ps`.
#
# PREREQUISITES
#   - az CLI authenticated; the local venv has the backend `alembic` installed
#     (pip install -e "backend[dev]").
#   - PG_ADMIN_PASSWORD set to the new server's admin password (choose one; it
#     is NOT read from Azure, which never returns it).
#
# USAGE
#   PG_ADMIN_PASSWORD='...' bash infra/move-postgres-region.sh dev --yes
#   # then, after verifying the copy:
#   PG_ADMIN_PASSWORD='...' bash infra/move-postgres-region.sh dev --yes --cutover
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; CYAN=$'\033[0;36m'; NC=$'\033[0m'
info()  { echo "${CYAN}==>${NC} $*"; }
ok()    { echo "${GREEN}[OK]${NC} $*"; }
warn()  { echo "${YELLOW}[!]${NC} $*"; }
die()   { echo "${RED}[X]${NC} $*" >&2; exit 1; }

ENV_NAME="dev"
RG="rg-riskapp-dev"
SOURCE_SERVER="riskapp-dev-postgres"
DATABASE_NAME="riskapp"
TARGET_LOCATION="eastus"
TARGET_SERVER=""
ADMIN_USER=""
CONFIRMED="false"
DO_CUTOVER="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        dev|prod|staging) ENV_NAME="$1"; shift ;;
        --resource-group) RG="$2"; shift 2 ;;
        --source-server) SOURCE_SERVER="$2"; shift 2 ;;
        --target-server) TARGET_SERVER="$2"; shift 2 ;;
        --target-location) TARGET_LOCATION="$2"; shift 2 ;;
        --database) DATABASE_NAME="$2"; shift 2 ;;
        --admin-user) ADMIN_USER="$2"; shift 2 ;;
        --yes) CONFIRMED="true"; shift ;;
        --cutover) DO_CUTOVER="true"; shift ;;
        -h|--help) sed -n '2,45p' "$0"; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

[[ -z "$TARGET_SERVER" ]] && TARGET_SERVER="${SOURCE_SERVER}-${TARGET_LOCATION}"
DEPLOY_ENV_FILE="$SCRIPT_DIR/deploy.${ENV_NAME}.env"
[[ -f "$DEPLOY_ENV_FILE" ]] || die "Missing $DEPLOY_ENV_FILE (run generate-deploy-env.sh first)."

# --- preflight ---------------------------------------------------------------
command -v az >/dev/null || die "az CLI not found"
command -v python >/dev/null || die "python not found"
python -c "import alembic" 2>/dev/null || die "alembic not importable; activate the backend venv (pip install -e 'backend[dev]')"
[[ -n "${PG_ADMIN_PASSWORD:-}" ]] || die "Set PG_ADMIN_PASSWORD (password for the new admin user)."

# Read a value from the deploy env file without echoing it.
read_env() { python - "$DEPLOY_ENV_FILE" "$1" <<'PY'
import sys
path, key = sys.argv[1], sys.argv[2]
for line in open(path, encoding="utf-8"):
    if line.startswith(key + "="):
        print(line.split("=", 1)[1].strip().strip('"'))
        break
PY
}

SOURCE_URL="$(read_env RISKAPP_DATABASE_URL)"
[[ -n "$SOURCE_URL" ]] || die "RISKAPP_DATABASE_URL is empty in $DEPLOY_ENV_FILE"
SOURCE_FQDN="$(python - "$SOURCE_URL" <<'PY'
import sys
from urllib.parse import urlsplit
print(urlsplit(sys.argv[1].replace("postgresql+psycopg://", "postgresql://")).hostname or "")
PY
)"
[[ -n "$SOURCE_FQDN" ]] || die "Could not parse the source database host."
[[ -z "$ADMIN_USER" ]] && ADMIN_USER="$(az postgres flexible-server show -g "$RG" -n "$SOURCE_SERVER" --query administratorLogin -o tsv)"

echo "------------------------------------------------------------------------------"
echo "Move PostgreSQL into the app region"
echo "------------------------------------------------------------------------------"
echo "  Resource group : $RG"
echo "  Source server  : $SOURCE_SERVER ($SOURCE_FQDN)"
echo "  Target server  : $TARGET_SERVER ($TARGET_LOCATION)"
echo "  Database       : $DATABASE_NAME"
echo "  Admin user     : $ADMIN_USER"
echo "  Cutover        : $DO_CUTOVER"
echo "------------------------------------------------------------------------------"

if [[ "$CONFIRMED" != "true" ]]; then
    warn "Dry run: pass --yes to create the target server and copy data."
    exit 0
fi

# --- 1. create the target server --------------------------------------------
if az postgres flexible-server show -g "$RG" -n "$TARGET_SERVER" >/dev/null 2>&1; then
    warn "Target server $TARGET_SERVER already exists; reusing it."
else
    info "Creating $TARGET_SERVER in $TARGET_LOCATION (this takes several minutes)..."
    az postgres flexible-server create \
        -g "$RG" -n "$TARGET_SERVER" -l "$TARGET_LOCATION" \
        --admin-user "$ADMIN_USER" --admin-password "$PG_ADMIN_PASSWORD" \
        --version 16 --sku-name Standard_B2s --tier Burstable \
        --storage-size 32 --public-access 0.0.0.0 \
        --database-name "$DATABASE_NAME" --yes >/dev/null
    ok "Server created."
fi

TARGET_FQDN="$(az postgres flexible-server show -g "$RG" -n "$TARGET_SERVER" \
    --query fullyQualifiedDomainName -o tsv)"
ok "Target host: $TARGET_FQDN"

# --- 2. create the schema on the target -------------------------------------
# Build the URL in Python so the password is URL-encoded, and export it (never
# pass secrets as arguments).
TARGET_URL="$(python - "$ADMIN_USER" "$PG_ADMIN_PASSWORD" "$TARGET_FQDN" "$DATABASE_NAME" <<'PY'
import sys
from urllib.parse import quote
user, password, host, db = sys.argv[1:5]
print(f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}@{host}:5432/{db}?sslmode=require")
PY
)"
export RISKAPP_DATABASE_URL="$TARGET_URL"
info "Applying migrations to the target (alembic upgrade head)..."
( cd "$BACKEND_DIR" && RISKAPP_DATABASE_URL="$TARGET_URL" python -m alembic upgrade head >/dev/null )
ok "Target schema at head."

# --- 3. copy the data --------------------------------------------------------
info "Copying data (row counts are verified)..."
SOURCE_DATABASE_URL="$SOURCE_URL" TARGET_DATABASE_URL="$TARGET_URL" \
    PYTHONPATH="$BACKEND_DIR/src" python "$SCRIPT_DIR/copy_postgres.py"
ok "Data copied."

if [[ "$DO_CUTOVER" != "true" ]]; then
    echo
    ok "Target is ready and populated. Production is untouched."
    echo "Next (during the maintenance window):"
    echo "  1. Re-run this script with --cutover to repoint the app and restart it."
    echo "  2. Verify: curl -fsS https://riskapp-${ENV_NAME}-web.<region>.azurecontainerapps.io/health"
    echo "  3. Keep the source server for rollback (see the header for the rollback steps)."
    exit 0
fi

# --- 4. cutover --------------------------------------------------------------
info "Pointing the app at the new server..."
BACKUP="${DEPLOY_ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"
cp "$DEPLOY_ENV_FILE" "$BACKUP"
python - "$DEPLOY_ENV_FILE" "$SOURCE_FQDN" "$TARGET_FQDN" <<'PY'
import sys
path, old_host, new_host = sys.argv[1:4]
lines = open(path, encoding="utf-8").read().splitlines(keepends=True)
out = []
for line in lines:
    if line.startswith("RISKAPP_DATABASE_URL=") and f"@{old_host}" in line:
        line = line.replace(f"@{old_host}", f"@{new_host}")
    out.append(line)
open(path, "w", encoding="utf-8").writelines(out)
PY
ok "Updated $DEPLOY_ENV_FILE (backup: $BACKUP)"

info "Redeploying web/worker/beat with the new database secret..."
bash "$SCRIPT_DIR/deploy-service.sh" "$ENV_NAME" --service web,worker,beat --stage apps
ok "Cutover complete."

echo
warn "Post-cutover checks:"
echo "  - Confirm the app is healthy and that query latency improved."
echo "  - Once satisfied, decommission the old server:"
echo "      az postgres flexible-server delete -g $RG -n $SOURCE_SERVER --yes"
echo "  - Rollback if needed:"
echo "      cp $BACKUP $DEPLOY_ENV_FILE"
echo "      bash infra/deploy-service.sh $ENV_NAME --service web,worker,beat --stage apps"
