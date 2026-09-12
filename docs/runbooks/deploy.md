# Runbook — Deploy

Trigger: a tagged release (`v*`) has built images, or a hotfix must go out.

1. On the VPS: `cd /opt/research-management && git fetch --tags && git checkout <tag>`.
2. Confirm `infra/.env` has every variable in `.env.example` (`diff <(grep -o '^[A-Z_]*' .env.example | sort) <(grep -o '^[A-Z_]*' infra/.env | sort)`).
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
8. Verify: `curl -fsS https://<domain>/api/readyz` returns `ready`; worker logs show
   `worker starting`; the professor overview loads. If `RM_OPENAI_API_KEY` is unset the api log
   says so at start-up and assessments run on the deterministic fake gateway — which is a valid
   way to run a pilot, but it should be a decision rather than a surprise.
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
