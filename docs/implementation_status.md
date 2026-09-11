# Implementation status

Version 0.1 — 11 September 2026 — companion to [research_management_requirements.md](research_management_requirements.md) v0.3, [architecture.md](architecture.md), and [repo_layout.md](repo_layout.md)

This document records what has been built, what remains, and the decisions taken while building
that are not obvious from the code. It follows the bootstrap order in section 9 of the repository
layout. Update it in the pull request that changes what it describes.

## 1 Where the project stands

| Step | Scope | State |
| --- | --- | --- |
| 1 | Repository skeleton, `core/`, health endpoints, dev Compose, CI | Done |
| 2 | `identity/`: users, invitations, sessions, authz, break-glass | Done |
| 3 | `projects/` and `reporting/`: periods, obligations, drafts, submission, versions, plan baselines; student frontend | Done except artifacts |
| 4 | `notifications/`: scheduler tasks, missed-deadline email, in-app messages | Done except the Playwright e2e |
| 5 | `evidence/`: connectors, identity mapping, indexing and retrieval | Done |
| 6 | `assessment/`: snapshot, metrics, pipeline, review | Done |
| 7 | `ai/` against OpenAI, cost ledger, evaluation harness | Seam built, provider not |
| 8 | `assistant/`, exports, professor overview, backup drill, release | Not started |

At the time of writing: 376 backend tests, 14 frontend tests, 92.6 % backend coverage, ten
migrations, and all five import-linter contracts holding.

## 2 What each finished step delivers

### Step 2 — `identity/` (AUTH-01..03)

Invitation-based enrollment with single-use tokens stored only as digests; Argon2 passwords;
server-side sessions with a 12-hour idle and 30-day absolute expiry; password recovery; and the
audited break-glass procedure the runbook describes, reachable only from a host shell.

One predicate decides every read of a user record, and search, downloads and exports compile the
same one — there is no second permission model. Deactivation, role change, and password reset each
revoke every session and advance `workspaces.access_epoch` in the same transaction, which is what
later lets a cached answer be refused.

`app.cli identity bootstrap` creates the workspace and its professor; without it there was no way
to get a first account, and the deploy runbook now names it.

### Step 3 — `projects/` and `reporting/` (PROJ-01..06, REP-01..06)

Projects with research questions, stages and statuses; membership history that is never deleted;
milestones whose baselines are retained as immutable revisions when scope or weight changes; tasks
whose partial completion must carry a reason; dated research decisions.

The reporting calendar generates periods, derives obligations from membership dates and project
status, and records exemptions and extensions. Drafts autosave. Submission writes an immutable
version with one entry per required project, and a repeated submission carrying the same
idempotency key returns the version already written.

Plan baselines freeze at period start from the previous report's next-week plan, or record an empty
baseline when there is nothing to freeze; a student may then propose a first plan, which becomes a
commitment only once the professor accepts it.

The frontend covers sign-in, the student overview, and the weekly editor with a tab per required
project, autosave, and an idempotent submit.

### Step 4 — `notifications/` (REP-07, REP-08, UI-07)

The missed-deadline job reads obligations at the moment it sends, so a submission at 23:59 receives
nothing. Every write is keyed, so a retried job sends no duplicate. The professor sees the
outstanding list in-app at the same time and receives no email. In-app notifications carry
per-recipient visibility and mutable preferences, with the critical categories unmutable.

The procrastinate schema ships as a migration, so a deploy still runs only `alembic upgrade head`.

### Step 5 — `evidence/` (REPO-01..08)

A read-only connector protocol with two implementations: an in-memory one that the tests, the demo
seed and the end-to-end stack run against, and the GitHub App connector, which mints an installation
token per run and never persists it.

Sync normalises commits, pull requests, reviews, issues and check runs into events that keep author,
commit, merge and ingestion time apart. A run ends completed, partial, or failed, so a rate limit
keeps its progress and a revoked credential is reported rather than read as an absence of work.

Attribution is deliberately narrow: only a verified login or an explicitly confirmed alias
attributes anything; a merger is recorded as a merger; co-authors are joint and the project counts
the artifact once; bots are labelled; and a repository serving several projects leaves unmatched
paths unresolved.

The index stores citable references with their access label and chunks that carry it too, so the
permission predicate sits inside each ranking arm and a chunk outside the caller's scope is never
scored.

### Step 6 — `assessment/` (ASSESS-01..10)

The arithmetic is pure and replayable: the specification's worked example runs end to end, an
unknown withholds the index rather than scoring zero, a not-applicable dimension renormalises the
rest, and a missing baseline leaves commitment completion unavailable.

Snapshots are built through the student's own view of the evidence, so an assessment later
published to them cites only what they can open, and a supervision note can never reach one. A
citation that is not in the snapshot is dropped and the rating that rested on it is downgraded to
`unknown`. A failed model step leaves the run partial and retryable; a restricted project reaches
no provider at all.

