# Research Management System — Repository Layout

Version 0.6 — 7 October 2026 — companion to [architecture.md](architecture.md), [research_management_requirements.md](research_management_requirements.md) v0.14 and [use_cases.md](use_cases.md)

Where code lives, how modules are shaped, and which conventions every contributor follows. Section 4 of the architecture defines the module boundaries; this document places them on disk and adds tooling, tests, infrastructure and workflow. `scripts/check_docs.py` checks that every path in the trees below exists and that every backend module, API router, frontend feature, hook and locale is named here.

## 1 Principles

1. **One repository, three deployable parts.** `backend/` (api and worker share one image), `frontend/` (static SPA), `infra/` (Compose, Caddy, backup). One `git clone` gives a working local stack.
2. **Directory equals bounded context.** A backend module is a directory with a fixed set of files (section 3.2). The import-linter contract in `backend/pyproject.toml` enforces the dependency direction from architecture section 4.1.
3. **Same names in every layer.** A table `report_versions` maps to ORM class `ReportVersion`, Pydantic schema `ReportVersionOut`, TypeScript type `ReportVersion`, and API path `/api/v1/reports/{id}/versions`. No synonyms.
4. **Generated code is committed only where the build needs it.** The TypeScript API client is generated in CI and checked for drift; Alembic migrations are hand-reviewed and committed.
5. **Docs live with the code.** `docs/` holds the specification, the architecture, this layout, and decision records. Changing a requirement ID or a table name updates the docs in the same pull request.

## 2 Top-level tree

