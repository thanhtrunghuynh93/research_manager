# Use cases

Version 0.23 — 8 October 2026 — companion to [research_management_requirements.md](research_management_requirements.md) v0.14, [architecture.md](architecture.md) and [implementation_status.md](implementation_status.md)

What each role can do with the system as built: the endpoint, and the screen that calls it. It is
compiled from `backend/app/api/v1/` and `frontend/src/`, not from the specification. Paths are
under `/api/v1` unless shown otherwise. Update it in the pull request that changes a route or a
screen; §8 has the commands that check it.

| Mark | Meaning |
| --- | --- |
| 🖥️ | A screen calls it, and this role can reach that screen |
| ⚙️ | The endpoint works and no screen calls it — reachable only with an HTTP client |

## 1 The screens

Routes in `frontend/src/app/router.tsx`. The guard only avoids offering a dead end; the API enforces
every permission itself (AUTH-02). `/` and unknown paths go to the role's home (`/overview` for a
professor, `/me` for a student); a guard that turns someone away lands them on their own home with
a note naming the page they could not open.

| Route | Guard | Reached from | What is on it |
| --- | --- | --- | --- |
| `/login` | public | the door | Sign in; request a password reset |
| `/accept-invitation` | public | the invitation email | Set a password, then the role's home |
| `/reset-password` | public | the reset email | Set a new password |
| `/status` | public | typed | Readiness of database, object store, worker and mail relay |
| `/me` | student | nav; student home | This week's deadline and report state, obligations per project, earlier weeks with the state of each one submitted (a week with none reads "No report"), links to the editor, the submitted week and own progress |
| `/me/profile` | student | link on `/me` | Trajectory per project; every released assessment |
| `/me/assessments/:id` | student | `/me/profile` | One released assessment: ratings, rationales, its week |
| `/report/:periodId` | student | `/me` | Weekly editor: a tab per required project, autosave, attachments, submit |
| `/report/:periodId/submitted` | student | `/me`, an earlier week on `/me` | What was submitted: every version, every entry, open revision requests |
| `/overview` | professor | nav; professor home | Budget and mail warnings, this week's reports by project and student, outstanding reports, review queue, stalled analyses with retry |
| `/reports` | professor | nav | Every submitted weekly report, grouped by week, newest first: student, projects, submission time, Late, version count, state, each project's assessment. Filters for week, student, project, state and needs review live in the URL. Drafts are never listed |
| `/people` | professor | nav | The roll of the workspace being worked in: invite, resend, move, suspend, restore, remove |
| `/workspaces` | professor | nav | The workspace being worked in (rename for its owner; the weekly schedule), the others belonged to (join, leave, archive), create one. Switching is the workspace name in the header, on every screen |
| `/students/:id` | professor | `/people`, the overview, `/reports`, a project's member list | Approved assessments, trajectory per project, the last eight weeks with each one's report state (a week with none reads "No report") |
| `/students/:studentId/reports/:periodId` | professor | `/students/:id`, `/reports` | One submitted week: versions, entries (including projects since left), mark reviewed, request a revision |
| `/review/:assessmentId` | professor | overview review queue, `/students/:id`, `/reports` | Claims and discrepancies, evidence snapshot, draft ratings; approve, or override with a rationale |
| `/projects` | signed in | nav (both roles) | Projects the caller may see; create one; for a student, projects open to joining and Join |
| `/projects/:id` | signed in | `/projects`, a project title on `/me` | Research questions, description, repository link, members, related documents. Professor: stage, activate, open to joining, assign a student, end a membership. Creator: edit the record. Anyone on it: attach a document |

Navigation: a professor sees Overview, Reports, People, Projects, Workspaces; a student sees their week and
Projects. Member names on `/projects/:id` link to `/students/:id`, which a student cannot open.

## 2 Professor

Professors are co-equal inside a workspace (ADR 0011): none can administer another; that is
break-glass (§6). Every read and write follows the workspace being worked in (ADR 0020, 0021).

