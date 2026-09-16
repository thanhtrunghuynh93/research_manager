# Use cases

Version 0.1 — 16 September 2026 — companion to [research_management_requirements.md](research_management_requirements.md) v0.3, [architecture.md](architecture.md), and [implementation_status.md](implementation_status.md)

What each role can actually do with the system as built, by role.

This document is compiled from `backend/app/api/v1/` and from the frontend code that calls it,
not from the specification. That distinction is the point: the requirements say what the system
should do, [implementation_status.md](implementation_status.md) says which modules are finished,
and neither answers the question a professor asks on their first morning — *what can I do here?*
Every row below was checked against a route and against the screens that call it.

## How to read the tables

| Mark | Meaning |
| --- | --- |
| 🖥️ | There is a screen. A person can do this in the app. |
| ⚙️ | The endpoint exists and works, and nothing in the app calls it. Reachable only with an HTTP client or a host shell. |

⚙️ is not the same as unbuilt. The service, its permission predicate and its tests are in place, and
the route is live; what is missing is a way in. The distinction matters because the two need
different work — a screen, versus a feature — and because a reader of
[implementation_status.md](implementation_status.md) alone would conclude that everything below is
available. A step marked Done there means its module is done; what calls it is the separate
question, and this document is the answer to it.

**As of this version: 96 endpoints, 43 of them reachable from the app.**

## 1 Professor

The professor supervises students, sets the terms of the work, and decides what is published.
Professors are co-equal: one cannot administer another (ADR 0011), and the only route between
professor accounts is the break-glass procedure in §5.

### 1.1 Enrolment and people (AUTH-01..03)

| Use case | Endpoint | |
| --- | --- | --- |
| Invite a student, or a colleague as a professor | `POST /users/invitations` | 🖥️ |
| See everyone in the workspace | `GET /users` | 🖥️ |
| Read one user's record directly | `GET /users/{id}` | ⚙️ |
| Suspend an account's access | `POST /users/{id}/deactivate` | 🖥️ |
| Reactivate an account | `POST /users/{id}/reactivate` | 🖥️ |
| Remove a student from the workspace | `POST /users/{id}/remove` | 🖥️ |

Enrolment is invitation-only and there is no self-registration, so the invitation email is the only
door into the system. Deactivation, role change and password reset each revoke every session and
advance the workspace access epoch in the same transaction.

### 1.2 Projects (PROJ-01..06)

| Use case | Endpoint | |
| --- | --- | --- |
| Read a project, its members, decisions and weighted progress | `GET /projects`, `/projects/{id}`, `/{id}/members`, `/{id}/decisions`, `/{id}/progress` | 🖥️ |
| Read a project's milestones | `GET /projects/{id}/milestones` | 🖥️ |
| Read a milestone's retained baselines | `GET /milestones/{id}/revisions` | ⚙️ |
| **Create a project** | `POST /projects` | ⚙️ |
| **Update a project** — title, research questions, stage, status | `PATCH /projects/{id}` | ⚙️ |
| **Assign a student to a project** | `POST /projects/{id}/members` | ⚙️ |
| End a membership, keeping its history | `POST /projects/{id}/members/{membership_id}/end` | ⚙️ |
| Record a dated research decision and its rationale | `POST /projects/{id}/decisions` | ⚙️ |
| Create a milestone; update its scope or weight | `POST /projects/{id}/milestones`, `PATCH /milestones/{id}` | ⚙️ |
| Create a task | `POST /projects/{id}/tasks` | ⚙️ |
| Read tasks | `GET /projects/{id}/tasks` | ⚙️ |

Nothing in this section can be done from the app. That has a consequence beyond inconvenience, set
out in §7.

### 1.3 The reporting calendar (REP-01, REP-06)

