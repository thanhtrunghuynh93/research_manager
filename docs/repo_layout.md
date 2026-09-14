# Research Management System — Repository Layout

Version 0.2 — 12 September 2026 — companion to [architecture.md](architecture.md) and [research_management_requirements.md](research_management_requirements.md)

This document fixes where code lives, how modules are shaped, and which conventions every contributor follows. It began as a specification for a repository that did not exist; the tree below now describes one that does, and [implementation_status.md](implementation_status.md) §4 records where the two diverged and why. Section 4 of the architecture defines the module boundaries; this document places them on disk and adds tooling, tests, infrastructure, and workflow.

## 1 Principles

1. **One repository, three deployable parts.** `backend/` (api and worker share one image), `frontend/` (static SPA), `infra/` (Compose, Caddy, backup). One `git clone` gives a working local stack.
2. **Directory equals bounded context.** A backend module is a directory with a fixed set of files (section 3.2). The import-linter contract in `backend/pyproject.toml` enforces the dependency direction from architecture section 4.1.
3. **Same names in every layer.** A table `report_versions` maps to ORM class `ReportVersion`, Pydantic schema `ReportVersionOut`, TypeScript type `ReportVersion`, and API path `/api/reports/{id}/versions`. No synonyms.
4. **Generated code is committed only where the build needs it.** The TypeScript API client is generated in CI and checked for drift; Alembic migrations are hand-reviewed and committed.
5. **Docs live with the code.** `docs/` holds the specification, the architecture, this layout, and decision records. Changing a requirement ID or a table name updates the docs in the same pull request.

## 2 Top-level tree

```
research_management/
├── README.md                  quick start, links to docs
├── LICENSE
├── .gitignore
├── .editorconfig
├── .pre-commit-config.yaml    ruff, ruff-format, eslint, prettier, mypy (staged files), gitleaks
├── .github/
│   └── workflows/
│       ├── ci.yml             lint, type-check, tests, build images, client drift check
│       ├── e2e.yml            Playwright against the Compose stack on pull requests to main
│       └── release.yml        tag → build and push images, attach SBOM
├── Makefile                   thin wrappers: make dev, make test, make migrate, make seed, make e2e
├── docs/
│   ├── research_management_requirements.md
│   ├── architecture.md
│   ├── repo_layout.md         this file
│   ├── implementation_status.md  what is built, what is left, decisions taken (section 9)
│   ├── adr/                   architecture decision records, one file each (section 7)
│   ├── runbooks/              deploy.md, production-readiness.md, backup-restore.md, rotate-secrets.md, break-glass.md, incident.md
│   ├── api/                   openapi.json exported by CI for review; changelog of breaking changes
│   └── evaluation/            AI evaluation set description, rubric calibration protocol, pilot gates
├── backend/                   section 3
├── frontend/                  section 4
├── infra/                     section 5
└── scripts/                   section 6
```

## 3 Backend

### 3.1 Tree

