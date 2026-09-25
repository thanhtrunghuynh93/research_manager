# Implementation status

Version 0.9 — 21 September 2026 — companion to [research_management_requirements.md](research_management_requirements.md) v0.9, [architecture.md](architecture.md), [repo_layout.md](repo_layout.md), and [use_cases.md](use_cases.md) v0.17

This document records what has been built, what remains, and the decisions taken while building
that are not obvious from the code. It follows the bootstrap order in section 9 of the repository
layout. Update it in the pull request that changes what it describes.

## 1 Where the project stands

| Step | Scope | State |
| --- | --- | --- |
| 1 | Repository skeleton, `core/`, health endpoints, dev Compose, CI | Done |
| 2 | `identity/`: users, invitations, sessions, authz, break-glass | Done |
| 3 | `projects/` and `reporting/`: periods, obligations, drafts, submission, versions, plan baselines, artifacts; student frontend | Done |
| 4 | `notifications/`: scheduler tasks, missed-deadline email, notification records | Done |
| 5 | `evidence/`: connectors, identity mapping, indexing and retrieval | Done |
| 6 | `assessment/`: snapshot, metrics, pipeline, review | Done |
| 7 | `ai/` against OpenAI, cost ledger, evaluation harness | Done |
| 8 | `assistant/`, professor overview, backup drill, release | Done |
| 9 | The seams: assessment triggering, the periodic tasks, the repository API | Done |
| 10 | A full review of the branch, and the defects it found | Done |
| 11 | Deployment preparation: readiness checks, production config refusal, auth rate limits, mail warnings | Done |
| 12 | `workspaces/`: ownership, joining and leaving, plural membership, reads that span it | Done |

Counted from the tree rather than remembered, and checked by `scripts/check_docs.py`:

| Counted | Value |
| --- | --- |
| Alembic migrations | 26 |
| `/api/v1` endpoints | 91 (89 in the schema, 2 `include_in_schema=False`) |
| ADRs | 20 |
| Acceptance scenarios with a test | 19 of 19 |
| Import-linter contracts holding | 5 of 5 |

Test counts and coverage are deliberately not recorded here. A number in prose goes stale the week
after it is written — the previous version of this section claimed 794 backend tests and 91.3 %
coverage, and both had drifted by the time anyone read them. Section 6 says how to obtain the
current figures, and CI enforces the 85 % gate rather than a sentence.

**21 September 2026 — the project screen, and three rules that had drifted from their documents.**
Four changes went out together, and the shape worth recording is that two of them were the
*documents* being wrong rather than the code.

Switching workspaces moved from `/workspaces` into the header, where every screen can reach it.
The project screen lost milestone completion and dated decisions — both computed, both shown, and
neither writable by any screen, so completion read 0% for every project as though that were a
finding; milestones were withdrawn outright the same day (requirements 0.8, migration 0026) — and
gained related documents, which is PROJ-01's "shared resources" built at last
([ADR 0018](adr/0018-project-documents-are-shared-with-the-project.md)). Ending a membership
became the professor's ([ADR 0019](adr/0019-ending-a-membership-is-the-professors.md)).

The rule that had drifted: `memberships_active_in_range` required an `ACTIVE` project to *derive*
an obligation, and `memberships_open_through`, which judges obligations already derived, tested
only `left_on`. A professor completed a project and the student still owed a report for it that
week — and was emailed at 00:00 on the meeting day. One query, three readers. The docstring beside
it already claimed the two agreed, which is the failure mode this document keeps recording: the
comment was the specification, and nothing checked it against the query underneath.

Requirements went to v0.7 in the same pass, amending AUTH-01, PROJ-07, REP-06, UI-03, PROJ-01,
PROJ-06 and section 9 to describe what is built. Before it, four documents said a student could
leave a project, one said the project workspace showed decisions, and one called an artifact a
file *or URL* two releases after links were withdrawn.

