# Research Management System

A supervision workspace for one professor and their students: weekly report packages, optional repository evidence, professor-approved progress assessments, and a cited research assistant.

## Documents

- [Requirements](docs/research_management_requirements.md) — what the system must do (v0.3)
- [Architecture](docs/architecture.md) — how it is built
- [Repository layout](docs/repo_layout.md) — where things live and the conventions
- [Implementation status](docs/implementation_status.md) — what is built, what is left, and why
- [ADRs](docs/adr/) — decisions and their reasons
- [Runbooks](docs/runbooks/) — operate it

## Quick start (development)

Prerequisites: Docker with Compose, [uv](https://docs.astral.sh/uv/), Node 20+ with npm.

```bash
cp .env.example infra/.env
make dev          # starts postgres, minio, mailpit; runs migrations; starts api + worker with reload
make bootstrap    # creates the workspace and professor; prints the invitation link
make web          # frontend dev server on http://localhost:5173 (proxies /api to :8000)
make test         # backend tests (needs Docker for testcontainers)
```

`make bootstrap` prints a single-use invitation link; open it to set the professor's password.
In development the api logs the invitation and recovery links for every account until the
notifications module sends them by email.

API health: `http://localhost:8000/api/healthz`. Interactive API docs: `http://localhost:8000/api/docs`.

## Layout

```
backend/    FastAPI application, worker, migrations, tests   (Python 3.12, uv)
frontend/   React + Vite single-page app                     (TypeScript, npm)
infra/      Docker Compose, Caddy, Postgres, backup
scripts/    developer and operations scripts
docs/       specification, architecture, decisions, runbooks
```

See [docs/repo_layout.md](docs/repo_layout.md) for the full tree and the bootstrap order.
