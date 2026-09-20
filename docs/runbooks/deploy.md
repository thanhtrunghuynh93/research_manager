# Runbook — Deploy

Trigger: a tagged release (`v*`) has built images, or a hotfix must go out.

> **Never `down -v` on this host.** `infra/.env` line 1 says PRODUCTION; the volumes it would
> remove are `pgdata` and `objects` — the database and every uploaded attachment. Stopping the
> stack is `docker compose ... down`, with no `-v`, which leaves both alone. This happened on
> 16 September 2026 and cost the data between the 02:00Z dump and that evening;
> `scripts/guard_docker_volumes.py` now refuses the command through a PreToolUse hook
> (`.claude/settings.json`), but the hook only binds agents working in this repository — a person
> at a shell is on their own.
>
> Backups are encrypted to a key this host does not hold, which is correct and also means recovery
> is not something that can be done from here. `RM_OFFSITE_REMOTE` is currently empty, so the only
> copies are in the `backups` volume on this disk.

0. First deploy only: point **two** A records at the VPS — `<domain>` and `objects.<domain>`.
   Attachments go from the browser straight to the object store and back, never through the API
   (REP-04), so the store is published on its own subdomain and Caddy obtains a certificate for
   it. Without that record, uploads fail at the moment the browser PUTs the file, after the
   student has already chosen it, and `RM_S3_PUBLIC_ENDPOINT` in `infra/.env` must be
   `https://objects.<domain>` to match.
1. On the VPS: `cd /opt/research-management && git fetch --tags && git checkout <tag>`.
2. Run `scripts/preflight.sh`. It compares the keys in `infra/.env` against `.env.example` and
   then checks the things a key comparison structurally cannot see: an empty value, a variable
   that never reaches the container that reads it, a bind-mounted file that does not exist (Docker
   creates those as *directories*, and the backup container then fails on its first nightly run),
   whether both DNS names resolve, and whether `RM_PUBLIC_URL` and `RM_S3_PUBLIC_ENDPOINT` agree
   with `RM_DOMAIN`. It exits non-zero on anything blocking.

   The application enforces its own half: with `RM_ENV=prod` it refuses to start on any shipped
   development default and names all of them at once (`app/core/config.py`). Between the two, the
   variables below are checked rather than remembered — they are documented here because knowing
   *why* each one matters is what makes a preflight failure readable:
   - `RM_METRICS_TOKEN` — with `RM_ENV=prod` and no token, `/api/metrics` refuses everybody and
     the api log says so at start-up. Prometheus scrapes the api container directly on the
     internal network; Caddy blocks `/api/metrics` at the edge either way.
   - `RM_GITHUB_WEBHOOK_SECRET` — only if a GitHub App is configured. With an app id set and no
     webhook secret, `POST /api/v1/webhooks/github` returns 503 rather than verifying deliveries
     against an empty HMAC key, so pushes will not trigger a sync until it is set. It must match
     the secret entered in the GitHub App itself.
3. Pull images: `docker compose --env-file infra/.env -f infra/docker-compose.yml pull`.
4. Take a pre-deploy backup: `docker compose ... exec backup backup.sh`.
5. Apply: `docker compose ... up -d`. Migrations run from the api container:
   `docker compose ... exec api alembic upgrade head`.
6. First deploy only: create the workspace and its professor, then open the printed
   invitation link (valid 7 days, single use):
   ```bash
   docker compose ... exec api python -m app.cli identity bootstrap \
     --name "<workspace>" --email <professor-email> --display-name "<name>"
   ```
7. First deploy only: set the monthly AI budget, or accept that there is none. No budget means no
   limit, not a limit of zero — assessments will run until the provider bill says otherwise.
   ```bash
   curl -fsS -X PUT https://<domain>/api/v1/admin/ai/budgets \
     -H 'content-type: application/json' --cookie "<professor session>" \
     -d '{"monthly_usd": "50.00", "project_monthly_usd": {}}'
   ```
   The professor overview then shows `analysis delayed: budget` rather than a silent absence when
   the limit is reached.
8. Verify attachments end to end, because nothing else exercises the browser-to-store path:
   sign in as a student, attach a file to the weekly package, reload the page, and confirm it is
   still listed. `readyz` reports `object_storage: ok` only when the bucket is actually present,
   but it says nothing about whether a *browser* can reach it — that is DNS, the certificate for
   `objects.<domain>`, and `RM_S3_PUBLIC_ENDPOINT` agreeing with each other.
9. Verify: `curl -fsS https://<domain>/api/readyz` returns `ready`; worker logs show
   `worker starting`; the professor overview loads. If `RM_OPENAI_API_KEY` is unset the api log
   says so at start-up and assessments run on the deterministic fake gateway — which is a valid
   way to run a pilot, but it should be a decision rather than a surprise.

   `readyz` now carries four checks, and `worker` is the one to read closely on a first deploy:
   ```json
   {"status":"ready","checks":{"database":"ok","object_storage":"ok","worker":"skipped","smtp":"ok"}}
   ```
   `worker: skipped` means the queue is empty and nothing has run yet, which is correct for the
   first few minutes and stops being correct after that — the seam check below is what turns it
   into `ok`. `worker: fail` means jobs are waiting and nothing is consuming them. `smtp: fail`
   means no invitation will ever arrive, which on an invitation-only system means nobody can sign
   in; it is checked at most once a minute, so give it that long after fixing the relay.

   Then verify the seam, because a healthy api and a running worker do not prove they are joined:
   submit a report as a student (or `POST /api/v1/admin/assessments/retry`) and confirm a row
   appears in the queue and then leaves it.
   ```bash
   docker compose ... exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "SELECT status, task_name, count(*) FROM procrastinate_jobs GROUP BY 1,2"
   ```
   An empty `todo` and a rising `succeeded` is the product running unattended. Rows stuck in
   `todo` mean the worker is not consuming; no rows at all after a submission mean nothing is
   deferring, which is what `tests/jobs/test_defer_seam.py` exists to catch before a deploy.
9. If readiness fails: `docker compose ... logs --tail=200 api worker`, then roll back with
   `git checkout <previous-tag> && docker compose ... up -d` and `alembic downgrade <rev>` only if
   the migration is reversible (check the migration file first).

Record the deploy (tag, time, operator) in the operations log.

## Loading a demo workspace

Never on the production deployment: `app.cli seed demo` creates a professor with a published
password. On a staging or evaluation host:

```bash
docker compose ... exec api python -m app.cli seed demo
```

## After a mail misconfiguration

If a deadline passed while the mail provider was wrong, fix `RM_SMTP_*` and run the dispatch again.
It is safe to repeat: the notification key and the delivery row make a second run a no-op, so
nobody receives a duplicate (REP-08, AC-19).

```bash
docker compose ... exec api python -m app.cli notifications dispatch-missed-deadline --period <id>
```