**15 September 2026 — first deployment preparation.** §1 and §2 of
[production-readiness.md](runbooks/production-readiness.md) are closed bar mail deliverability.
Two of those findings turned out to be understated in the same way, and the shape is the one this
document keeps recording: *the fix as prescribed would not have worked*. `RM_ACME_EMAIL` was
missing from `.env.example`, and also from the caddy service, which has no `env_file` — so setting
it correctly would still have changed nothing. Failed token emails were said to miss the mail
warning on the professor's overview; there was no mail warning, and `failed_deliveries()` had no
callers at all. A dead worker or a wrong SMTP credential is now a `readyz` failure rather than a
deployment that answers `ready` and enrols nobody, and `RM_ENV=prod` refuses to start on any
shipped development default instead of trusting an operator to read a checklist.

**Version 0.2 of this document claimed the MVP was complete. It was not**, and the error is worth
recording because of its shape: every module was built and tested, and three of the seams between
them were missing, which no module-level test could see.

- Nothing subscribed to `ReportSubmitted` on behalf of `assessment`, so a submitted report indexed
  itself and notified the professor and never produced a draft. The review queue stayed empty until
  somebody asked for each assessment by hand.
- Four of the six periodic tasks in architecture §12 did not exist, so the reporting calendar and
  the plan baselines only advanced when a person POSTed for them.
- `evidence` was complete and unreachable: every service existed and no route did, so a repository
  could not be connected through the product at all.

All three are now built (§2, step 9). The lesson for the next reviewer of this document: a step
marked Done means its module is done, and the question worth asking separately is what calls it.

**Version 0.3 was then reviewed line by line, and the same shape appeared again.** A fourth seam
was missing — the API process never opened the job queue, so every `defer_async` raised
`AppNotOpen` and a submitted report still produced no draft, exactly the symptom §9 was meant to
have cured. The review found more than fifty further defects, and what they had in common is
worth recording as plainly as the seams were:

- **A test that stubs the seam proves the module, not the product.** The assessment trigger test
  monkeypatched `defer_pipeline`, the seed called `run_pipeline` directly, and the webhook test
  signed its payload with the test double's own published secret — so three separate defects in
  the same path were invisible while the suite was green.
- **Docstrings asserted invariants the code did not hold.** `core/jobs.py` said jobs were enqueued
  in the caller's transaction; `useAutosave` said it flushed on unmount; `links.py` said the fetch
  was bounded in three directions; `embeddings.py` said a restricted project skipped the provider;
  the exports bundle called itself complete. Each was a decision written down and then not
  implemented, and each read as documentation of working behaviour.
- **Wrong numbers look like numbers.** Commitment completion was computed with every fraction
  hardcoded to zero; coverage took its denominator from whatever the model returned; the snapshot
  carried a fortnight of already-assessed evidence. None of these fails — they produce a plausible
  figure, which is the worst available outcome for an assessment system.

All are fixed, each with a test that fails without the fix. What remains before a pilot
is still calibration and operation rather than construction: the rubric has to be rated against
real work, and the professor still owes the decisions in §5.

**Version 0.6 found the first shape again, from the outside.** QA of the professor role on the
deployment found that `rate_rubric` had failed on *every* call for as long as a real key had been
configured — 13 of 13 runs, no assessment ever produced from model output, every one on screen
still the seed's. `RubricOutput.dimensions` was `dict[str, DimensionRating]`, and the provider's
strict mode cannot express an object whose keys are not known in advance, so each request came
back 400. It is the same lesson as the fourth seam with one turn added, worth recording because
the obvious guard would not have caught it either:

- **The SDK's own strict converter accepts a schema the server rejects.**
  `_ensure_strict_json_schema` fills in `additionalProperties: false` only where the key is
  *absent*; a `dict[str, X]` emits the key already holding a `$ref`, so the converter walks past
  it and `to_strict_json_schema(RubricOutput)` succeeds. A check written the obvious way — hand
  the model to the SDK, assert it does not raise — agrees with the bug. The rules have to be
  reimplemented against the *server's* contract, which is what `app/ai/schemas/strict.py` does.
- **The fake was the reason nobody noticed.** It never built a JSON schema, so the entire suite
  ran through the defect. It now refuses any schema the provider would refuse, which makes every
  pipeline, acceptance and evaluation test that touches `rate_rubric` a guard against this class.
- **The failure was recorded as a class name.** The gateway stored `type(error).__name__` and
  nothing else, so thirteen identical `BadRequestError` rows sat on the professor's overview with
  nothing to act on and the cause had to be reconstructed from the schema rather than read.

## 2 What each finished step delivers

