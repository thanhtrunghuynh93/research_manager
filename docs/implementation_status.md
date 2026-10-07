# Implementation status

Version 0.14 — 7 October 2026 — companion to [research_management_requirements.md](research_management_requirements.md) v0.14, [architecture.md](architecture.md), [repo_layout.md](repo_layout.md) and [use_cases.md](use_cases.md)

What is built, what is deliberately not, and what is still open. How it was built is in git history,
not here. Counts (tests, coverage, migrations, endpoints) are deliberately not recorded: §5 says how
to obtain them, and CI enforces the 85 % coverage gate. Update this file in the pull request that
changes what it describes.

## 1 What is built

Every backend module below is complete, tested and reachable from a screen or a scheduled job;
[use_cases.md](use_cases.md) says which endpoint each screen calls.

| Module | What it does | Requirements |
| --- | --- | --- |
| `core/` | Settings (refuses shipped development defaults when `RM_ENV=prod`), DB session, `Scope` and the `visible_to` registry, audit rows, the procrastinate app, clock, object store, metrics | §9, §11 |
| `identity/` | Invitation-only enrolment, Argon2 passwords, server-side sessions (12 h idle, 30 d absolute), password recovery, workspaces (ownership, plural professor membership, join/leave/archive), moving a student who has written nothing, break-glass CLI | AUTH-01..07, UI-08 |
| `projects/` | Projects with stages and statuses, membership history (assigned, created-with, joined), joining open projects, project documents, plan baselines frozen at period start | PROJ-01, 02, 04, 07 |
| `reporting/` | Versioned reporting calendar, periods, obligations derived from memberships, exemptions and extensions, one weekly package per student with an entry per project, autosaved drafts, idempotent submission, immutable versions, revision requests, attachments (presigned upload, verified checksum, extraction at submission) | REP-01..06 |
| `evidence/` | The access-labelled evidence index: report entries and attachments chunked on `ReportSubmitted` / `ArtifactExtracted`, dropped on `ArtifactRemoved`; window and by-source reads for the assessment snapshot. No search, no embeddings, no provider calls | AUTH-02 |
| `assessment/` | Snapshot through the student's own view, claim extraction and matching, rubric rating, citation validation, deterministic metrics (`metrics.py`), drafts, approve/override/withdraw, trends grouped by rubric version, stage applicability from the rubric version, retry, AI spend and budgets (`ops.py`) | ASSESS-01..10, PROJ-05 |
| `ai/` | The only module that reaches OpenAI: prompt registry (`extract_claims`, `match_claims`, `rate_rubric`), untrusted-content framing, redaction, strict-schema check, cost ledger (`ai_calls`), budgets, the deterministic `FakeGateway` | ASSESS-09, §11 |
| `overview/` | The professor's week: next deadline, outstanding reports with an as-of instant, the week's board, review queue, stalled analyses — plain SQL-backed functions | UI-01, REP-08, AC-15 |
| `notifications/` | Missed-deadline email at 00:00 local on the meeting day (state read at send time, keyed so a retry is a no-op), invitation and reset emails, queued delivery with retries, mail health on the overview | REP-08, UI-07 |
| `api/v1/` | One router per area; `/api/healthz`, `/api/readyz` (database, object store, worker, SMTP), `/api/metrics` | §10, §11 |
| Frontend | Sign-in, invitation and reset pages; student week, report editor and reader, own progress and released assessments; professor overview, people, workspaces (with the calendar), student profile, review; project list and project page for both roles | UI-01..05, UI-08 |
| Operations | Single-host Compose stack (Caddy, api, worker, Postgres 16, MinIO, backup), encrypted nightly backups, restore drill, `scripts/preflight.sh`, demo seed and missed-deadline drill | §11, AC-16 |

Periodic tasks (architecture §12): `ensure_periods`, `freeze_baselines`, `scan_due_reminders`
(the missed-deadline dispatch), `send_queued_emails`, `queue_health`, `retention_sweep` (deletes
queue jobs finished more than seven days ago).