| Use case | Endpoint | |
| --- | --- | --- |
| List reporting periods | `GET /periods` | 🖥️ |
| See who owes a report this period | `GET /periods/{id}/obligations` | 🖥️ |
| **Configure the reporting calendar** — timezone, week start, meeting day, grace | `PUT /calendar` | ⚙️ |
| Materialise periods up to a date | `POST /periods/ensure` | ⚙️ |
| Derive obligations for a period | `POST /periods/{id}/obligations/ensure` | ⚙️ |
| Excuse one student's obligation | `POST /obligations/{id}/excuse` | ⚙️ |
| Extend one student's deadline | `POST /obligations/{id}/extend` | ⚙️ |
| Set how long before a deadline to remind | `PUT /notifications/reminder-offsets` | ⚙️ |

The deadline is fixed by rule rather than chosen per period: 23:59 local on the day before the
weekly meeting. The calendar decides the rest. Until it is configured, every screen that needs a
current period reads "No reporting period has been configured yet", and the daily `ensure_periods`
task skips the workspace deliberately rather than inventing a schedule.

### 1.4 Reading submitted work (REP-02..05, UI-04)

| Use case | Endpoint | |
| --- | --- | --- |
| Read a weekly report | `GET /periods/{id}/report` | 🖥️ |
| Read one submitted version by id | `GET /report-versions/{id}` | ⚙️ |
| Open an attachment | `GET /artifacts`, `GET /artifacts/{id}/download` | 🖥️ |
| See a student's profile and history | — (composed from the above) | 🖥️ |
| Read every stored version of one attachment | `GET /artifacts/{id}/versions` | ⚙️ |
| Request a revision of one project entry | `POST /reports/{id}/revisions` | ⚙️ |
| See outstanding revision requests | `GET /reports/{id}/revisions` | ⚙️ |
| Mark a report reviewed | `POST /reports/{id}/reviewed` | ⚙️ |

### 1.5 Assessment (ASSESS-01..10, UI-05)

| Use case | Endpoint | |
| --- | --- | --- |
| Read a draft assessment and the evidence snapshot it was made from | `GET /assessments/{id}`, `/{id}/evidence` | 🖥️ |
| Approve and publish an assessment | `POST /assessments/{id}/approve` | 🖥️ |
| See a student's trajectory on one project | `GET /trends` | 🖥️ |
| Withdraw a published assessment | `POST /assessments/{id}/withdraw` | ⚙️ |
| Read feedback on an assessment | `GET /assessments/{id}/feedback` | ⚙️ |
| Record a private supervision note | `POST /supervision-notes` | ⚙️ |
| Re-run one assessment pipeline | `POST /admin/assessments/retry` | ⚙️ |

Drafts are the professor's to approve; nothing reaches a student unapproved. An override requires a
recorded reason and keeps the model's own output beside it. Supervision notes live in a table
nothing indexes and are read through a function the student branch never calls, so their
confidentiality is structural rather than a matter of filtering.

### 1.6 Repository evidence (REPO-01..08)

| Use case | Endpoint | |
| --- | --- | --- |
| Connect a repository the professor has read access to | `POST /repositories` | ⚙️ |
| List connected repositories | `GET /repositories` | ⚙️ |
| Say which project a repository's work belongs to | `POST /repositories/{id}/projects` | ⚙️ |
| See a repository's last sync, its range and any error | `GET /repositories/{id}/sync` | ⚙️ |
| Resync now | `POST /repositories/{id}/sync` | ⚙️ |
| Confirm a student's claimed developer identity | `POST /developer-identities/{id}/confirm` | ⚙️ |
| See contributions attributed to a student | `GET /contributions` | ⚙️ |
| Search the evidence index | `GET /evidence/search` | ⚙️ |
| Open one citable evidence reference | `GET /evidence/references/{id}` | ⚙️ |

Nothing in this section can be done from the app either, which means repository evidence cannot be
switched on by the person it was built for.

### 1.7 The assistant and exports (QA-01..07, UI-06)

| Use case | Endpoint | |
| --- | --- | --- |
| Ask a cited question about the workspace's research | `POST /assistant/ask` | 🖥️ |
| Read their own past conversations | `GET /assistant/conversations` | 🖥️ |
| Export authorized records as a bundle or a spreadsheet | `GET /exports`, `/exports/kinds`, `/exports/{kind}.csv` | 🖥️ |
| Watch the steps while an answer is produced | `POST /assistant/ask/stream` | ⚙️ |
| Read one conversation's turns | `GET /assistant/conversations/{id}/messages` | ⚙️ |

