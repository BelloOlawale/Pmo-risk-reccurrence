#!/usr/bin/env bash
# =============================================================================
# Measure the app -> PostgreSQL round-trip from inside the web container
# =============================================================================
#
# Use before and after the region move (infra/move-postgres-region.sh) to prove
# the latency win. A same-region database should show a few ms per query; the
# cross-region setup measured ~76 ms per query and ~580 ms per fresh connect.
#
# USAGE
#   bash infra/check-db-latency.sh                 # dev / riskapp-dev-web
#   bash infra/check-db-latency.sh prod --app web
#
# =============================================================================

set -euo pipefail

ENV_NAME="dev"
APP="web"
RG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        dev|prod|staging) ENV_NAME="$1"; shift ;;
        --app) APP="$2"; shift 2 ;;
        --resource-group) RG="$2"; shift 2 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done
[[ -z "$RG" ]] && RG="rg-riskapp-${ENV_NAME}"

APP_NAME="riskapp-${ENV_NAME}-${APP}"
command -v az >/dev/null || { echo "az CLI not found" >&2; exit 1; }

echo "Measuring DB round-trip from ${APP_NAME} (resource group ${RG})..."

# Runs inside the container, where RISKAPP_DATABASE_URL and psycopg are present.
PROBE="import time,os,psycopg;u=os.environ['RISKAPP_DATABASE_URL'].replace('+psycopg','');t=time.time();c=psycopg.connect(u);print('connect_ms',round((time.time()-t)*1000));cur=c.cursor();[ (lambda s:(cur.execute('select 1'),print('query_ms',round((time.time()-s)*1000))))(time.time()) for _ in range(5)]"

az containerapp exec -g "$RG" -n "$APP_NAME" --command "python -c \"${PROBE}\"" 2>&1 \
    | grep -E "connect_ms|query_ms" \
    | sed 's/^/  /'

echo
echo "Baseline (cross-region): connect_ms ~580, query_ms ~76"
echo "Target  (same region):   connect_ms  <20, query_ms  <5"