### Step 2 — `identity/` (AUTH-01..03)

Invitation-based enrollment with single-use tokens stored only as digests; Argon2 passwords;
server-side sessions with a 12-hour idle and 30-day absolute expiry; password recovery; and the
audited break-glass procedure the runbook describes, reachable only from a host shell.

One predicate decides every read of a user record, and search and downloads compile the same one —
there is no second permission model. Deactivation, role change, and password reset each
revoke every session and advance `workspaces.access_epoch` in the same transaction, which is what
later lets a cached answer be refused.

`app.cli identity bootstrap` creates the workspace and its professor; without it there was no way
to get a first account, and the deploy runbook now names it.

### Step 3 — `projects/` and `reporting/` (PROJ-01..05, PROJ-07, REP-01..06)

Projects with research questions, stages and statuses; membership history that is never deleted;
tasks whose partial completion must carry a reason; dated research decisions. Milestones were here
too, and are not: nothing ever created one, so migration 0026 removed them (requirements 0.8).

The reporting calendar generates periods, derives obligations from membership dates and project
status, and records exemptions and extensions. Drafts autosave. Submission writes an immutable
version with one entry per required project, and a repeated submission carrying the same
idempotency key returns the version already written.

Plan baselines freeze at period start from the previous report's next-week plan, or record an empty
baseline when there is nothing to freeze; a student may then propose a first plan, which becomes a
commitment only once the professor accepts it.

Attachments (REP-04) upload straight to object storage: the API validates the size, issues a
presigned PUT, and then verifies what arrived against the checksum the client declared. Extraction
records three outcomes rather than two, because a file we could not read and a file with no text to
read lead to opposite conclusions about the week. Links are fetched only after the resolved address
is checked, and every redirect is checked again.

The frontend covers sign-in, the student overview, and the weekly editor with a tab per required
project, autosave, attachments, and an idempotent submit.

### Step 4 — `notifications/` (REP-07, REP-08, UI-07)

The missed-deadline job reads obligations at the moment it sends, so a submission at 23:59 receives
nothing. Every write is keyed, so a retried job sends no duplicate. The professor sees the
outstanding list in-app at the same time and receives no email — on the overview, since use cases
v0.4 retired the notifications screen. Notification records carry per-recipient visibility. They
carry no preferences: muting went with the screen, and the table went with it, because an
unclearable mute is worse than none.

The procrastinate schema ships as a migration, so a deploy still runs only `alembic upgrade head`.

`app.cli notifications dispatch-missed-deadline` runs the dispatch again after a mail
misconfiguration is fixed; it is safe to repeat because the notification key and the delivery row
make a repeat a no-op.

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

### Step 7 — `ai/` (ASSESS-09, requirements §11, §13)

`gateway.py` is the only module that imports the OpenAI SDK. A prompt file splits at its first
labelled section: the instructions stay above, and every piece of student text, diff or README is
rendered into the untrusted block below them. Placeholders are filled by plain substitution rather
than a template engine, because a real engine would hand that text an expression language to sit
in. No tool is offered to the model in any call, so there is nothing for an injected instruction to
reach even if one is followed.

Inputs are redacted before they are serialised; what was removed is recorded as a rule name, never
as the value. Retries cover only errors that could plausibly clear. Every outcome — completed,
refused, failed, delayed by budget — writes an `ai_calls` row in the caller's transaction, and a
model with no published rate records its tokens and leaves the cost null rather than guessing.

A spent budget is its own run state. A run that produced no draft has three possible causes and the
professor needs to tell them apart: the money ran out, the model failed, or nothing changed.

The evaluation set in [`docs/evaluation/`](evaluation/) holds ten seed cases covering the categories
requirements §13 names. The harness keeps two questions apart: contract properties are pass/fail and
run on every CI pass against the deterministic gateway; agreement with the professor needs the real
provider and is reported rather than asserted, because a threshold invented before anyone has seen
real disagreement is a number to hit rather than a decision to make.

### Step 8 — `assistant/`, overview, operations (QA-01..07, UI-01)

The assistant runs one flow in a fixed order, because the order is the safety property: route,
resolve entities against the database, compute facts, retrieve, re-check, generate, validate
citations, cache.

