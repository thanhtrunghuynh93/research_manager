# Runbook — Rotate secrets

Trigger: scheduled rotation (every 6 months), a suspected leak, or an operator leaving.

| Secret | Where | Steps |
| --- | --- | --- |
| `RM_SECRET_KEY` | `infra/.env` | Generate a new key; restart api. Every session and pending invitation token becomes invalid; tell users to log in again. |
| Postgres password | `infra/.env`, database role | `ALTER ROLE rm PASSWORD '…'`; update `POSTGRES_PASSWORD` and `RM_DATABASE_URL`; restart api, worker, backup. |
| MinIO root credentials | `infra/.env` | Update both `MINIO_ROOT_*` and `RM_S3_*`; restart minio, api, worker, backup. |
| OpenAI API key | `infra/.env` | Create the new key in the OpenAI dashboard; update; restart worker and api; revoke the old key. |
| GitHub App private key | file referenced by `RM_GITHUB_APP_PRIVATE_KEY_PATH` | Generate a new key in the App settings; replace the file; restart worker; delete the old key in GitHub. |
| GitHub webhook secret | `infra/.env` and App settings | Update both within the same minute; a mismatch drops webhooks (incremental sync still covers the gap). |
| SMTP password | `infra/.env` | Update; restart worker. |
| age backup key | operator key store | Add the new recipient to `age-recipients.txt` before removing the old one; keep the old identity until every dump encrypted with it has expired. |

After any rotation: `curl /api/readyz`, trigger a manual repository sync, and send a test email
from the admin page. Record the rotation in the operations log.
