# Research Management System

A supervision workspace for professors and their students: weekly report packages, optional repository evidence, professor-approved progress assessments, and a cited research assistant.

Professors are co-equal inside a workspace ([ADR 0011](docs/adr/0011-co-equal-professors.md)) and a professor may belong to several, reading across them and writing into the one they are working in ([ADR 0016](docs/adr/0016-reads-span-membership.md)).

## Documents

- [Overview](docs/overview.md) — what the problem is, what is new here, and how the impact is measured
- [Requirements](docs/research_management_requirements.md) — what the system must do
- [Architecture](docs/architecture.md) — how it is built
- [Repository layout](docs/repo_layout.md) — where things live and the conventions
- [Implementation status](docs/implementation_status.md) — what is built, what is left, and why
- [Use cases](docs/use_cases.md) — what each role can do, and which of it has a screen
- [ADRs](docs/adr/) — decisions and their reasons
- [Runbooks](docs/runbooks/) — operate it

## Quick start (development)

Prerequisites: Docker with Compose, [uv](https://docs.astral.sh/uv/), Node 20+ with npm.

```bash
scripts/run_mock.sh --seed    # everything on the fakes, with the demo dataset
```

That starts postgres, minio and mailpit, runs the migrations, brings up the api and worker with
reload, and serves the app on http://localhost:8020. Assessments are produced by the
deterministic gateway rather than a model provider, which exercises the whole workflow without
spending anything — see `scripts/run_mock.sh --help`.

To run against real integrations instead, fill in `infra/.env.real` and use `scripts/run.sh`. It
refuses to start when a credential is missing rather than falling back to the fake, because the
fallback is silent and its output looks real.

The individual steps are also available as make targets:

```bash
cp .env.example infra/.env
make dev          # starts postgres, minio, mailpit; runs migrations; starts api + worker with reload
make bootstrap    # creates the workspace and professor; prints the invitation link
make web          # frontend dev server on http://localhost:8020 (proxies /api to :8021)
make test         # backend tests (needs Docker for testcontainers)
```

`make bootstrap` prints a single-use invitation link; open it to set the professor's password.
Every later invitation and recovery link travels by email — in development to mailpit, which the
mock stack serves on http://localhost:8025, because a link nobody receives is an account nobody
can reach (AUTH-01).

API health: `http://localhost:8021/api/healthz`. Interactive API docs: `http://localhost:8021/api/docs`.

## Layout

```
backend/    FastAPI application, worker, migrations, tests   (Python 3.12, uv)
frontend/   React + Vite single-page app                     (TypeScript, npm)
infra/      Docker Compose, Caddy, Postgres, backup
scripts/    developer and operations scripts
docs/       specification, architecture, decisions, runbooks
```

See [docs/repo_layout.md](docs/repo_layout.md) for the full tree and the bootstrap order.
