# Use cases

Version 0.12 — 17 September 2026 — companion to [research_management_requirements.md](research_management_requirements.md) v0.6, [architecture.md](architecture.md), and [implementation_status.md](implementation_status.md)

What each role can actually do with the system as built, by role.

This document is compiled from `backend/app/api/v1/` and from the frontend code that calls it,
not from the specification. That distinction is the point: the requirements say what the system
should do, [implementation_status.md](implementation_status.md) says which modules are finished,
and neither answers the question a professor asks on their first morning — *what can I do here?*
Every row below was checked against a route, against the screens that call it, and — since v0.2 —
against the links that reach those screens. The third check is the one that moves rows.

v0.3 recorded a scope decision before the code agreed with it: notifications and exports retired
as user-facing features, workspace management added as a professor capability. v0.4 removed the
first, v0.5 built the second. v0.6 added entering and leaving, which answered the refusal §2.1 hit
in v0.5 from the other side: an account could not change workspace, so the session did instead
(ADR 0013). v0.7 paid the schema cost instead and made the account movable (ADR 0014), and v0.8
made belonging plural (ADR 0015). **v0.10 is the one that changes what a professor sees**: reads
span every workspace they belong to (ADR 0016), writes still land in one, and the screens group by
workspace. §2.1 has the split that made all of it possible.

**v0.11 is the one that changes what can happen at all.** It closes the two findings this document
has been carrying: §8.1, that no report could ever become due because no project could be created
from the app, and the last row of §8.2, that an assessment approved for a student had no screen on
which that student could read it. Neither needed a new capability — every endpoint involved already
worked and was already tested. What both needed was a caller.

## How to read the tables

| Mark | Meaning |
| --- | --- |
| 🖥️ | There is a screen, and this role can get to it. |
| 🚧 | A screen calls it, but not one this role can open: either the role guard turns them away, or nothing in the app links to the screen. |
| ⚙️ | The endpoint exists and works, and no screen calls it at all. Reachable only with an HTTP client or a host shell. |
| ✂️ | Built, working, and leaving scope — a decision taken, not yet carried out. No row carries it today; v0.3's did, and v0.4 removed them with the code. |
| ◻️ | In scope and not built. No screen, no route, no service. No row carries it as of v0.9: the last one, moving a student, was built in the half the schema allows. |

⚙️ is not the same as unbuilt. The service, its permission predicate and its tests are in place, and
the route is live; what is missing is a way in. The distinction matters because the two need
different work — a screen, versus a feature — and because a reader of
[implementation_status.md](implementation_status.md) alone would conclude that everything below is
available. A step marked Done there means its module is done; what calls it is the separate
question, and this document is the answer to it.

🚧 is the mark this document lacked in v0.1, and adding it moved seven rows that had been read as
available. It exists because a screen is not a capability until the person who needs it can arrive
at it, and the two ways of failing that — a guard that says no, and a page nothing links to — are
both invisible in a route inventory. §1 is where they become visible.

✂️ and ◻️ are the two marks that point away from the code rather than at it, and they are read in
opposite directions. A ✂️ row describes something a reader can do right now and will not be able to
later, so it stays visible until the code catches up; deleting it before then would make this
document disagree with a running deployment. A ◻️ row describes the reverse. Neither is a 🚧: 🚧 is
a gap nobody chose.

v0.3 marked ten endpoints ✂️ and v0.4 removed all ten; v0.3 marked six use cases ◻️ and v0.9
finished the last of them. Both marks did what they were for: they held a decision in view for
exactly as long as it was ahead of the code, and stopped being needed the moment it was not.

**As of this version: 97 endpoints, 49 of them called by a screen, and nothing left marked ◻️.**
v0.4 removed ten — seven notification routes and three export routes, with `PUT
/notifications/reminder-offsets` surviving because it configures email delivery (§7) — and v0.5 to
v0.9 added eight for workspaces and one for moving a student, every one of them behind a screen.
v0.12 added two, `GET /projects/joinable` and `POST /projects/{id}/join`, and opened three more
to students: creating a project, patching one they created, and ending their own membership
(PROJ-07, AUTH-07).

The second number is not the whole answer even so, because reachability is per role:
`GET /periods/{id}/report` is 🖥️ for the student who writes the report and 🚧 for the professor who
is meant to read it.

## 1 The screens

Sixteen routes and one shell, in `frontend/src/app/router.tsx`. The guard is the route's own; the
API enforces every permission itself regardless (AUTH-02), so the guard is about not offering a
dead end rather than about security.