### 2.1 Workspaces (AUTH-04..06, UI-08)

| Use case | Endpoint | |
| --- | --- | --- |
| List the workspaces this professor belongs to or owns | `GET /workspaces` | 🖥️ |
| Create a workspace and move into it | `POST /workspaces` | 🖥️ |
| Read, rename, set the timezone (owner) | `GET`/`PATCH /workspaces/{id}` | 🖥️ |
| Join a workspace, or switch to one already joined | `POST /workspaces/{id}/join` | 🖥️ header switcher and `/workspaces` |
| Leave a workspace (refused if it is the only one, or would strand active accounts without a professor) | `POST /workspaces/{id}/leave` | 🖥️ |
| Archive a workspace nobody belongs to (owner) | `POST /workspaces/{id}/archive` | 🖥️ |
| Move a student who has written nothing to another workspace | `POST /users/{id}/workspace` | 🖥️ `/people` |

A student belongs to exactly one workspace, named by their invitation. Moving a student who has
submitted anything is refused by the database: `project_memberships` and `weekly_reports` do not
cascade on update (ADR 0014; `backend/tests/module/identity/test_workspaces.py` pins it).

### 2.2 People (AUTH-01..03)

| Use case | Endpoint | |
| --- | --- | --- |
| Invite a student, or a colleague as a professor; resend a pending invitation | `POST /users/invitations` | 🖥️ |
| See everyone in the workspace; read one user | `GET /users`, `GET /users/{id}` | 🖥️ |
| Suspend, restore | `POST /users/{id}/deactivate`, `/reactivate` | 🖥️ |
| Remove a student (ends every open membership and deactivates) | `POST /users/{id}/remove` | 🖥️ |

Re-inviting an address still `invited` revokes the earlier link. Deactivation, role change and
password reset end every session of that account.

### 2.3 Projects (PROJ-01, 02, 04, 07)

| Use case | Endpoint | |
| --- | --- | --- |
| List projects, read one and its members | `GET /projects`, `/projects/{id}`, `/projects/{id}/members` | 🖥️ |
| Create a project (starts `proposed`) | `POST /projects` | 🖥️ |
| Update a project — any field, including status and `open_to_join` | `PATCH /projects/{id}` | 🖥️ (`ai_restricted` is shown, and set only through the API) |
| Assign a student | `POST /projects/{id}/members` | 🖥️ |
| End a membership, keeping its history | `POST /projects/{id}/members/{membership_id}/end` | 🖥️ |
| Read the project's documents | `GET /artifacts?project_id=`, `GET /artifacts/{id}/download` | 🖥️ |

A project owes reports only while `active`; taking it out of `active` takes the week off everyone on
it, including the week in progress (ADR 0019). A professor reads every project document and removes
none.

### 2.4 Reporting calendar and obligations (REP-01, REP-06)

| Use case | Endpoint | |
| --- | --- | --- |
| Read and configure the weekly schedule — timezone, week start, meeting day, grace | `GET`/`PUT /calendar` | 🖥️ `/workspaces`; saving opens the next weeks and derives this week's obligations |
| List periods | `GET /periods` | 🖥️ |
| Derive this week's obligations now | `POST /periods/{id}/obligations/ensure` | 🖥️ overview |
| See who owes and who has reported | `GET /overview` (week board) | 🖥️ |
| Materialise periods up to a date | `POST /periods/ensure` | ⚙️ — the calendar save and the nightly job do it |
| Excuse an obligation | `POST /obligations/{id}/excuse` | ⚙️ |
| Extend an obligation's deadline | `POST /obligations/{id}/extend` | ⚙️ |

The deadline is 23:59 local on the day before the meeting. Until a calendar is configured no period
exists and `ensure_periods` skips the workspace.

### 2.5 Reading submitted work (REP-02..05, UI-04)

