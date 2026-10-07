# Runbook — Production readiness

Trigger: before a first production deploy, and again before any deploy that changes
authentication, mail, or object storage. Work through it alongside [deploy.md](deploy.md), which is
the procedure; this is what must already be true for that procedure to produce a working system.

An item is closed when it is either fixed or written down as an accepted risk with a name against
it. "We know about it" is not closed. Record the date and operator when this list changes.

The audit of 14–15 September 2026 covered enrolment and weekly submission. Its findings and how
each was closed are in git history (`git log -- docs/runbooks/production-readiness.md`).

## 1 In place

| Item | Where |
| --- | --- |
| A failed invitation, reset or notification email is visible | `notifications.service.mail_health`; the mail warning on the professor overview counts failed `email_deliveries` rows and failed `notifications.send_token_email` jobs separately |
| Readiness covers the worker and SMTP | `/api/readyz`: `database`, `object_storage`, `worker` (`skipped` on an empty queue, `fail` when jobs wait unconsumed), `smtp` (connect and log in, cached 60 s) |
| Mass session revocation | `app.cli identity revoke-all-sessions` ([rotate-secrets.md](rotate-secrets.md)); sessions are opaque tokens stored as digests, with no signing key to rotate |
| Rate limits on sign-in, reset requests and invitation acceptance | `AuthRateLimitMiddleware`, per client address, per api container — the same thing on one host |
| Refusal to start on development defaults | `Settings` with `RM_ENV=prod` names every surviving default at once (`app/core/config.py`) |
| `RM_ACME_EMAIL` reaches Caddy | In `.env.example` and passed to the caddy service; `scripts/preflight.sh` fails on an empty value |
| Bind-mounted files exist | `scripts/preflight.sh` checks `infra/backup/age-recipients.txt` and `infra/backup/rclone.conf` |
| Images are built on the host | `RM_BACKEND_IMAGE`/`RM_CADDY_IMAGE` are `rm-backend:local`/`rm-caddy:local`; deploy.md step 3 builds |
| Postgres sized for a 4 GB host | `shared_buffers = 512MB`, `effective_cache_size = 2GB`, `work_mem = 8MB`; 2 GB swap |
| Object store published on its own subdomain | `objects.<domain>`, its certificate, `RM_S3_PUBLIC_ENDPOINT` and the CSP `connect-src` entry (deploy.md steps 0 and 8) |
| Backups cover the database and the bucket | [infra/backup/backup.sh](../../infra/backup/backup.sh); restore drill in [backup-restore.md](backup-restore.md) |

## 2 Open

| Item | What it needs |
| --- | --- |
| Mail deliverability | SPF and DKIM published for the sending domain, and one invitation sent to an external mailbox as part of the first deploy. Enrolment is invitation-only, so a message in a spam folder is no way in |
| Upload scanning | No malware or content scanning; `default-src 'none'; sandbox` on the objects subdomain mitigates but does not remove the risk. Accept in writing, or add a scan between `confirm` and extraction |
| MinIO single-node | The bucket is mirrored nightly, so the worst-case recovery point for attachments is 24 hours. Confirm that target or shorten the schedule |
| Offsite backups | `RM_OFFSITE_REMOTE` is empty, so backups die with this host's disk. [infra/backup/rclone.conf](../../infra/backup/rclone.conf) is the template |
| Monthly AI budget | None configured means no limit (deploy.md step 7) |

Decisions behind these are listed in [implementation_status.md](../implementation_status.md) §5.