```
backend/
├── pyproject.toml             project metadata, dependencies, ruff, mypy, pytest, import-linter contracts
├── uv.lock                    locked dependencies (uv); the Dockerfile installs from this file only
├── Dockerfile                 multi-stage: builder → runtime; same image for api and worker
├── alembic.ini
├── alembic/
│   ├── env.py                 imports app.core.db.metadata; autogenerate compared in CI
│   ├── script.py.mako
│   └── versions/              YYYYMMDD_HHMM_<slug>.py; one migration per pull request where possible
├── app/
│   ├── __init__.py
│   ├── main.py                FastAPI factory: create_app(settings) → mounts api routers, middleware, lifespan
│   ├── worker.py              procrastinate app entry: imports every module's tasks.py, registers periodic tasks
│   ├── cli.py                 typer root command; subcommands registered by modules
│   ├── seed.py                demo dataset and the AC-19 missed-deadline drill
│   ├── tasks.py               periodic jobs that span modules: calendar, queue health, retention
│   ├── observability.py       reads the current state into the metric gauges
│   ├── core/
│   │   ├── config.py          Settings (pydantic-settings), one class, env-var names in section 3.6
│   │   ├── db.py              engine, session factory, metadata, Base, get_session dependency
│   │   ├── authz.py           Scope, resolve_scope(), visible_to() registry, require_role()
│   │   ├── audit.py           write_audit() called from services; AuditEvent model
│   │   ├── jobs.py            procrastinate app object, job key helpers, retry policy constants
│   │   ├── clock.py           now() indirection for tests; calendar helpers (local ↔ UTC)
│   │   ├── context.py         request/job id contextvar readable by lower layers (audit, logging)
│   │   ├── errors.py          domain exceptions → HTTP problem details mapping
│   │   ├── ids.py             uuid7()
│   │   ├── storage.py         ObjectStore protocol, presigned URLs, S3/MinIO and in-memory stores
│   │   ├── metrics.py         the Prometheus series; filled by app/observability.py
│   │   ├── pagination.py      cursor pagination helpers
│   │   └── types.py           shared enums (Role, Visibility, JobState)
│   ├── identity/              module shape in 3.2
│   ├── projects/
│   ├── reporting/
│   │   ├── artifacts.py       uploads, links, versions, download (REP-04)
│   │   ├── extraction.py      text from markdown, csv, pdf, docx, notebooks
│   │   └── links.py           SSRF-guarded link fetching
│   ├── evidence/
│   │   ├── connectors/
│   │   │   ├── base.py        RepositoryConnector protocol, RepoRef, Page, DiffResult, WebhookEvent
│   │   │   ├── github.py      GitHub App implementation
│   │   │   ├── factory.py     picks a connector for a stored repository; falls back loudly
│   │   │   └── fake.py        in-memory connector for tests and demo seed
│   │   └── index/
│   │       ├── chunking.py
│   │       ├── embeddings.py  Embedder protocol + registry; content-hash cache (ai registers the
│   │       │                gateway-backed one at start-up, so evidence never imports app.ai)
│   │       └── retrieval.py   hybrid SQL (permission predicate first, then rank fusion)
│   │   └── tasks.py           incremental_sync (30 min), targeted sync from a webhook
│   ├── assessment/
│   │   ├── snapshot.py        build_snapshot()
│   │   ├── metrics.py         progress_index, plan_completion, coverage_pct, confidence — pure functions
│   │   ├── pipeline/
│   │   │   ├── claims.py      extract_claims job
│   │   │   ├── matching.py    match_claims job
│   │   │   ├── rating.py      rate_rubric job + validate_output()
│   │   │   └── draft.py       create_draft job
│   │   ├── events.py          subscribes to ReportSubmitted; enqueues one job per changed entry
│   │   ├── tasks.py           the pipeline as a worker job
│   │   ├── ops.py             model spend and budgets, for the professor-only admin routes
│   │   └── review.py          approve, override, request_revision services
│   ├── assistant/
│   │   ├── router.py          intent + entity extraction → plan
│   │   ├── facts/             one file per fact function group: reports.py, obligations.py, scores.py, members.py
│   │   ├── retrieval.py       scope-filtered semantic retrieval
│   │   ├── answer.py          generation, citation validation, answer contract
│   │   ├── stream.py          SSE event writer
│   │   └── cache.py           answer_cache with access_epoch check
│   ├── notifications/
│   │   ├── email/
│   │   │   ├── base.py        EmailSender protocol
│   │   │   ├── smtp.py
│   │   │   └── console.py     dev sender: logs to stdout / writes to MinIO "outbox"
│   │   ├── templates/         Jinja2, en/ and vi/ subfolders, plain-text and HTML pairs
│   │   ├── scheduler_tasks.py ensure_periods, freeze_baselines, scan_due_reminders, dispatch_missed_deadline
│   │   ├── preferences.py
│   │   └── cli.py             dispatch-missed-deadline, send-queued-emails
│   ├── exports/               bundle assembly across reporting, projects and assessment (UI-06)
│   ├── ai/
│   │   ├── gateway.py         AIGateway protocol, OpenAIGateway, prompt framing; the only OpenAI import
│   │   ├── bootstrap.py       installs the gateway and the embedder at start-up
│   │   ├── models.py          ai_calls, the cost ledger
│   │   ├── prompts/
│   │   │   ├── registry.py    load(prompt_id, version) → Prompt(model, temperature, schema, text)
│   │   │   ├── extract_claims/v1.md + manifest.toml
│   │   │   ├── match_claims/v1.md + manifest.toml
│   │   │   ├── rate_rubric/v1.md + manifest.toml
│   │   │   ├── route_question/v1.md + manifest.toml
│   │   │   └── answer/v1.md + manifest.toml
│   │   ├── schemas/           Pydantic models for every structured output (RubricOutput, ClaimList, RoutePlan, Answer)
│   │   ├── cost.py            ledger writes, published prices, budget checks
│   │   ├── redaction.py
│   │   └── fake.py            deterministic fake gateway for tests (fixtures keyed by prompt_id)
│   └── api/
│       ├── deps.py            get_scope, get_session, idempotency_key header dependency
│       ├── middleware.py      request id, structured access log, security headers
│       ├── problems.py        RFC 9457 problem responses
│       └── v1/
│           ├── __init__.py    include_routers()
│           ├── auth.py        /api/v1/auth/*
│           ├── users.py
│           ├── projects.py
│           ├── memberships.py
│           ├── milestones.py
│           ├── periods.py
│           ├── reports.py
│           ├── artifacts.py
│           ├── repositories.py
│           ├── webhooks.py    /api/v1/webhooks/github (no session auth; signature only)
│           ├── evidence.py
│           ├── assessments.py
│           ├── assistant.py
│           ├── notifications.py
│           ├── exports.py
│           ├── admin.py       jobs retry, sync status, budgets — professor only
│           └── health.py      /api/healthz, /api/readyz, /api/metrics
└── tests/                     section 3.4
```

