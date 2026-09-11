#!/usr/bin/env bash
# Nightly backup: encrypted pg_dump + MinIO bucket mirror, synced offsite with rclone.
# RPO 24 h. Retention: 30 daily, 12 monthly (architecture §3, requirements section 11).
set -euo pipefail

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DAY=$(date -u +%d)
DEST=/backups
RECIPIENTS=/run/age-recipients.txt
OFFSITE_REMOTE=${RM_OFFSITE_REMOTE:-offsite:research-management}

mkdir -p "$DEST/db" "$DEST/objects"

echo "[backup] $STAMP dumping database"
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  | age -R "$RECIPIENTS" -o "$DEST/db/rm-$STAMP.dump.age"

echo "[backup] mirroring object storage"
mc alias set local "$RM_S3_ENDPOINT" "$RM_S3_ACCESS_KEY" "$RM_S3_SECRET_KEY" >/dev/null
mc mirror --overwrite --remove "local/$RM_S3_BUCKET" "$DEST/objects/$RM_S3_BUCKET"

echo "[backup] pruning local dumps"
find "$DEST/db" -name 'rm-*.dump.age' -mtime +30 ! -name "rm-*01T*" -delete   # keep the 1st-of-month dumps
find "$DEST/db" -name 'rm-*01T*.dump.age' -mtime +366 -delete

if rclone listremotes | grep -q "^${OFFSITE_REMOTE%%:*}:"; then
  echo "[backup] syncing offsite to $OFFSITE_REMOTE"
  rclone sync "$DEST" "$OFFSITE_REMOTE" --fast-list --transfers 8
else
  echo "[backup] WARNING: offsite remote not configured; backups are local only"
fi

echo "[backup] done $(date -u +%Y%m%dT%H%M%SZ)"
