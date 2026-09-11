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
| Assessments stuck in `queued` | Worker down or OpenAI budget/timeouts | Check worker logs; `/api/metrics` queue depth; retry from the admin jobs page after the cause is fixed |
| Missed-deadline emails not sent | SMTP failure | `email_deliveries.state = failed` rows; fix SMTP; the in-app notification is already visible; resend from admin |
| Repository sync stale | Installation token or rate limit | Project workspace shows the error; re-authorize the GitHub App; manual resync |
| Suspected data exposure | Authorization bug | Disable the affected endpoint at Caddy (`respond /api/v1/<path>* 503`), export `audit_events` and access logs for the window, fix, then notify the professor with the scope of what was visible |

## After

Write a short post-incident note: timeline, cause, fix, and the test or alert added so it does not
recur. Reports and approvals are immutable versions, so recovery never rewrites history.