All acceptance scenarios that stand have tests (AC-01..19 less the withdrawn AC-04, AC-06, AC-09);
`scripts/check_traceability.py` lists any that do not. AC-16 runs a real `pg_dump`/`pg_restore`
cycle; the wall-clock recovery time is measured by `scripts/restore_drill.sh` on real infrastructure.

## 2 Withdrawn — built or specified, then removed

Each was removed with its code and tables; the requirement rows keep their *Was:* text and the ADRs
keep the reasoning.

| Feature | Requirement rows | Decision | Migration |
| --- | --- | --- | --- |
| Exports and the in-app notification screen | UI-06, UI-07 (0.4) | use cases v0.4 | — |
| Milestones and project progress | PROJ-06, PROJ-03 (0.8) | requirements 0.8 | 0026 |
| Tasks, dated research decisions, pre-deadline reminder offsets, student correction requests, the baseline proposal flow | PROJ-03, PROJ-04, REP-07, ASSESS-08, UI-03 (0.10) | requirements 0.10, [ADR 0021](adr/0021-the-read-set-is-one-workspace.md) (one-workspace `Scope`) | 0027 |
| GitHub repository connector (sync, webhook, identities, attribution) | REPO-01..08, AC-04, AC-06, AC-09 (0.11) | [ADR 0022](adr/0022-no-repository-connector.md) | 0028 |
| Professor research assistant, supervision notes, answer cache, access epoch | QA-01..07 (0.12) | [ADR 0023](adr/0023-no-research-assistant.md) | 0029 |
| Embeddings, pgvector, the full-text column | §10 (0.13) | [ADR 0024](adr/0024-no-embeddings.md) | 0030 |

Residue kept on purpose: `plan_baseline_items.task_id` (no FK), the `proposed`/`accepted`/
`superseded` baseline states, `evidence_source_kind` values `repository_event`, `decision` and
`feedback`, `evidence_snapshots.integration_lag_days` (always 0) and
`evidence_snapshot_items.integration_of_earlier_work` (always false) — each has historical rows or
enum users. A project's repository is the plain link `projects.repo_url`, which nothing reads.

## 3 Known gaps

| Gap | Requirement | Why |
| --- | --- | --- |
| OCR for scanned documents | REP-04 | Later work by the specification. A scanned PDF is recorded as "no text layer", not as a failure |
| Markdown or rich-text editing, equation rendering | REP-04, §11 Usability | The editor is plain textareas per entry field; content is stored as written |
| Overview filters by student, project, stage and week | UI-01 | The overview is the current week of the workspace being worked in |
| Source freshness on the review screen | UI-05 | The freshness badges were the connector's (ADR 0022); the review screen shows claims, evidence and the draft. Revision requests are made on the report reader, not the review screen |
| Professor-authored feedback beyond the released assessment and revision requests | REP-07 | No code path writes one |
| Withdrawing a published assessment, excusing or extending an obligation, attachment version history, editing one's own profile, reading/setting AI budgets | ASSESS-08, REP-06, REP-04, AUTH-01, §11 Cost control | The endpoints work; no screen calls them (⚙️ rows in use_cases.md) |
| Moving a student who has written history | AUTH-06 | Refused by the two history foreign keys, by design. The ways out — cascade the history or make the move a new account — both change what "the workspace a record was written in" means |
| Retention and authorized deletion of research records | §11 Data control | `retention_sweep` purges only finished queue jobs; the schedule for reports, assessments and artifacts is the professor's to set |
| Row-Level Security | §11 | ADR 0004: application-level authorization first, RLS as defence in depth later |
| Rubric calibration | ASSESS-03, §13 | Needs the professor's ratings on real weeks; the harness and [protocol](evaluation/protocol.md) are ready |
| Performance benchmarks | §11 | The p95 targets (2 s interactive, 10 min assessment) have never been measured, and no seed builds the 100k-chunk corpus |
| Upload scanning; single-node MinIO | §11 Security, recovery | Open decisions in [production-readiness.md](runbooks/production-readiness.md) |

## 4 Decisions taken while building

Choices the specification left open, or where following it literally would have been wrong.

