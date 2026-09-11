# Runbook — Backup and restore

Targets: RPO 24 h, RTO 4 h (requirements section 11; AC-16). Backups run nightly from the
`backup` container: encrypted `pg_dump` plus a MinIO bucket mirror, synced offsite with rclone.

## Verify backups are running

- `docker compose ... logs --since 48h backup | grep '\[backup\] done'` shows a run in the last 24 h.
- `rclone ls <offsite-remote>:research-management/db | tail -3` lists a dump from today.

## Restore drill (quarterly, and before launch)

`scripts/restore_drill.sh <backups-dir> <age-identity>` brings up a scratch stack, restores the
latest dump and object mirror, waits for readiness, and prints the elapsed time. Then check:

1. Log in as the professor; open the latest reporting period; counts match the operations log.
2. Open one submitted report and its attachments; the attachment downloads.
3. Open one approved assessment; citations resolve.
4. `alembic current` equals the deployed revision.

Tear down with `docker compose -p rm-restore-drill down -v`.

## Real restore

1. Stop api and worker: `docker compose ... stop api worker`.
2. Run `restore.sh <dump> <objects-dir>` inside the backup container with `AGE_IDENTITY` set.
3. `alembic upgrade head` if the dump predates the deployed code.
4. Start api and worker; run the four checks above; announce the recovered as-of time to users
   (any report submitted after that time must be resubmitted).
