#!/usr/bin/env bash
# Restore drill: bring up a scratch stack on a separate Compose project, restore the latest backup,
# and run smoke checks. Proves RTO/RPO before launch and quarterly afterwards (AC-16).
# Usage: scripts/restore_drill.sh <path-to-backups-dir> <age-identity-file>
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUPS=${1:?backups dir required}
AGE_IDENTITY=${2:?age identity file required}
PROJECT=rm-restore-drill
COMPOSE=(docker compose -p "$PROJECT" -f infra/docker-compose.yml -f infra/docker-compose.dev.yml --env-file infra/.env)

LATEST=$(ls -1t "$BACKUPS"/db/rm-*.dump.age | head -1)
echo "[drill] latest dump: $LATEST"
START=$(date +%s)

"${COMPOSE[@]}" up -d postgres minio
sleep 5
docker run --rm --network "${PROJECT}_default" \
  -v "$BACKUPS":/backups:ro -v "$AGE_IDENTITY":/run/age.key:ro \
  --env-file infra/.env -e AGE_IDENTITY=/run/age.key \
  "$(docker compose -p "$PROJECT" -f infra/docker-compose.yml images -q backup 2>/dev/null || echo rm-backup:local)" \
  restore.sh "/backups/db/$(basename "$LATEST")" "/backups/objects/${RM_S3_BUCKET:-rm-dev}"

"${COMPOSE[@]}" up -d api
bash scripts/dev-up.sh --wait-only
"${COMPOSE[@]}" exec -T api uv run alembic current

END=$(date +%s)
echo "[drill] restore completed in $((END-START)) s (target RTO 4 h)"
echo "[drill] tear down with: docker compose -p $PROJECT down -v"