### 3.2 Module shape

Every bounded-context package contains the same files, empty ones omitted:

| File | Content | Rule |
| --- | --- | --- |
| `models.py` | SQLAlchemy ORM classes for this module's tables only | Only this module imports them |
| `schemas.py` | Pydantic request/response models, suffixes `In`, `Out`, `Patch` | No ORM imports leak into `api/` |
| `repository.py` | Query functions; every read takes `scope` and applies `visible_to` | No business rules here |
| `service.py` | Use cases; the only entry point other modules may import; writes audit rows; enqueues jobs in the caller's transaction | Public surface of the module |
| `tasks.py` | procrastinate job functions; thin wrappers that open a session and call `service` | Job key built with `core.jobs.key()` |
| `policies.py` | `visible_to` implementations registered with `core.authz` for this module's aggregates | One function per aggregate |
| `events.py` | Domain event dataclasses emitted by `service` (for example `ReportSubmitted`) and in-process handlers registered by dependent modules | Keeps `reporting` unaware of `assessment` |
| `cli.py` | typer subcommands, registered in `app/cli.py` | Optional |

Cross-module reads go through `service.py` functions that return schemas, never ORM instances. Cross-module reactions go through `events.py`: `reporting.service.submit_report()` emits `ReportSubmitted`, and `assessment/events.py` subscribes to enqueue the pipeline. This is how `reporting` avoids importing `assessment` while still triggering it.

### 3.3 Import-linter contracts (`pyproject.toml`)

```toml
[tool.importlinter]
root_package = "app"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Layered bounded contexts"
type = "layers"
layers = ["app.assistant", "app.exports", "app.assessment", "app.evidence", "app.reporting", "app.projects", "app.identity", "app.core"]

[[tool.importlinter.contracts]]
name = "Only assessment and assistant use the AI gateway"
type = "forbidden"
allow_indirect_imports = "true"   # the API calls assessment.service, which may reach the gateway
source_modules = ["app.identity", "app.projects", "app.reporting", "app.evidence", "app.notifications", "app.exports", "app.api", "app.core"]
forbidden_modules = ["app.ai"]

[[tool.importlinter.contracts]]
name = "Only the gateway imports the OpenAI SDK"
type = "forbidden"
source_modules = ["app"]
forbidden_modules = ["openai"]
ignore_imports = ["app.ai.gateway -> openai"]
unmatched_ignore_imports_alerting = "none"

[[tool.importlinter.contracts]]
name = "Notifications depend on reporting and core only"
type = "forbidden"
source_modules = ["app.notifications"]
forbidden_modules = ["app.evidence", "app.assessment", "app.assistant"]

[[tool.importlinter.contracts]]
name = "API never touches ORM models directly"
type = "forbidden"
allow_indirect_imports = "true"   # the API reaches models through service.py by design
source_modules = ["app.api"]
forbidden_modules = ["app.identity.models", "app.projects.models", "app.reporting.models", "app.evidence.models", "app.assessment.models", "app.assistant.models", "app.notifications.models"]
```