| Use case | Endpoint | |
| --- | --- | --- |
| List every submitted report, by week; filter by week, student, project, state, needs review | `GET /reports` | 🖥️ `/reports`; per student on `/students/:id` |
| Read a student's weekly report | `GET /periods/{id}/report?student_id=` | 🖥️ |
| Read every submitted version, and one by id | `GET /reports/{id}/versions`, `GET /report-versions/{id}` | 🖥️ |
| Open an attachment | `GET /artifacts`, `GET /artifacts/{id}/download` | 🖥️ |
| Request a revision of one project entry; see open requests | `POST`/`GET /reports/{id}/revisions` | 🖥️ |
| Mark a report reviewed | `POST /reports/{id}/reviewed` | 🖥️ |
| Read every stored version of one attachment | `GET /artifacts/{id}/versions` | ⚙️ |

The reader never shows `draft_content`: an unsubmitted draft is not a submission. For the same
reason the list never shows a draft. Its Late flag is the first submission against the deadline that
applied — grace, then any extension, including one granted afterwards.

### 2.6 Assessment (ASSESS-01..10, UI-05)

| Use case | Endpoint | |
| --- | --- | --- |
| List assessments; read a draft and its evidence snapshot | `GET /assessments`, `/assessments/{id}`, `/assessments/{id}/evidence` | 🖥️ |
| Approve, or override with a recorded rationale | `POST /assessments/{id}/approve` | 🖥️ |
| See a student's trajectory on a project | `GET /trends` | 🖥️ |
| Re-run a stalled assessment | `POST /admin/assessments/retry` | 🖥️ overview |
| Withdraw a published assessment | `POST /assessments/{id}/withdraw` | ⚙️ |

Drafts are produced by the pipeline when a report is submitted; nothing reaches a student unapproved.
The evidence index has no route of its own: the pipeline reads it when it builds a snapshot.

### 2.7 Operations (UI-01, §11)

| Use case | Endpoint | |
| --- | --- | --- |
| The current week: deadline, week board, outstanding with as-of time, review queue, stalled analyses, budget and mail warnings | `GET /overview` | 🖥️ |
| Model spend this month | `GET /admin/ai/usage` | ⚙️ |
| Read and set monthly AI budgets (none set means no limit) | `GET`/`PUT /admin/ai/budgets` | ⚙️ |

## 3 Student

| Use case | Endpoint | |
| --- | --- | --- |
| Accept an invitation and set a password | `POST /auth/accept-invitation` | 🖥️ |
| See the week — period, deadline, what is owed | `GET /periods`, `GET /periods/{id}/obligations` | 🖥️ |
| Write the weekly report, a tab per required project, autosaving | `GET /periods/{id}/report`, `PATCH /periods/{id}/report/draft` | 🖥️ |
| Attach a file straight to the object store | `POST /artifacts/uploads`, `POST /artifacts/{id}/confirm` | 🖥️ |
| Remove a file they attached, submitted week or not | `DELETE /artifacts/{id}` | 🖥️ |
| Submit the weekly package (idempotent) | `POST /periods/{id}/report/submit` | 🖥️ |
| See their earlier weeks and the state of each one submitted | `GET /reports` | 🖥️ `/me` |
| Read what they submitted, every version, and any revision requested | `GET /reports/{id}/versions`, `/report-versions/{id}`, `/reports/{id}/revisions` | 🖥️ |
| Read their projects, members and documents; attach and remove their own documents | `GET /projects/...`, `GET /artifacts?project_id=`, `POST /artifacts/uploads`, `DELETE /artifacts/{id}` | 🖥️ |
| Start a project (active at once) | `POST /projects` | 🖥️ |
| Edit the record of a project they started (not its status, joining or AI restriction) | `PATCH /projects/{id}` | 🖥️ |
| See projects open to joining, and join one | `GET /projects/joinable`, `POST /projects/{id}/join` | 🖥️ |
| Read their approved assessments and trajectory | `GET /assessments`, `/assessments/{id}`, `GET /trends` | 🖥️ |
| Read an assessment's evidence snapshot | `GET /assessments/{id}/evidence` | ⚙️ by choice: UI-02 does not ask for it, and `MyAssessmentPage.test.tsx` fails if the screen requests it |