```
research_management/
├── README.md                  quick start, links to docs
├── .gitignore
├── .editorconfig
├── .pre-commit-config.yaml    ruff, ruff-format, eslint, prettier, mypy (staged files), gitleaks
├── .github/
│   └── workflows/
│       ├── ci.yml             lint, type-check, tests, build images, client drift check
│       └── release.yml        tag → build and push images, attach SBOM
├── Makefile                   thin wrappers: make test, make lint, make typecheck, make check-docs
├── docs/
│   ├── research_management_requirements.md
│   ├── architecture.md
│   ├── repo_layout.md         this file
│   ├── implementation_status.md  what is built, what was withdrawn, known gaps, open decisions
│   ├── use_cases.md           what each role can do: the endpoint and the screen that calls it
│   ├── domain_model.md        how professor, student, workspace, project and reports relate
│   ├── overview.md            the product summary: problem, innovation, impact
│   ├── adr/                   architecture decision records, one file each (section 7)
│   ├── runbooks/              deploy.md, production-readiness.md, backup-restore.md, rotate-secrets.md, break-glass.md, incident.md
│   ├── api/                   openapi.json exported for review; README.md lists breaking changes
│   └── evaluation/            assessment evaluation set, calibration protocol, pilot gates
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
│   ├── tasks.py               periodic jobs that span modules: ensure_periods (15 0), freeze_baselines
│   │                          (30 0), queue_health (*/5), retention_sweep (45 1; also deletes
│   │                          jobs finished over seven days ago)
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
│   │   ├── artifacts.py       uploads, confirm, removal, versions, download, extraction hand-off (REP-04)
│   │   ├── extraction.py      text from markdown, csv, pdf, docx, notebooks
│   ├── evidence/              the access-labelled evidence index the assessment snapshot reads
│   │   └── index/
│   │       └── chunking.py    what an assessment cites
│   │   └── tasks.py           retries of report-entry and attachment indexing
│   ├── assessment/
│   │   ├── snapshot.py        build_snapshot()
│   │   ├── metrics.py         progress_index, plan_completion, coverage_pct, confidence — pure functions
│   │   ├── pipeline/          a placeholder package: the four steps — extract claims, match them,
│   │   │                      rate the rubric, draft — run inside service.py::run_pipeline
│   │   ├── service.py         the pipeline, and approve / withdraw. There is
│   │   │                      no review.py, and override is a branch of approve rather than its
│   │   │                      own service
│   │   ├── events.py          subscribes to ReportSubmitted; enqueues one job per changed entry
│   │   ├── tasks.py           the pipeline as a worker job
│   │   └── ops.py             model spend and budgets, for the professor-only admin routes
│   ├── overview/              the professor overview's numbers (UI-01, REP-08, AC-15); no models,
│   │   ├── __init__.py        no routes of its own, no AI
│   │   └── service.py         next_deadline, missing_reports, week_reports, review_queue,
│   │                          stalled_analyses, display_name
│   ├── notifications/
│   │   ├── email/
│   │   │   ├── base.py        EmailSender protocol
│   │   │   ├── smtp.py
│   │   │   └── console.py     dev sender: logs to stdout / writes to MinIO "outbox"
│   │   ├── templates/         Jinja2 triples — .txt, .html, .subject.txt — for invitation,
│   │   │                      missed_deadline and password_reset. No locale subfolders:
│   │   │                      migration 0016 dropped the column
│   │   ├── scheduler_tasks.py scan_due_reminders, send_queued_emails, send_token_email,
│   │   │                      dispatch_missed_deadline — ensure_periods and freeze_baselines
│   │   │                      live in app/tasks.py
│   │   └── cli.py             dispatch-missed-deadline, send-queued-emails
│   ├── ai/
│   │   ├── gateway.py         AIGateway protocol, OpenAIGateway, prompt framing; the only OpenAI import
│   │   ├── bootstrap.py       installs the gateway at start-up
│   │   ├── models.py          ai_calls, the cost ledger
│   │   ├── prompts/
│   │   │   ├── registry.py    load(prompt_id, version) → Prompt(model, temperature, schema, text)
│   │   │   ├── extract_claims/v1.md + manifest.toml
│   │   │   ├── match_claims/v1.md + manifest.toml
│   │   │   └── rate_rubric/v1.md, v2.md, v3.md + manifest.toml
│   │   ├── schemas/           Pydantic models for every structured output (ClaimList, ClaimVerdicts, RubricOutput)
│   │   │                      and strict.py, which asserts each is one the provider's strict mode accepts
│   │   ├── cost.py            ledger writes, published prices, budget checks
│   │   ├── redaction.py
│   │   └── fake.py            deterministic fake gateway for tests; refuses a schema the provider would refuse
│   └── api/
│       ├── deps.py            get_scope, get_session, idempotency_key header dependency
│       ├── middleware.py      request id, structured access log, security headers
│       ├── problems.py        RFC 9457 problem responses
│       └── v1/
│           ├── __init__.py    include_routers()
│           ├── auth.py        login, logout, /auth/me, accept-invitation, password reset
│           ├── users.py       the roll, invitations, remove, deactivate/reactivate, and
│           │                  moving a student to another workspace (AUTH-06)
│           ├── workspaces.py  list, create, read, rename, join, leave, archive
│           │                  (ADR 0012/14/15/20). Renaming and archiving are owner-only;
│           │                  entering and reading follow membership as well
│           ├── projects.py    projects and members — membership has no router of its own
│           ├── reports.py     calendar, periods, obligations, excuse/extend, draft, submit,
│           │                  versions, revisions — there is no periods.py
│           ├── artifacts.py   presigned upload, confirm, remove, versions, download (REP-04)
│           ├── assessments.py  drafts, approve, withdraw, evidence, trends
│           ├── overview.py    the professor's current week (UI-01), from app.overview
│           ├── admin.py       assessment retry, AI usage and budgets — prof only
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

Cross-module reads go through `service.py` functions that return schemas, never ORM instances. Cross-module reactions go through `events.py`: `reporting.service.submit_report()` emits `ReportSubmitted`, and `assessment/events.py` subscribes to enqueue the pipeline. This is how `reporting` avoids importing `assessment` while still triggering it. The same seam runs the other way down the layers: `projects/events.py` emits `MembershipStarted`, and `reporting` subscribes to derive the week's obligation at once rather than at the next nightly run — `projects` cannot call `reporting`, which sits above it.

### 3.3 Import-linter contracts (`pyproject.toml`)

```toml
[tool.importlinter]
root_package = "app"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Layered bounded contexts"
type = "layers"
layers = ["app.overview", "app.assessment", "app.evidence", "app.reporting", "app.projects", "app.identity", "app.core"]

[[tool.importlinter.contracts]]
name = "Only assessment uses the AI gateway"
type = "forbidden"
allow_indirect_imports = "true"   # the API calls assessment.service, which may reach the gateway
source_modules = ["app.identity", "app.projects", "app.reporting", "app.evidence", "app.notifications", "app.overview", "app.api", "app.core"]
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
forbidden_modules = ["app.evidence", "app.assessment", "app.overview"]