### 3.4 Tests

```
backend/tests/
├── conftest.py               Postgres via testcontainers (pgvector image), transactional session per test,
│                             FakeAIGateway, FakeConnector, frozen clock fixture, scope fixtures (prof, student_a, student_b)
├── factories.py              factory_boy factories for every model
├── unit/                     pure functions: metrics, calendar, redaction, chunking, validate_output
│   └── test_metrics.py       includes the spec example: ratings 3,4,3,2 → 78.75 → 79
├── module/                   service-level tests per bounded context, real DB, fakes for AI and GitHub
│   ├── identity/  projects/  reporting/  evidence/  assessment/  assistant/  notifications/
├── authz/                    one test per access acceptance scenario (AC-02, AC-11, QA-06); parametrised over API, search, download, export
├── api/                      HTTP tests through the ASGI app; OpenAPI schema snapshot
├── jobs/                     idempotency and retry: duplicate webhook, retried sync range, killed worker (AC-09, AC-13)
├── acceptance/               test_ac_01.py … test_ac_19.py, each named after the requirements scenario it proves
└── evaluation/               AI evaluation harness; skipped in CI unless RM_EVAL=1; reads docs/evaluation set
```

Conventions: test names state the behaviour (`test_late_submission_keeps_first_submitted_at`); every acceptance test docstring quotes the scenario row from the requirements; coverage gate 85 % on `app/`, 100 % on `assessment/metrics.py` and `core/authz.py`.

### 3.5 Tooling

| Tool | Configuration | Purpose |
| --- | --- | --- |
| uv | `pyproject.toml`, `uv.lock` | Dependency resolution and virtualenv |
| ruff | `[tool.ruff]` line length 100, rules E,F,I,B,UP,S,N | Lint and format |
| mypy | strict, plugins for SQLAlchemy and Pydantic | Type check |
| import-linter | section 3.3 | Module boundaries |
| pytest | `-p no:cacheprovider`, `asyncio_mode = auto`, markers `unit`, `module`, `api`, `authz`, `acceptance`, `evaluation_contract`, `evaluation` | Tests |
| alembic | autogenerate diff checked in CI (`make migrate-check`) | Schema drift |
| gitleaks | pre-commit and CI | Secret scanning |

### 3.6 Environment variables

All read once by `core/config.py`. Prefix `RM_`.

| Variable | Used by | Notes |
| --- | --- | --- |
| `RM_ENV` | all | `dev`, `test`, `prod` |
| `RM_DATABASE_URL` | api, worker | Postgres DSN |
| `RM_PUBLIC_URL` | api, worker | Absolute links in emails |
| `RM_S3_ENDPOINT`, `RM_S3_BUCKET`, `RM_S3_ACCESS_KEY`, `RM_S3_SECRET_KEY` | api, worker | MinIO |
| `RM_OPENAI_API_KEY`, `RM_OPENAI_MODEL`, `RM_OPENAI_EMBED_MODEL` | worker, api (assistant) | Gateway only |
| `RM_GITHUB_APP_ID`, `RM_GITHUB_APP_PRIVATE_KEY_PATH`, `RM_GITHUB_WEBHOOK_SECRET` | api (webhooks), worker | Connector |
| `RM_SMTP_HOST`, `RM_SMTP_PORT`, `RM_SMTP_USER`, `RM_SMTP_PASSWORD`, `RM_MAIL_FROM` | worker | Email |
| `RM_UPLOAD_MAX_FILE_MB` | api | Default 25 |
| `RM_LOG_LEVEL`, `RM_LOG_JSON` | all | Observability |

