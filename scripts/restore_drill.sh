#!/usr/bin/env bash
# Restore drill: bring up a scratch stack on a separate Compose project, restore the latest backup,
# and run smoke checks. Proves RTO/RPO before launch and quarterly afterwards (AC-16).
# Usage: scripts/restore_drill.sh <path-to-backups-dir> <age-identity-file>
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUPS=${1:?backups dir required}
AGE_IDENTITY=${2:?age identity file required}
PROJECT=rm-restore-drill
COMPOSE=(docker compose -p "$PROJECT" -f infra/docker-compose.yml --env-file infra/.env)

LATEST=$(ls -1t "$BACKUPS"/db/rm-*.dump.age | head -1)
echo "[drill] latest dump: $LATEST"
START=$(date +%s)

"${COMPOSE[@]}" build backup
"${COMPOSE[@]}" up -d postgres minio
sleep 5
"${COMPOSE[@]}" run --rm --no-deps \
  -v "$BACKUPS":/backups:ro -v "$AGE_IDENTITY":/run/age.key:ro \
  -e AGE_IDENTITY=/run/age.key \
  backup restore.sh "/backups/db/$(basename "$LATEST")" "/backups/objects/${RM_S3_BUCKET:-rm-dev}"

"${COMPOSE[@]}" up -d api
echo "[drill] waiting for api ..."
for _ in $(seq 1 60); do
  "${COMPOSE[@]}" exec -T api curl -fsS http://localhost:8000/api/healthz >/dev/null 2>&1 && break
  sleep 2
done
"${COMPOSE[@]}" exec -T api curl -fsS http://localhost:8000/api/healthz >/dev/null \
  || { echo "[drill] api did not become healthy"; "${COMPOSE[@]}" logs api | tail -50; exit 1; }
"${COMPOSE[@]}" exec -T api alembic current

END=$(date +%s)
echo "[drill] restore completed in $((END-START)) s (target RTO 4 h)"
echo "[drill] tear down with: docker compose -p $PROJECT down -v"
