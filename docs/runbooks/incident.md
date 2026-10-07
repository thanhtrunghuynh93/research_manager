# Runbook — Incident response

Trigger: readiness failing, reports not submitting, assessments stuck, emails not sent, or a
suspected data exposure.

## First five minutes

1. `curl -fsS https://<domain>/api/readyz` — which check fails?
2. `docker compose ... ps` — is any container restarting?
3. `docker compose ... logs --tail=200 api worker` — look for the request id from the user's error.

## By symptom

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `database: fail` | Postgres down or disk full | `df -h`; `docker compose ... logs postgres`; restart postgres; if disk full, prune Docker and old local backups |
| `object_storage: fail` | MinIO down | Restart minio; uploads fail but report text submission still works |
| Assessments stuck or missing | Worker down, budget spent, or model errors | Check worker logs and `/api/metrics` queue depth; the overview's stalled analyses say which, and its Retry button re-runs one after the cause is fixed (`POST /api/v1/admin/assessments/retry`) |
| Missed-deadline or invitation emails not sent | SMTP failure (`readyz` shows `smtp: fail`; the overview shows a mail warning) | Fix `RM_SMTP_*` (`scripts/set-smtp-password.sh`); then `app.cli notifications send-queued-emails`, and `app.cli notifications dispatch-missed-deadline --period <id>` if a deadline passed meanwhile (deploy.md). Re-invite anyone whose invitation failed from `/people` |
| Suspected data exposure | Authorization bug | Disable the affected endpoint at Caddy (`respond /api/v1/<path>* 503`), export `audit_events` and access logs for the window, fix, then notify the professor with the scope of what was visible |

## After

Write a short post-incident note: timeline, cause, fix, and the test or alert added so it does not
recur. Reports and approvals are immutable versions, so recovery never rewrites history.