`.env.example` at repository root lists every variable with a safe development value; `infra/.env` is git-ignored.

## 4 Frontend

```
frontend/
├── package.json               scripts: dev, build, preview, lint, typecheck, test, e2e, gen:api
├── package-lock.json          npm; CI installs with `npm ci`
├── vite.config.ts             /api proxy to localhost:8021 in dev; build to dist/
├── tsconfig.json              project references → tsconfig.app.json (strict, alias @/ → src/) and tsconfig.node.json
├── tailwind.config.ts, postcss.config.js, components.json (shadcn)
├── eslint.config.js           ESLint 9 flat config (typescript-eslint, react-hooks, react-refresh)
├── .prettierrc, .prettierignore
├── index.html
├── public/                    favicon, static assets
├── playwright.config.ts
├── e2e/                       Playwright specs named after user journeys: submit-weekly-package.spec.ts,
│                              review-and-approve.spec.ts, missed-deadline-email.spec.ts (uses console sender outbox)
└── src/
    ├── main.tsx               providers: QueryClient, Router, I18n, Theme
    ├── app/
    │   ├── router.tsx         routes from architecture 4.2; role guards
    │   └── layout/            AppShell, Sidebar, TopBar, ScopeBadge (assistant scope display)
    ├── api/
    │   ├── client.ts          fetch wrapper: credentials include, problem-details errors, idempotency header helper
    │   ├── generated/         openapi-typescript output; regenerated by `npm run gen:api`; drift checked in CI
    │   └── sse.ts             EventSource helper for assistant streams
    ├── features/              one folder per backend module or screen
    │   ├── auth/              login, accept-invitation, reset-password
    │   ├── overview/          professor overview (UI-01)
    │   ├── me/                student overview and profile subset (UI-02, UI-04)
    │   ├── projects/          workspace, milestones, decisions, repositories (UI-03)
    │   ├── students/          research profile (UI-04)
    │   ├── report/            weekly package editor: EntryTabs, MarkdownEditor, EvidenceList, PlanEditor, SubmitDialog
    │   ├── review/            three-pane review workspace (UI-05)
    │   ├── assessments/       released assessment view, correction request
    │   ├── assistant/         chat, scope controls, citation side panel
    │   ├── notifications/     list, preferences (UI-07)
    │   └── exports/           filters and download (UI-06)
    ├── components/
    │   ├── ui/                shadcn primitives (generated, not hand-edited)
    │   ├── markdown/          renderer with KaTeX, tables, safe links
    │   ├── evidence/          EvidenceBadge, FreshnessBadge, CitationLink
    │   └── forms/             Field wrappers, AutosaveIndicator
    ├── hooks/                 useAutosave, useScope, useIdempotencyKey
    ├── lib/                   dates (period formatting in workspace timezone), i18n setup, zod schemas shared by forms
    ├── locales/
    │   ├── en/*.json
    │   └── vi/*.json
    └── test/                  Vitest + Testing Library unit tests, setup.ts, msw handlers
```

Conventions: a `features/<name>/` folder contains `pages/`, `components/`, `queries.ts` (TanStack Query hooks with keys `[feature, scope, ...ids]`), and `types.ts` re-exporting generated types. No feature imports another feature's components; shared pieces move to `components/`. Server state comes only from `queries.ts`; client-only state uses local React state or a small Zustand store inside the feature.

## 5 Infrastructure

```
infra/
├── docker-compose.yml         production: caddy, api, worker, postgres, minio, backup
├── docker-compose.dev.yml     overrides: bind mounts, hot reload, mailpit for email, exposed ports
├── .env.example
├── caddy/
│   └── Caddyfile              TLS, serve frontend/dist, reverse_proxy /api/* api:8000, security headers
├── postgres/
│   ├── init/01_extensions.sql  CREATE EXTENSION vector, pg_trgm
│   └── postgresql.conf         tuned parameters for the VPS
├── backup/
│   ├── Dockerfile              postgres client, age, rclone, cron
│   ├── backup.sh               pg_dump -Fc | age → local, minio mirror, rclone sync offsite; prune 30d/12m
│   └── restore.sh              documented in docs/runbooks/backup-restore.md; used by the restore drill
└── observability/
    ├── promtail or vector config (optional)
    └── dashboards/            Grafana JSON if a metrics stack is added later
```

