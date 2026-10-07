# Research Management System

A supervision workspace for professors and their students: weekly report packages with attached evidence, professor-approved progress assessments, and a cited research assistant.

Professors are co-equal inside a workspace ([ADR 0011](docs/adr/0011-co-equal-professors.md)) and a professor may belong to several, reading across them and writing into the one they are working in ([ADR 0016](docs/adr/0016-reads-span-membership.md)).

## Documents

- [Overview](docs/overview.md) — what the problem is, what is new here, and how the impact is measured
- [Requirements](docs/research_management_requirements.md) — what the system must do
- [Architecture](docs/architecture.md) — how it is built
- [Repository layout](docs/repo_layout.md) — where things live and the conventions
- [Implementation status](docs/implementation_status.md) — what is built, what is left, and why
- [Use cases](docs/use_cases.md) — what each role can do, and which of it has a screen
- [Domain model](docs/domain_model.md) — how professor, student, workspace, project and reports are organized
- [ADRs](docs/adr/) — decisions and their reasons
- [Runbooks](docs/runbooks/) — operate it

## Running it

The system runs as one production Compose stack (`infra/docker-compose.yml`) configured by a
root-owned `infra/.env` made from [.env.example](.env.example). Deploying, bootstrapping the first
professor and checking readiness are in the [deploy runbook](docs/runbooks/deploy.md).

## Checks

```bash
make test         # backend tests (needs Docker for testcontainers)
make lint         # ruff, import-linter, eslint
make typecheck    # mypy, tsc
make check-docs   # docs against the tree
```

Frontend unit tests: `cd frontend && npm test -- --run`.

## Layout

```
backend/    FastAPI application, worker, migrations, tests   (Python 3.12, uv)
frontend/   React + Vite single-page app                     (TypeScript, npm)
infra/      Docker Compose, Caddy, Postgres, backup
scripts/    developer and operations scripts
docs/       specification, architecture, decisions, runbooks
```

See [docs/repo_layout.md](docs/repo_layout.md) for the full tree and the bootstrap order.