A student may not assign anyone to a project or end any membership, their own included (ADR 0019).
Joining part-way through a week owes from the next week. Joining and ending memberships are rate
limited to thirty an hour. A membership grants the project record, its documents and member list —
never another student's reports, assessments or private evidence.

## 4 Either role

| Use case | Endpoint | |
| --- | --- | --- |
| Sign in, sign out, read own account | `POST /auth/login`, `/auth/logout`, `GET /auth/me` | 🖥️ |
| Request and confirm a password reset | `POST /auth/password-reset`, `/auth/password-reset/confirm` | 🖥️ |
| Update their own profile | `PATCH /users/me` | ⚙️ |

The only notification is the missed-deadline email (REP-08); there is no in-app notification
screen. The professor sees who is outstanding on the overview.

## 5 Unauthenticated

| Use case | Endpoint | Notes |
| --- | --- | --- |
| Sign in | `POST /auth/login` | 10 per 5 minutes per address |
| Accept an invitation | `POST /auth/accept-invitation` | 10 per hour |
| Request a password reset | `POST /auth/password-reset` | 5 per hour; identical answer for known and unknown addresses |
| Liveness and readiness | `GET /api/healthz`, `GET /api/readyz` | `readyz` covers database, object storage, worker and mail relay |
| Prometheus metrics | `GET /api/metrics` | Bearer token in production; blocked at the edge |

## 6 Operator

A person with a shell on the host (`python -m app.cli …` in the api container).

| Use case | Command |
| --- | --- |
| Create a workspace and its first professor | `identity bootstrap` (each run makes a new workspace) |
| End every session in the deployment | `identity revoke-all-sessions` |
| Re-run the missed-deadline dispatch after a mail fix | `notifications dispatch-missed-deadline` |
| Drain the queued email table now | `notifications send-queued-emails` |
| Load the demo dataset or the missed-deadline drill (never in production) | `seed demo`, `seed missed-deadline-drill` |
| Recover a locked-out professor | `breakglass recover-professor` |
| Transfer, demote or deactivate a professor | `breakglass transfer-professor`, `demote-professor`, `deactivate-professor` |

Every break-glass use is audited and refuses to leave a workspace with no active professor.

## 7 System

Periodic tasks in the worker (architecture §12).

| Task | Cadence | What it does |
| --- | --- | --- |
| `ensure_periods` | daily 00:15 | Materialises the next weeks for every workspace with a calendar |
| `freeze_baselines` | daily 00:30 | Freezes each membership's plan once its period opens |
| `scan_due_reminders` | 5 min | Finds weeks whose deadline has passed and queues the missed-deadline email |
| `send_queued_emails` | 2 min | Drains the email delivery table |
| `queue_health` | 5 min | Logs queue lag; its runs are the worker heartbeat `/api/readyz` reads |
| `retention_sweep` | daily 01:45 | Deletes queue jobs finished more than seven days ago |

Event-driven jobs: assessment pipeline per changed entry on submission; attachment extraction on
submission; evidence indexing of entries and extracted attachments; invitation and reset emails.

## 8 Keeping this document true

```bash
# every route
grep -rnE '^@router\.(get|post|put|patch|delete)' backend/app/api/v1/
# every call a screen makes is served, and every `METHOD /api/...` cited in docs exists
python3 scripts/check_docs.py
# every inbound link; a route in router.tsx that nothing links to is orphaned
grep -rnE '(to=\{?["`]/|navigate\(["`]/)' frontend/src --include=*.tsx | grep -v '\.test\.'
```

A ⚙️ row is either given a screen or given up; the history of rows removed that way is in the
requirements changelog (§15) and git.
