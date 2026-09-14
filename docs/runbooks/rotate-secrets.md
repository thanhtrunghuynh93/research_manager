# Runbook — Rotate secrets

Trigger: scheduled rotation (every 6 months), a suspected leak, or an operator leaving.

## Ending every session

**There is no key to rotate for this.** Sessions are opaque random tokens whose SHA-256 digest is
a row in `sessions`; no configuration value invalidates one, and restarting the api does not
either. Ending them is an operation:

```bash
docker compose ... exec api python -m app.cli identity revoke-all-sessions
```

It revokes every live session in the deployment, writes a system-actor `audit_events` row per
workspace, and prints how many it ended. Everybody signs in again, including you.

What it does **not** cover: pending invitation and password-reset links keep their own TTLs (7 days
and 2 hours). If one of those has leaked, revoke it per account — `breakglass deactivate-professor`
revokes a professor's sessions and pending invitations together, and issuing a new reset for an
address supersedes the outstanding one.

> Until September 2026 this row read "generate a new `RM_SECRET_KEY`; every session and pending
> invitation token becomes invalid." That was never true: the setting was read by nothing. It has
> been removed rather than wired up, because the opaque-token design is the stronger one and a
> signing key would have bought nothing it does not already have.

## Rotating a credential

| Secret | Where | Steps |
| --- | --- | --- |
| Postgres password | `infra/.env`, database role | `ALTER ROLE rm PASSWORD '…'`; update `POSTGRES_PASSWORD` and `RM_DATABASE_URL`; restart api, worker, backup. |
| MinIO root credentials | `infra/.env` | Update both `MINIO_ROOT_*` and `RM_S3_*`; restart minio, api, worker, backup. |
| OpenAI API key | `infra/.env` | Create the new key in the OpenAI dashboard; update; restart worker and api; revoke the old key. |
| GitHub App private key | file referenced by `RM_GITHUB_APP_PRIVATE_KEY_PATH` | Generate a new key in the App settings; replace the file; restart worker; delete the old key in GitHub. |
| GitHub webhook secret | `infra/.env` and App settings | Update both within the same minute; a mismatch drops webhooks (incremental sync still covers the gap). |
| SMTP password | `infra/.env` | Update; restart worker. |
| age backup key | operator key store | Add the new recipient to `age-recipients.txt` before removing the old one; keep the old identity until every dump encrypted with it has expired. |

After any rotation: `curl /api/readyz`, trigger a manual repository sync, and send a test email
from the admin page. Record the rotation in the operations log.