Image build: one `backend/Dockerfile` produces `rm-backend`; `frontend/` builds to `dist/` in CI and is copied into the `caddy` image by `infra/caddy/Dockerfile`, so production runs two custom images plus stock `postgres`, `minio`, and `backup`.

## 6 Scripts

```
scripts/
├── run.sh                     start the stack in real mode; refuses to start with a credential
│                              missing, because each integration otherwise falls back to a fake
├── run_mock.sh                the same in mock mode: fake gateway, in-memory connector, mailpit;
│                              a separate compose project, so seeded demo data never mixes in
├── dev-up.sh                  compose dev stack, wait for readiness, run migrations
├── seed_demo.py               calls app.cli seed: one professor, 6 students, 4 projects, 8 periods, fake repo events
├── seed_benchmark.py          50 students × 30 projects × 3 years, 100k chunks, for the performance suite
├── bench/                     k6 scripts for the p95 targets in architecture section 15
├── gen_api_client.sh          exports openapi.json from the app and runs openapi-typescript
├── check_traceability.py      asserts every requirement ID in docs/research_management_requirements.md
│                              appears in docs/architecture.md section 16 and in at least one test docstring
└── restore_drill.sh           spins a scratch stack, restores latest backup, runs smoke checks
```

## 7 Documentation conventions

- **ADRs** in `docs/adr/NNNN-<slug>.md` with Context, Decision, Consequences. Seed set from the architecture: 0001 modular monolith, 0002 procrastinate over Redis queue, 0003 pgvector in Postgres, 0004 application-level authorization before RLS, 0005 GitHub App connector, 0006 deterministic metrics outside the model, 0007 OpenAI behind a single gateway.
- **Runbooks** are imperative checklists; every runbook names the alert or event that triggers it.
- **Requirement references** in code use the ID in a comment on the function that implements it, for example `# REP-08` above `dispatch_missed_deadline`, so `grep REP-08` finds spec, architecture, code, and tests.

## 8 Branching, commits, and CI

- `main` is deployable; feature branches `feat/<area>-<slug>`, fixes `fix/<slug>`; squash merge with a Conventional Commits title (`feat(reporting): freeze plan baselines at period start`).
- Pull request template asks for: requirement IDs touched, migration present yes/no, docs updated yes/no, screenshots for UI.
- `ci.yml` jobs: `backend-lint` (ruff, mypy, import-linter), `backend-test` (pytest with testcontainers, coverage gate), `migrate-check` (alembic autogenerate produces no diff), `frontend` (eslint, tsc, vitest, build), `client-drift` (regenerate API client and fail on diff), `traceability` (`scripts/check_traceability.py`), `images` (build both images, Trivy scan).
- `e2e.yml` runs Playwright against the dev Compose stack with the console email sender and fake connector.
- `release.yml` on tag `v*`: build, push to the registry, generate SBOM, create release notes from commits.

## 9 Bootstrap order

Progress against this order, and the decisions taken while working through it, are recorded in
[implementation_status.md](implementation_status.md).

The first pull requests, in dependency order, so that the tree above fills in without dead directories:

1. Repository skeleton: top-level files, `backend/pyproject.toml`, `core/`, `main.py`, health endpoints, `infra/` dev Compose, CI lint and test jobs.
2. `identity/`: users, invitations, sessions, `authz.Scope`, first migration, authz test harness.
3. `projects/` and `reporting/` with periods, obligations, drafts, submission, versions, artifacts; frontend report editor and student overview.
4. `notifications/` with scheduler tasks and the missed-deadline email (REP-08) on the console sender; e2e for AC-19.
5. `evidence/` with the fake connector, then the GitHub App connector; identity mapping; indexing and retrieval.
6. `assessment/`: snapshot, metrics with unit tests, pipeline on the fake gateway, review workspace.
7. `ai/` gateway against OpenAI, prompt registry, cost ledger; evaluation harness.
8. `assistant/`, exports, professor overview polish, backup container and restore drill, release workflow.
