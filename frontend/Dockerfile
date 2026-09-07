# Frontend image: build the React/Vite app, then serve the static bundle via
# nginx with SPA fallback (so client-side routes work on refresh/deep links).
#
# Production (Azure Container Apps):
#   * VITE_* build args are baked into the bundle at build time.
#   * API_UPSTREAM is injected as a container env var at deploy time; the
#     start script renders nginx.prod.conf.template with it, proxying /api to
#     the web container app (same-origin for the browser).
# Docker Compose keeps its own mounted nginx config, so local behaviour is
# unchanged.

FROM node:20-alpine AS build

ARG VITE_API_BASE_URL=''
ARG VITE_ENTRA_CLIENT_ID=''
ARG VITE_ENTRA_TENANT_ID=''

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Bake the runtime configuration into the bundle.
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_ENTRA_CLIENT_ID=$VITE_ENTRA_CLIENT_ID \
    VITE_ENTRA_TENANT_ID=$VITE_ENTRA_TENANT_ID
RUN npm run build

FROM nginx:1.27-alpine

# Static SPA fallback (no /api proxy) used for standalone runs / Compose.
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Prod template rendered only when API_UPSTREAM is set (see start-nginx.sh).
COPY nginx.prod.conf.template /etc/nginx/prod/default.conf.template
COPY start-nginx.sh /start-nginx.sh
RUN chmod +x /start-nginx.sh

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["/start-nginx.sh"]
