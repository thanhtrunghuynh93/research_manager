# Builds the SPA and serves it with Caddy. Build context is the repository root.
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM caddy:2.8-alpine
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=web /web/dist /srv