A fact question never reaches the generation step. The obligations table says how many reports are
missing and that number is rendered, not written — the AC-15 tests script the fake gateway to
answer "seven" so that passing proves it was not consulted. Citations are checked against what was
actually retrieved; an invented one is dropped and the drop is stated.

Confidentiality is structural rather than instructed: supervision notes live in a table nothing
indexes and are read through a function the student branch never calls. The answer cache is keyed by
the asker as well as the question and dies with the access epoch it was written under.

The professor overview is built from the same fact functions the assistant uses, so the number on
the dashboard and the number in an answer cannot disagree.

The demo dataset (`app.cli seed demo`) and the missed-deadline drill (`seed missed-deadline-drill`)
give the Playwright suite something to act on; the e2e specs read mailpit to prove REP-08 end to
end, which the service tests cannot.

### Step 9 — the seams (architecture §9.1, §12; REPO-01..05)

`assessment/events.py` subscribes to `ReportSubmitted` and enqueues one pipeline job per entry
whose content moved — two projects in one package give two assessments (AC-01), an entry carried
forward unchanged gives none (AC-17). The queueing lock is the job key, so a redelivered event and
a manual retry are the same job. An enqueue that fails is logged and swallowed: the submitted
version is the thing that cannot be lost, and a missing draft is recoverable from the retry
endpoint (requirements §10, AC-13).

Eight periodic tasks now run: `ensure_periods` and `freeze_baselines` daily, `scan_due_reminders`
and `send_queued_emails` on their short cycles, `dispatch_due_reminders` every fifteen minutes,
`incremental_sync` every thirty, `queue_health` every five, and `retention_sweep` nightly. The two
calendar tasks are idempotent by construction, so a worker that was down for a day catches up
rather than skipping a week.

The repository routes close REPO-01 through REPO-05 as a *product* rather than a module: connect,
link to a project, map a developer identity, resync, search the evidence index, and the signed
GitHub webhook — which also enqueues the targeted run architecture §8.3 describes and reports
whether the delivery matched anything, because one landing nowhere looks identical to one working.

`/api/metrics` serves the series requirements §11 names. The assistant gained the SSE stream its
client helper was already written against.

### Step 12 — `workspaces/` (AUTH-04..06, UI-08)

A workspace was always the tenant boundary; what was missing was any relation saying which of them
a professor may administer, and then — once there were several — which they may be in.

- **Ownership is the administration relation** (ADR 0012, amending ADR 0011). `workspaces.owner_id`
  already existed as the break-glass contact; making it load-bearing meant nothing else had to
  change. It decides create, rename and archive.
- **Belonging is separate, and plural** (ADR 0015, migration 0021). `workspace_members` records it;
  `users.workspace_id` keeps its other job as the anchor every composite foreign key points at.
  Three checks moved onto membership as a result: archiving counts memberships, the roll is keyed by
  membership, and leaving your only membership is refused.
- **Reads span the set, writes land in one** (ADR 0016). `Scope` gained `workspace_ids`, and the
  comparison moved into `Scope.within(column)` so that all thirty-three predicates widened in one
  diff rather than thirty-three. The `across_workspaces` flag that a narrower design needed went
  with it — a second, wider variant of a narrow predicate is the shape a permission bug grows in.
- **The session was the wrong place for it.** ADR 0013 put the active workspace on the session and
  migration 0019 added the column; ADR 0014 superseded it two migrations later and 0020 dropped it.
  Paying the schema cost instead — `ON UPDATE CASCADE` on the four identity foreign keys — removed
  the second source of truth rather than adding a re-check on every request to keep it honest.
- **What the schema refuses, it refuses in the database.** The four history foreign keys do not
  cascade, so `move_student` catches an `IntegrityError` inside a savepoint and explains it rather
  than duplicating the constraint in Python where it could drift (AUTH-06).

The review of this work found three defects worth recording, because they share a shape: each was a
place where the *old* singular assumption survived the widening. `join_workspace` still gated on
ownership, so a colleague could not enter a workspace the screen offered them; `reactivate_user`
did not restore the membership `remove_student` deletes, so a restored account was active and
invisible to every membership-keyed read; and the answer cache was still validated against the
anchor's `access_epoch` alone, which ADR 0016's last bullet had predicted in writing. The third
needed migration 0022 and is now keyed to the whole read-set.

