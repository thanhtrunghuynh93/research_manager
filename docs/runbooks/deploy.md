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
7. Verify: `curl -fsS https://<domain>/api/readyz` returns `ready`; worker logs show
   `worker starting`; the professor overview loads.
8. If readiness fails: `docker compose ... logs --tail=200 api worker`, then roll back with
   `git checkout <previous-tag> && docker compose ... up -d` and `alembic downgrade <rev>` only if
   the migration is reversible (check the migration file first).

Record the deploy (tag, time, operator) in the operations log.