| Route | Guard | How a person arrives | What is on it |
| --- | --- | --- | --- |
| `/login` | public | the door | Sign in |
| `/accept-invitation` | public | the invitation email — the token is the credential | Set a password, then the role's home |
| `/reset-password` | public | the reset email | Request, and confirm |
| `/status` | public | typed | Readiness of database, object store, worker, mail relay |
| `/me` | student | nav, and the student's home | The deadline set as a figure, the report's state, obligations per project, earlier weeks, and the way through to the released record |
| `/me/profile` | student | a link on `/me` — it is not on the navigation bar, and `/me` no longer lists assessments itself | Trajectory per project, every released assessment |
| `/me/assessments/:id` | student | a row on `/me` or `/me/profile` | One released assessment: ratings, rationales, feedback, and a correction request |
| `/report/:periodId` | student | the button on `/me` | A tab per required project, autosaving; attachments and links; submit |
| `/overview` | professor | nav, and the professor's home | Budget and mail warnings, outstanding reports, review queue, sync issues, stalled analyses |
| `/people` | professor | nav | Everyone in every workspace they belong to, grouped by workspace; invite, move, suspend / restore / remove |
| `/workspaces` | professor | nav | The workspaces they belong to or own; join, leave, create, archive. The reporting calendar, and the weeks it opens |
| `/projects` | signed in | nav (both roles since PROJ-07; a student's bar is their week, then this); a project title on `/me` | Every project the caller may see; create one. For a student, the projects a professor has opened to joining, and a Join on each |
| `/students/:id` | professor | a name on `/people`, or on the overview's outstanding list | Approved assessments, trajectory per project, downloadable materials |
| `/review/:assessmentId` | professor | the overview's review queue, or a student's profile | Ratings per dimension, confidence, the evidence snapshot, approve with a rationale |
| `/assistant` | professor | nav | Facts, synthesis, citations, gaps |
| `/projects/:id` | signed in | the list at `/projects`, a title on `/me`, a member row | Research questions, weighted progress, members, milestones, dated decisions. Activate the project, open it to joining, assign a student (professor); edit the record (its creator); leave it (a student on it) |

v0.4 removed two rows, `/notifications` and `/exports`, and they were the two either role could
open; v0.5 added `/workspaces`. What is left is a professor's six and a student's two, meeting
nowhere but the sign-in pages and `/projects/:id` — which nothing links to, so in practice they do
not meet at all.

(v0.2 and v0.3 counted fourteen rows here as "thirteen routes". The table was right and the
sentence was not; the counts here have been correct since v0.4.)

The navigation offers five items to a professor and two to a student, and mirrors the guard
exactly: a page the caller cannot load is never linked, because a link that always fails is worse
than no link. `/` and anything unrecognised go to the home for the role — `/overview` for a
professor, `/me` for a student.

That last rule has an edge the navigation cannot show. Both the guard and the catch-all *redirect*
rather than refuse, so a person who follows a link into a page their role cannot open does not see
a refusal: they arrive at their own home, having lost what they clicked and with nothing to say
why. One link inside the app already does this — the member names on `/projects/:id` point at
`/students/:id`, which is professor-only, from a screen either role may open — and §8.2 is where it
happens in normal use.

## 2 Professor

The professor supervises students, sets the terms of the work, and decides what is published.
Professors are co-equal: one cannot administer another (ADR 0011), and the only route between
professor accounts is the break-glass procedure in §6.

### 2.1 Workspaces (AUTH-04, AUTH-05, AUTH-06, UI-08 — ADR 0012, 0014, 0015, 0016)

A professor belongs to as many workspaces as they like and works in one of them at a time. Joining
adds a membership and takes them there; leaving gives one up. Ownership decides which workspaces
they may create and archive, and is not a word the screen uses — it is the mechanism, not the
capability. Co-equality between professors is unchanged inside a workspace (ADR 0012, amending
ADR 0011).

What a professor may *enter or read* is the union of the two relations — owned, plus belonged to —
because they genuinely differ: a colleague belongs to a workspace they do not own, and someone who
created a workspace and later left owns one they do not belong to. `GET /workspaces` returns that
union, so every action offered on the screen has to be gated on it too. ADR 0014's "you can only
join a workspace you own" was written before belonging was plural and is amended there. Renaming
and archiving stay with ownership alone.

| Use case | Endpoint | |
| --- | --- | --- |
| List the workspaces this professor can be in | `GET /workspaces` | 🖥️ |
| Create a workspace, and be moved into it | `POST /workspaces` | 🖥️ |
| Read one, rename it, set its timezone | `GET`/`PATCH /workspaces/{id}` | 🖥️ |
| Join a workspace, or switch to one already joined | `POST /workspaces/{id}/join` | 🖥️ |
| Leave a workspace, keeping the others | `POST /workspaces/{id}/leave` | 🖥️ |
| See everyone across the workspaces they belong to | `GET /users` | 🖥️ (§2.2) |
| Archive a workspace nobody is in | `POST /workspaces/{id}/archive` | 🖥️ |
| Remove a student from a workspace | `POST /users/{id}/remove` | 🖥️ (§2.2) |
| Move a student to another workspace, before they start | `POST /users/{id}/workspace` | 🖥️ (§2.2) |

A student belongs to exactly one workspace and the invitation names it (§2.2), so they have one
from the moment they are enrolled and never have none. `POST /users/invitations` now carries
`workspace_id`; omitting it means the caller's own, which is what the caller's Scope always
supplied implicitly.

Three rules follow from the tenant boundary rather than from taste, and ADR 0012 has the reasoning:
a workspace is **created empty**, because its creator already belongs to theirs and a user belongs
to one; it is **archived, never deleted**, because every foreign key into a workspace cascades and
a delete would take the history with it; and archiving **refuses while any account is still
active**, so the flag never has to be enforced further down.

**Reads span every workspace you belong to; writes go to one** (ADR 0016). `Scope` carries both:
`workspace_ids` is what a read may see, `workspace_id` is where a write lands. The comparison lives
in `Scope.within`, one function that all thirty-three visibility predicates call — widening what a
read may see is the most consequential change anyone can make here, and it should be visible in one
diff rather than spread across seven `policies.py` files. A student belongs to one workspace, so
their set has one element and nothing about their access changed.

That is why "working here" still exists and is now a smaller idea than it was: it decides where new
things land, not what you can see.

**Belonging is plural; working in one is singular** (ADR 0015). `workspace_members` records the
first and `users.workspace_id` the second — the workspace a Scope is compiled from and the anchor
every composite foreign key points at. Joining adds a membership and moves the anchor; joining one
you already belong to moves only the anchor, which is how switching is spelled.

That split fixed three checks that had been reading the wrong column. Archiving counts
**memberships**, so a workspace cannot be archived out from under a professor who belongs to it but
is working elsewhere. The roll is keyed by **membership**, so a colleague working elsewhere stays
on it. And leaving is refused when it is your **only** membership, because `users.workspace_id` is
not nullable and the anchor would have nowhere to go.

Leaving still **must not strand people**: a workspace holding active accounts is never left without
an active professor, AUTH-01's rule applied to an ordinary call rather than only to break-glass.
Leaving the last member out is allowed, and is the path to archiving.

**The last row was ◻️ from v0.3 to v0.8, and is now half-built — because half of it is refused.**

`users.workspace_id` is the parent of a composite foreign key on eight tables, and v0.7 split them
in half (ADR 0014):

| | Tables | On update |
| --- | --- | --- |
| Identity — belongs to the person | `invitations`, `sessions`, `password_resets`, `notifications` | **cascade**, so they follow the account |
| History — belongs to the work | `project_memberships`, `weekly_reports`, `developer_identities`, `contributions` | **refuse**, so the account cannot leave them |

A professor has only identity rows, so they move. A student who has submitted anything has history
rows, so Postgres refuses — and *that* is now what "history stays in the workspace it was written
in" means. It is not a route that was never written; it is four constraints that say no.

So v0.9 builds the half that is reachable. `POST /users/{id}/workspace` moves a student who has not
started — the case that matters in practice, an account enrolled into the wrong workspace — and
refuses one who has, in the API's own words. The refusal is left to the database rather than
reimplemented: identity sits below projects, reporting and evidence in the layer order and cannot
ask them what they hold, so the move runs inside a savepoint and the `IntegrityError` is caught and
explained. The constraint *is* the rule, and asking it is more honest than keeping a second copy of
it in Python that could drift.

Before v0.7 none of the eight cascaded, and since enrolment is invitation-only every account had an
`invitations` row from creation, so no account could move at all. That is requirements §9's
*foreign keys scoped to the same workspace* read from the other direction, and the decision
recorded in v0.3 — that a moved student leaves their history behind — turned out to be what the
schema was already enforcing, for everyone.

Moving a student who has *started* is still not possible, and the two ways out are unchanged:

- **Let the history move.** Cascade the other four as well, and every record follows the student.
  It also drags `project_memberships` to projects that stayed behind, so it is not one change but
  two.
- **Let the move be a new account.** Close the account here and enrol a fresh one there, which is
  what "history stays behind" means exactly. `users.email` is globally unique and login resolves an
  address to one row, so this needs per-workspace addresses and a way to disambiguate a sign-in.

`tests/module/identity/test_workspaces.py` pins the invariant so that a future attempt to add the
move fails there first, with the reason attached.

One more thing the ownership decision costs, recorded because a reader will meet it before they
meet the ADR: a professor invited as a colleague into someone else's workspace can do everything
ADR 0011 grants — students, projects, reports, assessments — and cannot rename the workspace they
work in. `/workspaces` lists it and shows no controls beside it, rather than offering a button that
would always fail.

### 2.2 Enrolment and people (AUTH-01..03)

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

The first row is where a student gets their workspace. `InvitationIn` carries `workspace_id`
alongside the email, name and role; omitting it means the caller's own, which is what
`ProfScopeDep` always supplied implicitly. The invitation form on `PeoplePage` shows a picker only
when the professor owns more than one workspace open to invitations — one choice is not a
choice, and an archived workspace refuses them.

This is the only moment a workspace is chosen. `invite_user` refuses an address that belongs to a
user in another workspace with the same "a user with this email already exists" it gives for a
local duplicate, so a second invitation is not how a student moves — and §2.1 explains why nothing
else is either.

### 2.3 Projects (PROJ-01..07)

| Use case | Endpoint | |
| --- | --- | --- |
| Read a project, its members, decisions and weighted progress | `GET /projects`, `/projects/{id}`, `/{id}/members`, `/{id}/decisions`, `/{id}/progress` | 🖥️ |
| Read a project's milestones | `GET /projects/{id}/milestones` | 🖥️ |
| Read a milestone's retained baselines | `GET /milestones/{id}/revisions` | ⚙️ |
| **Create a project** | `POST /projects` | 🖥️ both roles |
| **Update a project** — title, research questions, stage, status | `PATCH /projects/{id}` | 🖥️ — a professor sets any field; the creator sets the record but not its standing |
| **Assign a student to a project** | `POST /projects/{id}/members` | 🖥️ |
| End a membership, keeping its history | `POST /projects/{id}/members/{membership_id}/end` | 🖥️ for the student leaving their own; ⚙️ for the professor ending anyone's |
| **List the projects open to joining** | `GET /projects/joinable` | 🖥️ student |
| **Join a project that is open** | `POST /projects/{id}/join` | 🖥️ student |
| Record a dated research decision and its rationale | `POST /projects/{id}/decisions` | ⚙️ |
| Create a milestone; update its scope or weight | `POST /projects/{id}/milestones`, `PATCH /milestones/{id}` | ⚙️ |
| Create a task | `POST /projects/{id}/tasks` | ⚙️ |
| Read tasks | `GET /projects/{id}/tasks` | ⚙️ |

The reads moved from 🚧 to 🖥️ without changing: `/projects` is a list screen, and a route nothing
linked to is a route nobody could open. Project titles on `/me` link to it too, so the student who
reports against a project can read it.

`PATCH /projects/{id}` carries more weight than its row suggests. A project is created `proposed`,
and `obligations_for` requires `Project.status == ACTIVE` — so creating a project and assigning a
student produces nothing until it is activated. The screen makes that a button of its own rather
than one value in a status dropdown, because everything else about the sequence looks like it
worked.

Since PROJ-07 the first half of that chain is no longer only the professor's. A student creates a
project and is on it at once, and the project is `active` rather than `proposed` — there is no
second party whose assent activation would record, and a proposed project would owe nothing. A
student may also join a project the professor has marked open to joining, which is a flag that
defaults closed: membership is the whole grant of access to a project's plan, milestones, tasks,
decisions and member list, so opening one is a disclosure decision rather than a convenience
([ADR 0017](adr/0017-students-own-their-projects.md)).

Joining part-way through a week owes from the *next* week, which is the one place the two ways of
acquiring a membership behave differently: a professor assigning someone on a Saturday means that
Saturday's week is owed, and a student joining then does not.

What is left ⚙️ is deliberate for now: milestones, decisions and a professor ending someone else's
membership are the rest of the workbench rather than the chain that makes a report due, and tasks
(PROJ-03) are a feature rather than a seam.

### 2.4 The reporting calendar (REP-01, REP-06)

| Use case | Endpoint | |
| --- | --- | --- |
| List reporting periods | `GET /periods` | 🖥️ |
| **Read the calendar in force** | `GET /calendar` | 🖥️ |
| See who owes a report this period | `GET /periods/{id}/obligations` | 🚧 |
| **Configure the reporting calendar** — timezone, week start, meeting day, grace | `PUT /calendar` | 🖥️ |
| Materialise periods up to a date | `POST /periods/ensure` | 🖥️ |
| Derive obligations for a period | `POST /periods/{id}/obligations/ensure` | 🖥️ |
| Excuse one student's obligation | `POST /obligations/{id}/excuse` | ⚙️ |
| Extend one student's deadline | `POST /obligations/{id}/extend` | ⚙️ |
| Set how long before a deadline to remind | `PUT /notifications/reminder-offsets` | ⚙️ |

The calendar panel lives on `/workspaces` rather than on a route of its own: it is a workspace
setting whose timezone default is the workspace's, and one more screen for one more form is how a
professor ends up with six places to look.

`GET /calendar` was added with it. Without it the panel could only ever render a blank form, and
the alternative signal — an empty period list — stops being true the moment a calendar is replaced
after periods already exist.

`POST /periods/ensure` and `.../obligations/ensure` are "do it now" buttons rather than the only
path: `ensure_periods` runs nightly and derives both for every workspace with a calendar. They are
there so that a professor setting a workspace up does not have to wait until tomorrow to see the
first week open.

`GET /periods/{id}/obligations` stays 🚧: `useObligations` is called from `/me` and
`/report/:periodId`, and the professor's role is turned away from both. What a professor sees of
the obligations is the outstanding list on `GET /overview` (§2.9).

The deadline is fixed by rule rather than chosen per period: 23:59 local on the day before the
weekly meeting. The calendar decides the rest. Until it is configured, every screen that needs a
current period reads "No reporting period has been configured yet", and the daily `ensure_periods`
task skips the workspace deliberately rather than inventing a schedule.

### 2.5 Reading submitted work (REP-02..05, UI-04)

| Use case | Endpoint | |
| --- | --- | --- |
| Read a weekly report | `GET /periods/{id}/report` | 🚧 |
| Read one submitted version by id | `GET /report-versions/{id}` | ⚙️ |
| Open an attachment | `GET /artifacts`, `GET /artifacts/{id}/download` | 🖥️ |
| See a student's profile and history | — (composed from the above) | 🖥️ |
| Read every stored version of one attachment | `GET /artifacts/{id}/versions` | ⚙️ |
| Request a revision of one project entry | `POST /reports/{id}/revisions` | ⚙️ |
| See outstanding revision requests | `GET /reports/{id}/revisions` | ⚙️ |
| Mark a report reviewed | `POST /reports/{id}/reviewed` | ⚙️ |

The first row is the sharpest instance of 🚧 in this document. `useReport` is consumed by
`StudentHomePage` and by `ReportEditorPage`, and by nothing else; both sit behind
`RequireAuth role="student"`. **A professor cannot read the text of a submitted report anywhere in
the app** — only its attachments, from a student's profile. The three rows that would let them
respond to one — request a revision, see the outstanding requests, mark it reviewed — are ⚙️. So
the read-and-respond loop REP-02..05 describes has no surface at either end: the professor cannot
read the report, and cannot answer it.

### 2.6 Assessment (ASSESS-01..10, UI-05)

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

### 2.7 Repository evidence (REPO-01..08)

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

### 2.8 The assistant (QA-01..07)

| Use case | Endpoint | |
| --- | --- | --- |
| Ask a cited question about the workspace's research | `POST /assistant/ask` | 🖥️ |
| Read their own past conversations | `GET /assistant/conversations` | 🖥️ |
| Watch the steps while an answer is produced | `POST /assistant/ask/stream` | ⚙️ |
| Read one conversation's turns | `GET /assistant/conversations/{id}/messages` | ⚙️ |

The export row is gone as of v0.4, and UI-06 went with it: exports were the whole of that
requirement, so retiring the feature retired the requirement rather than leaving part of it unmet.
It also took the professor's only way to get a record out of the system that is not a screen — the
assistant answers questions, it does not hand over rows.

A fact question never reaches the generation step: the obligations table says how many reports are
missing and that number is rendered rather than written. Citations are checked against what was
actually retrieved, and an invented one is dropped and the drop is stated.

### 2.9 Operations (UI-01, requirements §11)

| Use case | Endpoint | |
| --- | --- | --- |
| The current week at a glance — outstanding reports, review queue, stale repositories, stalled analyses, AI budget, failed mail | `GET /overview` | 🖥️ |
| See model spend this month | `GET /admin/ai/usage` | ⚙️ |
| See and set the monthly AI budgets | `GET`/`PUT /admin/ai/budgets` | ⚙️ |
| See repository sync health | `GET /admin/sync` | ⚙️ |

No budget configured means no limit, not a limit of zero. Since the budget can only be set through
the API, a deployment with a live model key spends without a ceiling until someone sets one by
hand.

## 3 Student

| Use case | Endpoint | |
| --- | --- | --- |
| Accept an invitation and set a password | `POST /auth/accept-invitation` | 🖥️ |
| See their week — period, deadline, what they owe | `GET /periods`, `/periods/{id}/obligations` | 🖥️ |
| Write the weekly report, a tab per required project, autosaving | `PATCH /periods/{id}/report/draft` | 🖥️ |
| Attach a file, straight from the browser to the object store | `POST /artifacts/uploads`, `/artifacts/{id}/confirm` | 🖥️ |
| Attach a link | `POST /artifacts/links` | 🖥️ |
| Submit the weekly package | `POST /periods/{id}/report/submit` | 🖥️ |
| Read their own projects, milestones, decisions and progress | `GET /projects/...` | 🖥️ |
| **Start their own project, active from the moment it exists** | `POST /projects` | 🖥️ |
| **Edit the record of a project they started** | `PATCH /projects/{id}` | 🖥️ |
| **See which projects are open to joining, and join one** | `GET /projects/joinable`, `POST /projects/{id}/join` | 🖥️ |
| **Leave a project, keeping the history** | `POST /projects/{id}/members/{membership_id}/end` | 🖥️ |
| Read every week they have been in, not only the current one | `GET /periods` | 🖥️ |
| **Read an approved assessment** | `GET /assessments`, `/assessments/{id}` | 🖥️ |
| **Read the feedback on it** | `GET /assessments/{id}/feedback` | 🖥️ |
| **See their own trajectory per project** | `GET /trends` | 🖥️ |
| **Request a correction to an assessment, with evidence** | `POST /assessments/{id}/corrections` | 🖥️ |
| Read an assessment's evidence snapshot | `GET /assessments/{id}/evidence` | ⚙️ |
| Report progress on a task | `PATCH /tasks/{id}` | ⚙️ |
| Claim a provider account as their own | `POST /developer-identities` | ⚙️ |
| See contributions attributed to them | `GET /contributions` | ⚙️ |
| Search the evidence they can see | `GET /evidence/search` | ⚙️ |

The student's surface was two screens and is now four: `/me` is the week — what is owed, when it is
due, the weeks before it, and one link onward — `/me/profile` is the trajectory and the whole
released record, and `/me/assessments/:id` is one assessment in full. The route `/me/profile` is the
one architecture.md §4.2 had named — "permitted subset at `/me/profile`" — since the table was
written. It carries the released assessments alone: `/me` listed them too until the week's screen
was cut back to the week, and with My progress off the navigation bar the link on `/me` is the only
way in.

Nothing about the API changed for the assessment half of that. Every endpoint there was already
`ScopeDep`, and `assessment/policies.py` already restricted a student to their own assessments and
only once a review had approved them. What was missing was a caller.

The project rows are a different kind of change and should not be read as the same one. Those
endpoints *were* professor-only, and AUTH-01 said so; PROJ-07 and AUTH-07 amended the requirement
and the guards moved with it. `POST /projects/{id}/members` did not: a student speaks for
themselves and for no other account, so assigning somebody is still the professor's alone, and so
is ending anybody else's membership.

`GET /assessments/{id}/evidence` stays ⚙️ **by choice, not by omission**. It would answer for a
student, but `snapshot_items` is unscoped and each item carries its own visibility; UI-02 does not
ask for the snapshot, so the student screens do not ask for it either. `MyAssessmentPage.test.tsx`
fails if a request to it is ever made.

The project row moved because `/projects` exists and because project titles on `/me` now link to
the project rather than rendering as plain text.

Submission writes an immutable version with one entry per required project; a repeated submission
carrying the same idempotency key returns the version already written. A submission survives a dead
worker by design — a failed enqueue is logged and swallowed, because report acceptance must not
wait on anything downstream.

**The student has no assistant.** That is deliberate and recorded as next-release work: the
retrieval path and the permission predicate are already shared, so it is a surface rather than a
rebuild.

**The student can no longer export.** Requirements §2 gives a student "own released records" to
export; v0.4 removed the route and the screen, and the professor's export went with it, so the
answer to *how do I keep a copy of my own work* is now that nobody does. It was the only row this
table lost, and it was lost entirely rather than reduced.

## 4 Either role

| Use case | Endpoint | |
| --- | --- | --- |
| Sign in, sign out, read own profile | `POST /auth/login`, `/auth/logout`, `GET /auth/me` | 🖥️ |
| Request and confirm a password reset | `POST /auth/password-reset`, `/password-reset/confirm` | 🖥️ |
| Update their own profile | `PATCH /users/me` | ⚙️ |

This table had seven rows in v0.3 and has three now. The five that went were the whole in-app
surface of UI-07 — reading notifications, marking them read, and muting categories — and only
that. The notification *records* are still written, the missed-deadline email still goes out under
REP-08, and `PUT /notifications/reminder-offsets` (§2.4) still configures when. What left is the
reading: a notification now exists in the database and reaches its recipient by email or not at
all.

"Critical categories cannot be muted" left with them. It was a rule enforced by a list of
unmutable kinds; it is now a property of the code, because `notify` consults nothing before it
writes and there is no suppression path to enforce anything against. The mute table was dropped
rather than left in place — an existing row would have silenced its category permanently, with no
account able to clear it.

## 5 Unauthenticated

| Use case | Endpoint | Notes |
| --- | --- | --- |
| Sign in | `POST /auth/login` | Rate limited: 10 per 5 minutes per address |
| Accept an invitation | `POST /auth/accept-invitation` | 10 per hour |
| Request a password reset | `POST /auth/password-reset` | 5 per hour; answers identically for a known and an unknown address |
| Liveness and readiness | `GET /healthz`, `/readyz` | `readyz` covers database, object storage, worker and mail relay |
| Prometheus metrics | `GET /metrics` | Bearer token required in production; blocked at the edge |
| Signed GitHub delivery | `POST /webhooks/github` | HMAC-verified; an unknown repository is accepted, recorded and reported as unmatched |

## 6 Operator

Not a role in the product: a person with a shell on the host. These exist because some actions must
not be reachable from a session, and some are needed before any account exists.

| Use case | Command |
| --- | --- |
| Create a workspace and its first professor | `app.cli identity bootstrap` |
| End every session in the **deployment** | `app.cli identity revoke-all-sessions` |
| Send the missed-deadline dispatch again after a mail misconfiguration | `app.cli notifications dispatch-missed-deadline` |
| Drain the queued email table now | `app.cli notifications send-queued-emails` |
| Load the demo dataset, or the missed-deadline drill | `app.cli seed demo`, `seed missed-deadline-drill` |
| Recover a locked-out professor | `app.cli breakglass recover-professor` |
| Transfer, demote or deactivate a professor | `app.cli breakglass transfer-professor`, `demote-professor`, `deactivate-professor` |

Two rows here are corrections to v0.2, both found while checking §2.1, and both in the same
direction: these commands are deployment-scoped, not workspace-scoped.

`revoke-all-sessions` ends every session in the deployment, not in a workspace — it writes one
audit row per workspace it touched, which is as plain a statement as the code makes that more than
one is expected. And `bootstrap` creates *a* workspace rather than *the* workspace: it refuses a
duplicate professor email and checks nothing else, so a second run makes a second workspace. Its
docstring says "run once", which is advice rather than a constraint.

Break-glass is the only route between professor accounts, and every use is audited. It refuses to
leave a workspace with no active professor (AUTH-01), which is a per-workspace rule enforced by
commands that otherwise range over the deployment — worth knowing before §2.1 adds a way to make
workspaces faster than an operator can. The demo seed creates a professor with a published password
and must never be run on a production deployment.

## 7 System

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

v0.4 changed none of these. The decision retired the reading of notifications, not their
production or their delivery: `scan_due_reminders`, `dispatch_due_reminders` and
`send_queued_emails` still run, and `backend/app/notifications/` still holds the invitation and
password-reset templates, the SMTP and console senders and the queued-email table. It has to —
enrolment is invitation-only, so that module is the only door into the system (§5). What changed is
that it is now the only way out as well.

## 8 What this inventory shows

One capability area has no screens at all — **repository evidence** (§2.7) — along with every
operations view (§2.9). Project setup (§2.3) and calendar administration (§2.4) were two more until
v0.11, and workspace management was a fourth until v0.5. §8.3 is what the v0.3 scope decision did
to the same balance.

### 8.1 Nothing can become due — *closed in v0.11*

The finding this section carried for eight versions was the one no single missing screen would
suggest. Obligations derive from project memberships; memberships require a project; creating a
project and assigning a student were both ⚙️. So on a correctly deployed system, with the calendar
configured and the worker running:

> no report is ever due, because no obligation can ever be derived, because no project can be
> created from the app.

Every link was a working, tested endpoint; the chain was broken only at the surface. v0.11 joined
it up: the calendar and the weeks it opens on `/workspaces`, creating a project on `/projects`,
activating it and assigning a student on `/projects/:id`, and deriving this week's obligations on
`/overview`. `frontend/e2e/setup-a-project.spec.ts` walks the whole of it in a browser.

One link in that chain was invisible even to this document, because it is not a missing screen but
a default. `POST /projects` writes `status = proposed`, and `obligations_for` requires
`Project.status == ACTIVE` — so a professor who created a project and assigned a student had still
produced nothing. Activation is now a button of its own with a sentence next to it, rather than one
value in a status dropdown, because everything else about the sequence looks like it worked.

The row this section is kept for: a capability inventory can tell you that every endpoint works and
still not tell you that nothing happens.

### 8.2 Built, and closed

Adding 🚧 turns up a second shape, which a count of screens hides because the screens are all
there. Four of them cannot be opened by the person the row is written for:

| Screen | Exists | Closed to | How |
| --- | --- | --- | --- |
| ~~`/projects/:id`~~ | yes, complete | ~~everyone~~ | *Closed in v0.11: `/projects` links to it, and so does a project title on `/me`* |
| `/report/:periodId` | yes, complete | the professor | The student guard redirects them home (§2.5) |
| `/me` period and obligations | yes, complete | the professor | Same guard; `GET /overview` answers part of it (§2.4) |
| ~~`/review/:assessmentId`, `/students/:id`~~ | yes, complete | ~~the student~~ | *Closed in v0.11: `/me/assessments/:id` renders the released assessment for the student it is about* |

The fourth row closed a loop the rest of the system opens, and it is worth recording what it cost
to leave open. An assessment is drafted by the pipeline, held back until the professor approves it,
and approving it is one of the few professor actions that is 🖥️ — while the student it was approved
for had no screen on which to read it. The approve button's own stamp said "Published to the
student"; there was no student side of that sentence.

Nothing in the API had to change to close it. Every endpoint involved was already `ScopeDep`, and
`assessment/policies.py` already restricted a student to their own assessments and only once a
review had approved them. What was missing was a caller — which is exactly the distinction the ⚙️
and 🚧 marks exist to make.

The assistant makes this worse rather than working around it. It is professor-only, and the fact
layer builds a locator for every citation it returns, which `CitationLink` renders as a `Link`.
Six locator shapes exist; three of them go nowhere:

| Locator | Built in | What a professor gets |
| --- | --- | --- |
| `/review/{assessment_id}` | `assistant/facts/scores.py` | The review screen |
| `/students/{id}#notes` | `assistant/retrieval.py` | The student's profile |
| `/projects/{id}` | `assistant/facts/members.py` | The project screen — the one inbound link it has |
| `/report/{period_id}` | `assistant/facts/obligations.py`, `facts/reports.py` | The student guard: `/overview` |
| `/projects?repository={id}` | `assistant/facts/sources.py` | Not a route: `/overview` |
| `/artifacts/{id}` | `evidence/service.py` | Not a route: `/overview` |

They go nowhere quietly, for the reason §1 gives: the guard and the catch-all both redirect, so the
professor lands on their own overview with nothing to say that the citation did not open. QA-03
asks that a citation open an authorized record. The record is authorized, the API would serve it,
and the answer that cited it was right. What is missing is a route.

The worst of the six is the one that matters most. A claim about what a student did this week is
cited to a report entry — `/report/{period_id}#{project_id}` — and that entry is precisely what a
professor cannot read anywhere in the app (§2.5). The assistant can quote the report in its answer;
it cannot show it.

### 8.3 What the scope change cost

v0.3 predicted two consequences and v0.4 shipped them, so they are now description rather than
forecast. Neither was a reason not to do it; both are things a reader of the code alone would have
to reconstruct.

**Email is the only channel.** Notification records are still written and the missed-deadline mail
still goes out (§7), and nothing in the app displays either. A student who does not read their
email has no way to learn that a deadline moved, a revision was requested, or an assessment was
released — and §8.2 says they cannot read the assessment in the app even if they hear about it. The
overview's mail warning, which exists because an invitation that never sent is an enrolment that
did not happen, is now the professor's only sight of a channel that carries everything.

**The student's surface halved.** Behind the sign-in pages a student had four screens and now has
two, both part of the weekly submission flow. The product a student sees is exactly one loop —
write the report, submit it — with no screen that shows them anything coming back. Read against
§8.2 that is the sharper form of the same finding: of the four, `/notifications` and `/exports`
were the two that carried anything *out* of the system to the student, and they are the two that
went.

One thing v0.3 did not predict turned up while removing the code. The mute preferences table had
to be dropped, not merely orphaned: with the unmute route gone, an existing row would have silenced
its category for good with no account able to clear it. A feature removal that leaves its storage
behind is not smaller than one that does not — it is the same removal with a trap in it.

§2.1 pulled the other way and is now built, deliberately with its screens rather than after them:
on the evidence of §8.1, shipping workspace management as five ⚙️ routes would have reproduced the
exact failure this document exists to name, one layer higher up.

Its last row is worth reading even by someone who will never create a workspace. "Move a
student to another workspace" looked like an ordinary missing feature and is a schema-level
refusal: eight tables carry a composite foreign key onto `users(workspace_id, id)`, none cascades
on update, and enrolment is invitation-only, so every account has a row pinning it from the moment
it exists. A workspace is not an attribute of a user; it is part of their identity. That was not
visible from any route inventory, any screen, or any requirement — only from trying it, which is
the argument for this document being compiled from the code rather than written beside it.

### 8.4 What opening a project costs

PROJ-07 let a student join a project without being assigned to it. The code change is small; what
it moves is not, and the reason is that **a membership is the entire grant of access to a project**.
`_in_scope` is `same_workspace AND project_id IN scope.project_ids`, with no second gate and no
status test, so inserting the row is the whole decision.

A student who joins an open project can therefore read, for that project: the record, its
milestones with their retained baselines and the professor's reasons for moving a target, its tasks
— including the free-text `blocker` and `completion_reason` another student wrote about their own
work — its dated decisions and rationales, its repositories and their sync errors, its shared
evidence, and the member list including past members. That last one matters more than it looks:
`user_visible_to` restricts a student to their own account, and `MembershipOut.student_name` is the
only route by which one student learns another's name. Joining every open project in turn is how a
roster gets enumerated.

What it does *not* reach was checked policy by policy and is the more important half. Reports,
report versions, attachments, obligations, assessments, reviews, feedback, corrections, supervision
notes, evidence snapshots and plan baselines are keyed to a `student_id`, never to a `project_id`.
Joining a project tells you what the work is. It tells you nothing about how anyone on it is doing.

Two mitigations, and one deliberate refusal. The flag: `open_to_join` defaults closed and is the
professor's per project, so nothing became joinable when this shipped and the exposure is bounded
by decisions somebody took. The projection: `GET /projects/joinable` serves title, stage, status
and a member count, and not the research questions — though since joining is unilateral and
instant, that is about keeping a directory a directory rather than about confidentiality. The
refusal: a student leaving still advances the workspace-wide access epoch, which discards every
cached assistant answer in it. Not bumping was considered and rejected — the leaver's own cached
answers were computed with access they no longer hold — so the cost is carried by a rate limit on
the route instead.

### 8.5 The shape

§8.1 and §8.2 are the failure shape [implementation_status.md](implementation_status.md) §1 names
twice — *"a step marked Done means its module is done, and the question worth asking separately is
what calls it"* — appearing again, one layer up. The earlier instances were missing seams between
modules. §8.1 is a missing seam between the product and the people who use it, and §8.2 is the same
seam inside the product: a screen is a module too, and what calls it is still the separate
question.

## 9 Keeping this document true

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
misses most of the app — it reports 14 where the answer is 33.

Those two commands settle 🖥️ against ⚙️. They cannot see 🚧, because an endpoint a screen calls
looks identical whether or not anyone can reach that screen. Two more are needed, and they are the
ones that found §8.2:

```bash
# every inbound link. A route defined in router.tsx and absent here is orphaned.
grep -rnE '(to=\{?["`]/|navigate\(["`]/)' frontend/src --include=*.tsx | grep -v '\.test\.'

# every locator the API hands the citation renderer, each of which becomes a <Link>. Any path
# here that router.tsx does not define, or defines behind a guard the assistant's caller fails,
# is a citation that redirects instead of opening.
grep -rnE 'locator=f?"' backend/app --include=*.py | grep -v test
```

Both are read against `frontend/src/app/router.tsx`: the first for routes it defines that nothing
reaches, the second for paths it does not define at all, or defines behind a guard the assistant's
own caller fails. A screen with no inbound link and a locator with no route are the two ways this
document goes quietly wrong.

None of the four commands can see ✂️ or ◻️, and no command can: those rows record a decision, and
a decision leaves no trace in the code until someone acts on it. They are checked against
[research_management_requirements.md](research_management_requirements.md) instead, and they are
meant to be temporary. A ✂️ row is deleted in the pull request that removes the code — deleting it
earlier makes this document disagree with a running deployment. A ◻️ row becomes ⚙️ or 🖥️ in the
pull request that builds it. A ◻️ row that has been here for several versions is telling you
something, and it is not that the table needs updating.

Update this file in the pull request that changes what it describes, as with
[implementation_status.md](implementation_status.md).
