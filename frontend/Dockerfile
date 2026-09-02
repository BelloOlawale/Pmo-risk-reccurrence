# Frontend image: build the React/Vite app, then serve the static bundle via
# nginx with SPA fallback (so client-side routes work on refresh/deep links).
#
# In production set VITE_API_BASE_URL at build time, or point nginx at the API
# by enabling the /api/ proxy block in nginx.conf.

FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
