#!/bin/sh
# Frontend container entrypoint (run after the base nginx docker-entrypoint.d
# scripts).
#
# In Azure Container Apps the deployment injects API_UPSTREAM (the web
# container-app FQDN); when set we render the prod nginx template with it so
# /api requests are proxied to the backend. Docker Compose and bare `docker
# run` leave API_UPSTREAM unset, so the baked/mounted config is used unchanged.
set -e

if [ -n "${API_UPSTREAM:-}" ]; then
    defined_envs=$(printf '${%s} ' $(awk 'END { for (name in ENVIRON) print name }' < /dev/null))
    envsubst "$defined_envs" \
        < /etc/nginx/prod/default.conf.template \
        > /etc/nginx/conf.d/default.conf
fi

exec nginx -g 'daemon off;'
