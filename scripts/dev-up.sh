#!/usr/bin/env bash
# Start the development stack and wait until the API is ready.
# Usage: scripts/dev-up.sh            start, wait, migrate
#        scripts/dev-up.sh --wait-only   only wait for readiness (CI uses this after compose up)
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml --env-file infra/.env)

if [[ "${1:-}" != "--wait-only" ]]; then
  [[ -f infra/.env ]] || cp .env.example infra/.env
  "${COMPOSE[@]}" up -d --build
fi

echo "waiting for api ..."
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8021/api/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS http://localhost:8021/api/healthz >/dev/null || { echo "api did not become healthy"; "${COMPOSE[@]}" logs api | tail -50; exit 1; }

if [[ "${1:-}" != "--wait-only" ]]; then
  "${COMPOSE[@]}" exec -T api uv run alembic upgrade head
fi

echo "ready: app http://localhost:8020  api http://localhost:8021/api/docs  mailpit http://localhost:8025  minio http://localhost:8026"