A fact question never reaches the generation step: the obligations table says how many reports are
missing and that number is rendered rather than written. Citations are checked against what was
actually retrieved, and an invented one is dropped and the drop is stated.

### 1.8 Operations (UI-01, requirements §11)

| Use case | Endpoint | |
| --- | --- | --- |
| The current week at a glance — outstanding reports, review queue, stale repositories, stalled analyses, AI budget, failed mail | `GET /overview` | 🖥️ |
| See model spend this month | `GET /admin/ai/usage` | ⚙️ |
| See and set the monthly AI budgets | `GET`/`PUT /admin/ai/budgets` | ⚙️ |
| See repository sync health | `GET /admin/sync` | ⚙️ |

No budget configured means no limit, not a limit of zero. Since the budget can only be set through
the API, a deployment with a live model key spends without a ceiling until someone sets one by
hand.

## 2 Student

| Use case | Endpoint | |
| --- | --- | --- |
| Accept an invitation and set a password | `POST /auth/accept-invitation` | 🖥️ |
| See their week — period, deadline, what they owe | `GET /periods`, `/periods/{id}/obligations` | 🖥️ |
| Write the weekly report, a tab per required project, autosaving | `PATCH /periods/{id}/report/draft` | 🖥️ |
| Attach a file, straight from the browser to the object store | `POST /artifacts/uploads`, `/artifacts/{id}/confirm` | 🖥️ |
| Attach a link | `POST /artifacts/links` | 🖥️ |
| Submit the weekly package | `POST /periods/{id}/report/submit` | 🖥️ |
| Read their own projects, milestones, decisions and progress | `GET /projects/...` | 🖥️ |
| Read an approved assessment and its evidence | `GET /assessments/{id}`, `/{id}/evidence` | 🖥️ |
| Export their own records | `GET /exports` | 🖥️ |
| Report progress on a task | `PATCH /tasks/{id}` | ⚙️ |
| Request a correction to an assessment, with evidence | `POST /assessments/{id}/corrections` | ⚙️ |
| Claim a provider account as their own | `POST /developer-identities` | ⚙️ |
| See contributions attributed to them | `GET /contributions` | ⚙️ |
| Search the evidence they can see | `GET /evidence/search` | ⚙️ |

Submission writes an immutable version with one entry per required project; a repeated submission
carrying the same idempotency key returns the version already written. A submission survives a dead
worker by design — a failed enqueue is logged and swallowed, because report acceptance must not
wait on anything downstream.

**The student has no assistant.** That is deliberate and recorded as next-release work: the
retrieval path and the permission predicate are already shared, so it is a surface rather than a
rebuild.

## 3 Either role

| Use case | Endpoint | |
| --- | --- | --- |
| Sign in, sign out, read own profile | `POST /auth/login`, `/auth/logout`, `GET /auth/me` | 🖥️ |
| Request and confirm a password reset | `POST /auth/password-reset`, `/password-reset/confirm` | 🖥️ |
| Read notifications and mark one read | `GET /notifications`, `POST /notifications/{id}/read` | 🖥️ |
| Mute and unmute a non-critical category | `POST /notifications/preferences/mute`, `/unmute` | 🖥️ |
| Update their own profile | `PATCH /users/me` | ⚙️ |
| Mark every notification read | `POST /notifications/read-all` | ⚙️ |
| Count unread notifications | `GET /notifications/unread-count` | ⚙️ |

Critical categories cannot be muted.

## 4 Unauthenticated

| Use case | Endpoint | Notes |
| --- | --- | --- |
| Sign in | `POST /auth/login` | Rate limited: 10 per 5 minutes per address |
| Accept an invitation | `POST /auth/accept-invitation` | 10 per hour |
| Request a password reset | `POST /auth/password-reset` | 5 per hour; answers identically for a known and an unknown address |
| Liveness and readiness | `GET /healthz`, `/readyz` | `readyz` covers database, object storage, worker and mail relay |
| Prometheus metrics | `GET /metrics` | Bearer token required in production; blocked at the edge |
| Signed GitHub delivery | `POST /webhooks/github` | HMAC-verified; an unknown repository is accepted, recorded and reported as unmatched |

