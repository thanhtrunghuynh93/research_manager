# Research Management System

A supervision workspace for a professor and their students: projects and memberships, a weekly
report package per student with attached files, a weekly schedule that decides who owes what and
emails anyone who misses the deadline, AI-drafted progress assessments that cite their evidence and
are published only after the professor reviews them, and a professor overview of the week.

Professors are co-equal inside a workspace ([ADR 0011](docs/adr/0011-co-equal-professors.md)). A
professor may belong to several workspaces and reads and writes in the one they are working in,
switching from the header ([ADR 0020](docs/adr/0020-reads-follow-the-workspace-you-are-in.md),
[ADR 0021](docs/adr/0021-the-read-set-is-one-workspace.md)); a student belongs to exactly one.

## Documents

- [Overview](docs/overview.md) — the problem, what is new, and how impact is measured
- [Requirements](docs/research_management_requirements.md) — what the system must do
- [Architecture](docs/architecture.md) — how it is built
- [Use cases](docs/use_cases.md) — what each role can do: endpoint and screen
- [Domain model](docs/domain_model.md) — how workspace, professor, student, project and reports relate
- [Implementation status](docs/implementation_status.md) — what is built, withdrawn, missing and still to decide
- [Repository layout](docs/repo_layout.md) — where things live and the conventions
- [ADRs](docs/adr/) — decisions and their reasons
- [Runbooks](docs/runbooks/) — deploy and operate it
- [Evaluation](docs/evaluation/) — how the assessment is calibrated

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

See [docs/repo_layout.md](docs/repo_layout.md) for the full tree.