**A live functional test of the deployed system found six more, and they share a shape too:** each
was a place where two parts of the product answered the same question on different terms.

- **A stored number and the ratings it came from drifted apart (ASSESS-04).** The progress index
  was computed once from the model's ratings and written down. Overriding every dimension to
  Unknown therefore published the 0/100 those ratings had produced — the one reading the
  requirements forbid, on the professor's page, on the student's released assessment and as a
  point in the trajectory. The index a reader sees is now derived from the ratings that reader is
  shown, against the rubric that produced them; the draft's own index stays beside it as
  `model_progress_index`.
- **Membership was written on one calendar and read on another (PROJ-02, AUTH-03).** `joined_on`
  and `left_on` are plain dates in the workspace's timezone; the access check compared them
  against UTC's. For the seven hours a UTC+7 workspace is a day ahead, a student assigned to a
  project saw it, owed its weekly entry, and could not attach a file to it — "not a member of this
  project". `identity.workspace_today` is now the one answer to what day it is, and the milestone
  overdue count and a removal's leave date were reading UTC too.
- **Citations pointed at routes their readers cannot open (QA-03).** Every fact emitted the
  student's report route, so a professor following a source was redirected to the overview with an
  access warning — which reads as the record being missing rather than the link being wrong. The
  locators are role-aware, and a week now cites one report per student rather than one place for
  all of them.
- **A read that spans workspaces described one (ADR 0016).** The calendar panel listed every
  period the professor could see, so a new workspace reported another's nine open weeks in the
  same breath as saying it had no calendar. Listing periods is scoped to the workspace being
  worked in; the screens that legitimately name a record from any of them ask for the wide list
  by name.
- **A cache was refreshed for half of what depends on it.** Submission invalidated the report and
  not the obligations, and whether a project still owes an entry is read from the obligations — so
  the editor confirmed version 2 over "1 project still has no entry in it", and navigating away
  and back fixed it.
- **A request was shown everywhere except where it is acted on (REP-05).** A revision request
  reached the student's home screen and the read-only reader, and not the editor, which is the one
  screen where the correction is made. It is now carried into the tab it is about, and that tab is
  the one the editor opens on.

## 3 What is deliberately not built

| Gap | Requirement | Why |
| --- | --- | --- |
| OCR for scanned documents | REP-04 | Explicitly later work in the specification. A scanned PDF is recorded as "no text layer", not as an extraction failure |
| Second repository provider, experiment trackers | §12 next release | Out of MVP scope by the specification |
| Row-Level Security | §11 | ADR 0004: application-level authorization first, RLS as defence in depth after the MVP |
| Student-side assistant | §2, §12 | Next release; the retrieval path and the predicate are already shared, so it is a surface rather than a rebuild |
| Rubric calibration | ASSESS-03, §13 | Needs the professor's own ratings on real weeks. The harness and the protocol are ready for them |
| Retention and authorized deletion | §11 "Data control" | `retention_sweep` expires the answer cache, which has a defined lifetime. Retention for reports, assessments and artifacts waits on the professor's policy: the deletion is irreversible and the schedule is theirs to set, not mine to invent |
| Moving a student who has written history | AUTH-06 | Four composite foreign keys refuse it, by design rather than by omission. The two ways out — cascade the history into the new workspace, or make the move a new account — both change what "the workspace a record was written in" means, and neither is worth doing before someone needs it (use_cases.md §2.1) |
| Pre-deadline reminders reaching anyone | REP-07 | The rows are written every fifteen minutes and nothing reads them: use cases v0.4 withdrew the in-app surface and only `missed_deadline` is emailed. The offsets endpoint has no screen either. Kept rather than deleted because the unique key is what makes a retried dispatch a no-op |
| Professor-authored feedback | REP-07 | `FeedbackKind.PROFESSOR_COMMENT` exists in the enum and no code path writes one. What a student can read today is the approved assessment, their own correction thread, and — since v0.13 — the reason attached to a revision request, which is the one thing a professor can now write that reaches them |
| Performance benchmarks | §11, §15 | `scripts/bench/` is empty. The p95 targets — 2 s interactive, 10 s first token, 10 min assessment — have never been measured against the 100k-chunk corpus the seed script can build |

### Acceptance scenarios