[[tool.importlinter.contracts]]
name = "API never touches ORM models directly"
type = "forbidden"
allow_indirect_imports = "true"   # the API reaches models through service.py by design
source_modules = ["app.api"]
forbidden_modules = ["app.identity.models", "app.projects.models", "app.reporting.models", "app.evidence.models", "app.assessment.models", "app.notifications.models"]
```

### 3.4 Tests

```
backend/tests/
├── conftest.py               Postgres via testcontainers (postgres:16-bookworm), transactional session per test,
│                             FakeAIGateway, frozen clock fixture, scope fixtures (prof, student_a, student_b)
├── factories.py              plain async row builders: make_project, make_week, make_entry, submit, login
├── unit/                     pure functions: metrics, calendar, redaction, chunking, validate_output
│   └── test_metrics.py       includes the spec example: ratings 3,4,3,2 → 78.75 → 79
├── module/                   service-level tests per bounded context, real DB, fakes for AI
│   ├── identity/  projects/  reporting/  evidence/  assessment/  overview/  notifications/  ai/
│                             (identity/test_user_visibility.py: one predicate decides every read of a user record;
│                             the access scenarios AC-02 and AC-11 live in acceptance/, Scope.within in unit/test_authz.py)
├── api/                      HTTP tests through the ASGI app; OpenAPI schema snapshot
├── jobs/                     idempotency and retry: periodic tasks, the defer seam, killed worker (AC-13)
├── acceptance/               test_ac_01.py … test_ac_19.py, each named after the requirements scenario it proves (04, 06, 09 withdrawn)
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
| pytest | `-p no:cacheprovider`, `asyncio_mode = auto`, markers `unit`, `module`, `api`, `acceptance`, `evaluation_contract`, `evaluation` | Tests |
| alembic | autogenerate diff checked in CI (`migrate-check` job) | Schema drift |
| gitleaks | pre-commit and CI | Secret scanning |

### 3.6 Environment variables

All read once by `core/config.py`. Prefix `RM_`.

| Variable | Used by | Notes |
| --- | --- | --- |
| `RM_ENV` | all | `dev`, `test`, `prod` |
| `RM_DATABASE_URL` | api, worker | Postgres DSN |
| `RM_PUBLIC_URL` | api, worker | Absolute links in emails |
| `RM_S3_ENDPOINT`, `RM_S3_PUBLIC_ENDPOINT`, `RM_S3_BUCKET`, `RM_S3_ACCESS_KEY`, `RM_S3_SECRET_KEY` | api, worker | MinIO; the public endpoint is what browsers upload to |
| `RM_OPENAI_API_KEY`, `RM_OPENAI_MODEL` | worker | Gateway only |
| `RM_SMTP_HOST`, `RM_SMTP_PORT`, `RM_SMTP_USER`, `RM_SMTP_PASSWORD`, `RM_MAIL_FROM` | worker | Email |
| `RM_UPLOAD_MAX_FILE_MB` | api | Default 25 |
| `RM_LOG_LEVEL`, `RM_LOG_JSON` | all | Observability |
| `RM_METRICS_TOKEN` | api | Bearer token for `/api/metrics`; required in production |
| `RM_WORKER_CONCURRENCY` | worker | Concurrent jobs |

Compose and the backup container read a few more (`RM_DOMAIN`, `RM_ACME_EMAIL`, `RM_BACKEND_IMAGE`, `RM_CADDY_IMAGE`, `RM_AGE_RECIPIENTS_FILE`, `RM_RCLONE_CONF`, `RM_OFFSITE_REMOTE`). `.env.example` at the repository root is the complete list, with placeholders the api refuses in production; `infra/.env` is git-ignored. There are no `RM_GITHUB_*` or `RM_OPENAI_EMBED_MODEL` settings any more; a live `infra/.env` that still carries them is harmless (see the deploy runbook).

## 4 Frontend