Drafts are the professor's to approve. An override requires a recorded reason and keeps the model's
own output beside it; a revision creates a new version while the approved one still stands.

## 3 What is deliberately not built yet

| Gap | Requirement | Why it waits |
| --- | --- | --- |
| File attachments and extraction | REP-04 | Needs MinIO presigned uploads plus worker-side extraction; belongs with the artifact pipeline rather than bolted onto submission |
| Playwright end-to-end for the missed-deadline email | repo_layout §9 step 4 | The service-level proof exists (`tests/acceptance/test_ac_19.py`); the browser-level one needs the full Compose stack in CI |
| OpenAI gateway, cost ledger, budgets | ASSESS-09, §11 | The seam and the fake are built; the provider needs the data-boundary decisions in requirements §14 first |
| Professor overview, review workspace, project and student screens | UI-01, UI-03, UI-04, UI-05 | Backend endpoints exist; the screens are step 8 |
| Professor assistant | QA-01..07 | Step 8, on top of the same retrieval and the same predicate |
| Exports | UI-06 | Step 8 |
| Backup restore drill, release workflow | AC-16 | Step 8; the scripts exist and have not been exercised |
| Second repository provider, experiment trackers | §12 next release | Out of MVP scope by the specification |

### Acceptance scenarios

Proved: AC-01, AC-02, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-13, AC-14, AC-17, AC-18, AC-19.

Not yet: AC-03 (partly proved in the module tests; the full scenario needs the review screen),
AC-10 and AC-15 (the assistant), AC-11 (the answer cache), AC-12 (adversarial fixtures in the
evaluation set), AC-16 (the restore drill). `scripts/check_traceability.py` prints the current list
on every CI run.

## 4 Decisions taken while building

These are choices the specification left open, or places where following it literally would have
produced something wrong. Each is reflected in the code and in the document it contradicts.

| Decision | Reason |
| --- | --- |
| `meeting_date` is derived from the period's end, not its start (architecture §7.1 corrected) | The formula as written placed the deadline the day before the period opened. The meeting follows the week it discusses |
| `project_memberships.left_on` is exclusive | With an inclusive end, "remove this student now" left their access alive until midnight |
| Embeddings come from a registered `Embedder`, not a direct gateway call | repo_layout §3.1 said otherwise, but §3.3 forbids `evidence` importing `ai`, and a restricted project must be able to index without a provider |
| `repository_events` and `plan_baselines` carry targeted guards rather than the blanket immutability trigger | REPO-06 must record that a force push removed an object upstream, and a proposed baseline must be acceptable; the guards allow exactly those transitions and nothing else |
| Email delivery is a queued row drained by a periodic task, not one job per message | Same at-least-once behaviour, with the attempt count and last error in one place |
| Two import contracts scoped to direct imports | The API reaches models through `service.py` and the gateway through `assessment.service`; that is the intended arrangement, and the contracts now forbid what they meant to forbid |
| Full-text search uses the `simple` configuration | Reports are written in English and Vietnamese; English stemming distorts the latter. Revisit with the retrieval benchmark |
| Report entries are indexed by `evidence` reacting to a `ReportSubmitted` event | Reporting stays unaware of evidence, which is the layer direction the architecture sets |
| Deadlines render as 23:59 rather than 11:59 PM | The requirement states the rule in 24-hour time, and the workspace's timezone convention matches |

## 5 Open decisions still owed by the professor

Carried from requirements §14 and architecture §17, narrowed to what is still open:

1. **Mail provider** — SMTP relay or a transactional API. The `EmailSender` protocol takes either;
   the dev stack uses mailpit.
2. **Model and data-processing terms** — which content may reach OpenAI, and which projects need
   `ai_restricted`. Step 7 cannot be finished honestly without this.
3. **Rubric calibration** — the default weights and anchors are the specification's proposals. The
   pilot gates in §13 are the point at which they become real.
4. **VPS region and offsite backup destination**.
5. **Whether to add Row-Level Security** as defence in depth after the MVP.
6. **Chunking parameters and embedding model**, to be fixed by the retrieval benchmark.

The first repository provider is settled: GitHub, as ADR 0005 assumed.

## 6 How to verify the current state

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run lint-imports
uv run pytest --cov=app --cov-fail-under=85

cd ../frontend && npm ci && npm run lint && npm run typecheck && npm test -- --run && npm run build

cd .. && python3 scripts/check_traceability.py
bash scripts/gen_api_client.sh && git diff --exit-code -- docs/api frontend/src/api/generated
```

Migrations are verified by applying them to an empty database, running `alembic check` for drift,
then downgrading and re-applying. The worker is verified by running it against a real queue: that
is how the missing engine initialisation in step 4 was found.