## 5 Operator

Not a role in the product: a person with a shell on the host. These exist because some actions must
not be reachable from a session, and some are needed before any account exists.

| Use case | Command |
| --- | --- |
| Create the workspace and its first professor | `app.cli identity bootstrap` |
| End every session in the workspace | `app.cli identity revoke-all-sessions` |
| Send the missed-deadline dispatch again after a mail misconfiguration | `app.cli notifications dispatch-missed-deadline` |
| Drain the queued email table now | `app.cli notifications send-queued-emails` |
| Load the demo dataset, or the missed-deadline drill | `app.cli seed demo`, `seed missed-deadline-drill` |
| Recover a locked-out professor | `app.cli breakglass recover-professor` |
| Transfer, demote or deactivate a professor | `app.cli breakglass transfer-professor`, `demote-professor`, `deactivate-professor` |

Break-glass is the only route between professor accounts, and every use is audited. The demo seed
creates a professor with a published password and must never be run on a production deployment.

## 6 System

No human initiates these. They run in the worker and are why the product advances unattended.

| Task | Cadence | What it does |
| --- | --- | --- |
| `ensure_periods` | daily | Materialises the next weeks for every workspace with a calendar |
| `freeze_baselines` | daily | Fixes each membership's plan once its period opens |
| `scan_due_reminders` | short | Finds obligations approaching their deadline |
| `dispatch_due_reminders` | 15 min | Sends those reminders |
| `send_queued_emails` | 2 min | Drains the email delivery table |
| `incremental_sync` | 30 min | Pulls new repository evidence |
| `queue_health` | 5 min | Refreshes the metric gauges |
| `retention_sweep` | nightly | Expires the assistant's answer cache |

Both calendar tasks are idempotent by construction, so a worker that was down for a day catches up
rather than skipping a week.

## 7 What this inventory shows

Three capability areas have no screens at all — **project setup** (§1.2), **calendar
administration** (§1.3), and **repository evidence** (§1.6) — along with every operations view
(§1.8). The student's side is complete; the professor's half of the same modules is not.

These compose into one consequence that no single missing screen would suggest. Obligations derive
from project memberships. Memberships require a project. Creating a project and assigning a student
are both ⚙️. So on a correctly deployed system, with the calendar configured and the worker
running:

> no report is ever due, because no obligation can ever be derived, because no project can be
> created from the app.

Each link is a working, tested endpoint. The chain is broken only at the surface.

This is the failure shape [implementation_status.md](implementation_status.md) §1 already names
twice — *"a step marked Done means its module is done, and the question worth asking separately is
what calls it"* — appearing a third time, one layer up. The earlier instances were missing seams
between modules. This one is a missing seam between the product and the people who use it.

## 8 Keeping this document true

The route inventory is mechanical, and drift here is the kind nobody notices:

```bash
# every route, with the role gate it sits behind
grep -rnE '^@router\.(get|post|put|patch|delete)' backend/app/api/v1/

# every endpoint the app actually calls. Both exclusions matter: the generated OpenAPI types
# name every route whether or not anything calls it, and the test files mock endpoints the app
# has no screen for — counting either one reports coverage the product does not have.
for f in $(grep -rl 'api/v1' frontend/src --include=*.ts --include=*.tsx \
             | grep -v generated | grep -v '\.test\.'); do
  grep -ohE '[`"]/api/v1/[^`"]*' "$f"
done | sed 's/[`"]//' | sed 's/\?.*//' | sed 's/\${[^}]*}/X/g' | sort -u
```

The character class covers both quote styles on purpose: a parameterised path is written as a
template literal, so a grep for double-quoted strings alone finds the handful of fixed paths and
misses most of the app — it reports 18 where the answer is 41.

Update this file in the pull request that changes what it describes, as with
[implementation_status.md](implementation_status.md).