```
frontend/
├── package.json               scripts: build, lint, format, typecheck, test, gen:api
├── package-lock.json          npm; CI installs with `npm ci`
├── vite.config.ts             build to dist/; vitest config
├── tsconfig.json              project references → tsconfig.app.json (strict, alias @/ → src/) and tsconfig.node.json
├── tailwind.config.ts, postcss.config.js, components.json (shadcn)
├── eslint.config.js           ESLint 9 flat config (typescript-eslint, react-hooks, react-refresh)
├── .prettierrc, .prettierignore
├── index.html
├── public/                    favicon, static assets
└── src/
    ├── main.tsx               providers: QueryClient, Router, I18n, Theme
    ├── app/
    │   ├── router.tsx         routes from architecture 4.2; role guards
    │   └── layout/            AppShell
    ├── api/
    │   ├── client.ts          fetch wrapper: credentials include, problem-details errors, idempotency header helper
    │   └── generated/         openapi-typescript output; regenerated by `npm run gen:api`; drift checked in CI
    ├── features/              one folder per backend module or screen
    │   ├── assessments/       shared by the professor's review and the student's own reading:
    │   │                      types, queries, Trajectory, RatingList
    │   ├── auth/              login, accept-invitation, reset-password
    │   ├── calendar/          the reporting calendar and the weeks it opens; rendered on the
    │   │                      workspaces screen, because a calendar is a workspace setting (REP-01)
    │   ├── overview/          professor overview (UI-01)
    │   ├── me/                student overview, own progress, one released assessment (UI-02, UI-04)
    │   ├── people/            the roll of the workspace being worked in: invite, resend, move,
    │   │                      suspend, restore, remove (AUTH-01, UI-08)
    │   ├── projects/          the project list and the project workspace: create, activate,
    │                          assign a student, end a membership, documents (PROJ-01, UI-03)
    │   ├── students/          research profile (UI-04)
    │   ├── report/            weekly package editor: a tab per required project, EntryForm,
    │   │                      Attachments, AutosaveIndicator
    │   ├── review/            three-pane review workspace (UI-05)
    │   └── workspaces/        the workspaces a professor belongs to or owns, and the header
    │                          switcher: join, leave, create, archive (ADR 0012/14/15/20, UI-08)
    ├── components/
    │   ├── Failure.tsx        the shared error surface
    │   ├── ui/                placeholder
    │   ├── markdown/          placeholder
    │   ├── evidence/          Badges.tsx (Badge, ConfidenceBadge, ProgressIndex)
    │   └── forms/             placeholder
    ├── hooks/                 useAutosave, useTheme. `useScope` and `useIdempotencyKey` were never
    │                          built: scope is resolved server-side and the idempotency header is
    │                          set in api/client.ts
    ├── lib/                   dates (period formatting in workspace timezone), i18n setup, theme, upload (hash, PUT, confirm — shared by report evidence and project documents)
    ├── locales/
    │   └── en/common.json     one language, deliberately: i18n.ts initialises `en` alone, so a
    │                          second is a resource file and a switcher rather than a refactor
    └── test/                  Vitest + Testing Library unit tests, setup.ts, msw handlers
```

Conventions: a `features/<name>/` folder contains `pages/`, `components/`, `queries.ts` (TanStack Query hooks with keys `[feature, scope, ...ids]`), and `types.ts` re-exporting generated types. No feature imports another feature's components; shared pieces move to `components/`. Server state comes only from `queries.ts`; client-only state uses local React state or a small Zustand store inside the feature.

## 5 Infrastructure

```
infra/
├── docker-compose.yml         production: caddy, api, worker, postgres, minio, backup
├── caddy/
│   └── Caddyfile              TLS, serve frontend/dist, reverse_proxy /api/* api:8000, security headers
├── postgres/
│   ├── init/01_extensions.sql  CREATE EXTENSION pg_trgm (no pgvector, ADR 0024)
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
├── gen_api_client.sh          exports openapi.json from the app and runs openapi-typescript
├── check_docs.py             asserts this file against the tree: every path named here exists and
│                          every high-churn path is named, every /api/... route cited in any
│                          document or called by a screen is one the application serves, and
│                          every ADR is in the index. Prose counts and versions are not checked
├── check_traceability.py      asserts every requirement ID in docs/research_management_requirements.md
│                              appears in docs/architecture.md section 16; warns on a standing AC-xx
│                              with no acceptance test
├── preflight.sh               compares infra/.env with .env.example and checks what a key diff cannot see
├── guard_docker_volumes.py    refuses `docker compose down -v` (PreToolUse hook for agents)
├── set-smtp-password.sh       writes the SMTP password into infra/.env
└── restore_drill.sh           spins a scratch stack, restores latest backup, runs smoke checks
```

## 7 Documentation conventions

- **ADRs** in `docs/adr/NNNN-<slug>.md` with Context, Decision, Consequences; never edited after acceptance except to mark them superseded, withdrawn or amended. `docs/adr/README.md` is the index, with each ADR's status, and must list every file — `scripts/check_docs.py` asserts it.
- **Runbooks** are imperative checklists; every runbook names the alert or event that triggers it.
- **Requirement references** in code use the ID in a comment on the function that implements it, for example `# REP-08` above `dispatch_missed_deadline`, so `grep REP-08` finds spec, architecture, code, and tests.

## 8 Branching, commits, and CI

- `main` is deployable; feature branches `feat/<area>-<slug>`, fixes `fix/<slug>`; squash merge with a Conventional Commits title (`feat(reporting): freeze plan baselines at period start`).
- Pull request template asks for: requirement IDs touched, migration present yes/no, docs updated yes/no, screenshots for UI.
- `ci.yml` jobs: `backend-lint` (ruff, mypy, import-linter), `backend-test` (pytest with testcontainers, coverage gate), `migrate-check` (alembic autogenerate produces no diff), `frontend` (eslint, tsc, vitest, build), `client-drift` (regenerate API client and fail on diff), `docs` (`scripts/check_traceability.py` and `scripts/check_docs.py`), `images` (build both images, Trivy scan).
- `release.yml` on tag `v*`: build, push to the registry, generate SBOM, create release notes from commits.
