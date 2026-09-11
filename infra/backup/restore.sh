#!/usr/bin/env bash
# Restore a database dump and object mirror into the current stack.
# Usage: restore.sh <dump-file.age> [objects-dir]      (see docs/runbooks/backup-restore.md)
# Requires AGE_IDENTITY (path to the age private key) in the environment.
set -euo pipefail

DUMP=${1:?dump file required}
OBJECTS=${2:-}
: "${AGE_IDENTITY:?AGE_IDENTITY (age private key path) required}"

echo "[restore] decrypting and restoring $DUMP into $POSTGRES_DB"
age -d -i "$AGE_IDENTITY" "$DUMP" \
  | PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      --clean --if-exists --no-owner --no-privileges

if [[ -n "$OBJECTS" ]]; then
  echo "[restore] restoring objects from $OBJECTS"
  mc alias set local "$RM_S3_ENDPOINT" "$RM_S3_ACCESS_KEY" "$RM_S3_SECRET_KEY" >/dev/null
  mc mb --ignore-existing "local/$RM_S3_BUCKET"
  mc mirror --overwrite "$OBJECTS" "local/$RM_S3_BUCKET"
fi

echo "[restore] done; run the smoke checks in the runbook"