| Decision | Reason |
| --- | --- |
| `meeting_date` is derived from the period's end, not its start | The formula as first written placed the deadline the day before the period opened |
| `project_memberships.left_on` is exclusive | With an inclusive end, "remove this student now" left access alive until midnight |
| Membership dates and "today" are the workspace's calendar (`identity.workspace_today`) | Comparing local dates against UTC's made a UTC+7 student lose access to a project for seven hours a day |
| The progress index a reader sees is derived from the ratings that reader is shown; the draft's own is kept as `model_progress_index` | A stored index drifted from an override, publishing 0/100 for an all-unknown assessment |
| `dimensions` in the rubric output is a list, not a map; `ai/schemas/strict.py` checks every schema against the provider's strict mode and `FakeGateway` refuses what the provider would | The map was rejected by the provider on every call while the fake accepted it |
| A spent budget is a distinct run state, not `partial`; spend is read where it is reported | "The money ran out" and "the model failed" need different responses; the budget check only totals spend when a limit exists |
| Model prices live in `ai/cost.py`; an unknown model records a null cost | A guessed price would be believed |
| Email delivery is a queued row drained by a periodic task | Same at-least-once behaviour, with attempts and the last error in one place |
| Token emails bypass `email_deliveries`; their failures are read from the job queue | The queue row would hold a live credential; the overview's mail warning counts both |
| Report entries and attachments are indexed by `evidence` reacting to events | Reporting stays unaware of evidence, as the layer order requires |
| Attachment text is indexed `student_private` | Indexing it project-shared would let a project-mate read through the evidence what they cannot open directly |
| A failed enqueue after submission is logged and swallowed | Report acceptance must not wait on anything downstream; a missing draft is recoverable from the retry button |
| An entry with every field empty is refused | One button press could otherwise discharge every project's obligation with nothing written |
| The submitted report is a separate screen from the editor, and never renders `draft_content` | The editor's tabs come from obligations and cannot show an entry for a project since left; showing drafts would make autosave surveillance |
| Two import contracts are scoped to direct imports | The API reaches models through `service.py` and the gateway through `assessment.service` by design |
| Metric labels never identify a person | Metrics are scraped into a system with different access rules |
| Deadlines render as 23:59 | The requirement states the rule in 24-hour time |
| The evaluation harness reports agreement rather than asserting a threshold | Requirements §13: the threshold is agreed with the professor during the pilot |

## 5 Open decisions owed by the professor

1. **Mail provider** — SMTP relay or a transactional API; the `EmailSender` protocol takes either.
   SPF/DKIM for the sending domain are still to be published.
2. **Model and data-processing terms** — which content may reach OpenAI, and which projects need
   `ai_restricted`.
3. **Rubric calibration** — the default weights and anchors are proposals until the pilot gates in
   requirements §13 are met.
4. **Monthly AI budget** — none is configured, which means no limit. It is set through
   `PUT /api/v1/admin/ai/budgets` (no screen; deploy.md step 7).
5. **VPS region and offsite backup destination** — `RM_OFFSITE_REMOTE` is empty.
6. **Row-Level Security** as defence in depth.
7. **Retention schedule** for reports, assessments and artifacts.

## 6 How to verify the current state

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run lint-imports
uv run pytest --cov=app --cov-fail-under=85

cd ../frontend && npm ci && npm run lint && npm run typecheck && npm test -- --run && npm run build

cd .. && python3 scripts/check_traceability.py && python3 scripts/check_docs.py
bash scripts/gen_api_client.sh && git diff --exit-code -- docs/api frontend/src/api/generated
```

Migrations are verified by applying them to an empty database, running `alembic check`, then
downgrading and re-applying. `tests/jobs/test_defer_seam.py` checks that the API process can
enqueue against a real queue. The worker's task registry, against architecture §12:

```bash
cd backend && uv run python -c "
import importlib
from app.core.jobs import TASK_MODULES, procrastinate_app
for module in TASK_MODULES: importlib.import_module(module)
print(sorted(procrastinate_app.tasks))
print(sorted(d.task.name for d in procrastinate_app.periodic_registry.periodic_tasks.values()))
"
```

The calibration run costs money and is opt-in: `cd backend && RM_EVAL=1 uv run pytest tests/evaluation -m evaluation -s`.
