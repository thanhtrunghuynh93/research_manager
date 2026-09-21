# Runbook — Deploy

Trigger: a change on `main` is to go out, or a hotfix must. Nothing here is driven by a tag today — the stack is built from the checkout, so what deploys is what is committed and present in the working tree.

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
1. On the VPS, in the checkout the compose project runs from — `/root/workspace/research_manager` on this host, which is what `docker inspect research-management-api-1` reports as the compose working directory, not `/opt/…`:
   `git fetch origin && git checkout main && git pull --ff-only`. Deploy a commit that is pushed: the build reads the tree, so an uncommitted edit ships and no one can reproduce it.
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
3. Get the images. **This host builds them; it pulls nothing.** `RM_BACKEND_IMAGE` and
   `RM_CADDY_IMAGE` in `infra/.env` are `rm-backend:local` and `rm-caddy:local`, which no registry
   holds, and the compose project's working directory *is* the checkout — so the deployed artifact
   is whatever is in the tree at this moment, and committing before deploying is what makes it
   reproducible.

   ```bash
   docker compose --env-file infra/.env -f infra/docker-compose.yml build
   ```

   The caddy image builds the SPA (`infra/caddy/Dockerfile` runs `npm run build` and copies
   `dist` into `/srv`), so a frontend change ships only if caddy is rebuilt. `pull` is the step a
   registry deployment would run instead, and it is kept here for the day this uses one.

   > **The mock stack shares these tags unless told otherwise.** `scripts/run_mock.sh` builds the
   > `builder` target — the one with `uv` in it — and writing that to `rm-backend:local` leaves the
   > production containers pointing at a dev image the moment they are next recreated. It happened
   > on 21 September 2026 in the other direction: a production build overwrote the tag and the mock
   > worker then died with `uv: executable file not found`. Set `RM_BACKEND_IMAGE=rm-backend:dev`
   > and `RM_CADDY_IMAGE=rm-caddy:dev` in `infra/.env.mock` so the two can never trade images.
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
10. If readiness fails: `docker compose ... logs --tail=200 api worker`, then roll back with
    `git checkout <previous-tag> && docker compose ... up -d`, **rebuilding** as in step 3, and
    `alembic downgrade <rev>` only if the migration is reversible (check the migration file first).

A frontend-only change is verified from the served bundle rather than from the API, because
`readyz` cannot see it:

```bash
BUNDLE=$(curl -s https://<domain>/ | grep -o '/assets/[^"]*\.js' | head -1)
curl -s "https://<domain>$BUNDLE" | grep -c "<a string the change introduced>"
```

Record the deploy (tag, time, operator) in the operations log. There is no operations log in this
repository; if one is being kept, it is somewhere else, and if it is not, this line is the thing
to fix rather than to follow.

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