All nineteen have tests: AC-01 through AC-19. `scripts/check_traceability.py` asserts it on every
CI run and prints the list.

AC-16 runs a real `pg_dump` and `pg_restore` cycle and reads the restored database back through the
ordinary services. It claims what a test can claim — that the records, the permission boundary and
the immutability triggers survive — and not the wall-clock recovery time, which
`scripts/restore_drill.sh` measures on real infrastructure.

## 4 Decisions taken while building

These are choices the specification left open, or places where following it literally would have
produced something wrong. Each is reflected in the code and in the document it contradicts.

| Decision | Reason |
| --- | --- |
| `meeting_date` is derived from the period's end, not its start (architecture §7.1 corrected) | The formula as written placed the deadline the day before the period opened. The meeting follows the week it discusses |
| `project_memberships.left_on` is exclusive | With an inclusive end, "remove this student now" left their access alive until midnight |
| Embeddings come from a registered `Embedder`, not a direct gateway call | repo_layout §3.1 said otherwise, but §3.3 forbids `evidence` importing `ai`, and a restricted project must be able to index without a provider |
| The index tells the embedder who to bill, through `EmbedContext` | Same contract: `evidence` cannot write an `ai_calls` row, but it can say which workspace a batch is for and leave the accounting to whoever makes the vectors |
| `repository_events` and `plan_baselines` carry targeted guards rather than the blanket immutability trigger | REPO-06 must record that a force push removed an object upstream, and a proposed baseline must be acceptable; the guards allow exactly those transitions and nothing else |
| Email delivery is a queued row drained by a periodic task, not one job per message | Same at-least-once behaviour, with the attempt count and the last error in one place |
| Two import contracts scoped to direct imports | The API reaches models through `service.py` and the gateway through `assessment.service`; that is the intended arrangement, and the contracts now forbid what they meant to forbid |
| Full-text search uses the `simple` configuration | Reports are written in English and Vietnamese; English stemming distorts the latter. Revisit with the retrieval benchmark |
| Report entries and attachments are indexed by `evidence` reacting to events | Reporting stays unaware of evidence, which is the layer direction the architecture sets. `ArtifactExtracted` uses the same seam `ReportSubmitted` does |
| Deadlines render as 23:59 rather than 11:59 PM | The requirement states the rule in 24-hour time, and the workspace's timezone convention matches |
| ~~`app.exports` is a bounded context, not just a router~~ — retired in use cases v0.4 | A bundle spanned reporting, projects and assessment; assembling it through those modules' services is what made export authorization identical to interactive access rather than a second implementation of it. The module is gone; the reasoning applies to the next context that spans modules |
| Model prices live in a table in `ai/cost.py`, and an unknown model records a null cost | A guessed price would be believed. The tokens are the fact; the money is arithmetic over a published rate |
| A spent budget is a distinct run state, not a `partial` | The professor's response to "the money ran out" is different from their response to "the model failed", so the record distinguishes them |
| The assistant resolves entity names against records the caller can already see | A model asked about a name will produce a plausible id. Matching against the caller's own visible set means a wrong guess finds nothing rather than reaching a record |
| Relative dates are resolved in Python, not by the router model | "Last month" has an exact answer, and a language model is the wrong instrument for arithmetic on dates |
| Attachment text is indexed `student_private`, matching the artifact record | The artifact is readable by its owner and the professor; indexing its text as project-shared would let a project-mate retrieve through search what they cannot open directly |
| A link is extracted by the server's `Content-Type`, not by the URL's last path segment | `/abs/2401.00001` has no extension worth reading, and the response says what it actually sent |
| A failed enqueue is logged and swallowed, not raised | Requirements §10: report acceptance must not wait on anything downstream. A missing draft is recoverable from the retry endpoint; an unrecorded submission is not recoverable at all |
| The connector factory falls back to the in-memory connector and says so in the log | A misconfigured key should surface as stale evidence on the dashboard, not as a dead worker that stops syncing every repository. Silently syncing nothing is the one outcome that must not happen, because it is indistinguishable from a student who did nothing (AC-04) |
| A webhook for an unknown repository is accepted, recorded, and reported as unmatched | Asking GitHub to retry something that will never match is noise rather than resilience; but a webhook landing nowhere looks identical to one working, so the response says which it was |
| Metric labels may never identify a person | A metric is scraped into a system with different access rules from this one, so a student id in a label would be a disclosure through the monitoring stack |
| `retention_sweep` expires only the answer cache | It is the one record with a defined lifetime. Inventing a deletion schedule for reports and assessments would be irreversible and is the professor's decision (requirements §14) |
| An entry with every field empty is refused, not just an empty package | The check was per package on the reading that judging one entry's substance is the professor's. That reading holds — the test is emptiness, not adequacy — but at package level a blank entry passed whenever a sibling tab had text, and *that project's* obligation was then marked submitted. One press of one button could report every project a student is on with nothing written for any of them. The granularity now matches the thing being discharged |
| The submitted report is a separate screen from the editor, not a mode of it | The editor is seeded mutable state — draft, autosave, idempotent submit — and a professor rendering it would mount autosave against an endpoint that answers 422. The deciding reason is narrower: the editor's tabs come from the obligations, so an entry for a project the student has left can never appear in it, and those entries are in every version. A read-only editor could not have shown them |
| The reader never renders `draft_content`, though the policy would allow it | A professor may read the draft; showing it would make autosave surveillance. An unsubmitted draft is not a submission, and the screen is about the record |
| `spent_usd` is read where it is reported, not taken from the budget check | `check_budget` runs before every model call and totals spend only when there is a limit to compare against, which is right for that path. Reading its figure on the overview meant reporting `$0` in exactly the case where nothing capped the bill |
| The evaluation harness reports agreement rather than asserting a threshold | Requirements §13 says the threshold is agreed with the professor during the pilot. Asserting one now would turn calibration into a test that gets tuned until it passes |

## 5 Open decisions still owed by the professor

Carried from requirements §14 and architecture §17, narrowed to what is still open:

1. **Mail provider** — SMTP relay or a transactional API. The `EmailSender` protocol takes either;
   the dev stack uses mailpit.
2. **Model and data-processing terms** — which content may reach OpenAI, and which projects need
   `ai_restricted`. The gateway, the ledger and the restriction flag are built and wired; what is
   missing is the decision about what may be sent.
3. **Rubric calibration** — the default weights and anchors are the specification's proposals. The
   pilot gates in §13 are the point at which they become real, and
   [`docs/evaluation/protocol.md`](evaluation/protocol.md) is the procedure.
4. **Monthly AI budget** — the panel on `/workspaces` sets one and the figure beside it is the
   month's real spend; none is configured, which means no limit rather than a limit of zero. Until
   v0.13 there was no screen at all, so this decision could only be acted on with curl — and the
   overview reported `$0` spent regardless, because spend was totalled only when a limit existed.
   The decision is still the professor's; what changed is that it can now be taken in the product.
5. **VPS region and offsite backup destination**.
6. **Whether to add Row-Level Security** as defence in depth after the MVP.
7. **Chunking parameters and embedding model**, to be fixed by the retrieval benchmark.

The first repository provider is settled: GitHub, as ADR 0005 assumed.

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

Migrations are verified by applying them to an empty database, running `alembic check` for drift,
then downgrading and re-applying. The worker is verified by running it against a real queue: that
is how the missing engine initialisation in step 4 was found.

`tests/jobs/test_defer_seam.py` covers the wiring itself: that the API process can actually
enqueue against a real connector, and that nothing is enqueued for a transaction that did not
commit. It exists because the by-hand check below verifies the worker's registry and says nothing
about whether anything can defer to it.

A check worth running by hand after any change to the seams — the worker must register every task,
and the periodic list must match architecture §12:

```bash
cd backend && uv run python -c "
import importlib
from app.core.jobs import TASK_MODULES, procrastinate_app
for module in TASK_MODULES: importlib.import_module(module)
print(sorted(procrastinate_app.tasks))
print(sorted(d.task.name for d in procrastinate_app.periodic_registry.periodic_tasks.values()))
"
```

The end-to-end suite needs the Compose stack and the demo dataset:

```bash
bash scripts/dev-up.sh
cd backend && uv run python -m app.cli seed demo
cd ../frontend && npm run e2e
```

The calibration run costs money and is opt-in:

```bash
cd backend && RM_EVAL=1 uv run pytest tests/evaluation -m evaluation -s
```
