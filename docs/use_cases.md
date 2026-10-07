# Use cases

Version 0.21 — 7 October 2026 — companion to [research_management_requirements.md](research_management_requirements.md) v0.13, [architecture.md](architecture.md), and [implementation_status.md](implementation_status.md)

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
made belonging plural (ADR 0015). **v0.10 changed what a professor sees**: reads spanned every
workspace they belong to (ADR 0016). That was reversed by ADR 0020: a professor now sees the
workspace the header switcher names, and switching changes every screen. §2.1 has the split that
made all of it possible.

**v0.11 is the one that changes what can happen at all.** It closes the two findings this document
has been carrying: §8.1, that no report could ever become due because no project could be created
from the app, and the last row of §8.2, that an assessment approved for a student had no screen on
which that student could read it. Neither needed a new capability — every endpoint involved already
worked and was already tested. What both needed was a caller.

**v0.17 takes things off the Workspaces screen.** Saving the weekly schedule now opens the weeks and
makes this week's reports due, so the "open weeks" step is gone (§2.4); the screen leads with the
workspace being worked in, its name and its schedule; and model spend has no screen, though its
endpoints and the gateway's ceiling are unchanged (§2.9).

**v0.18 takes away what no screen used.** Tasks, dated research decisions, pre-deadline reminder
offsets and student correction requests are removed with their endpoints and tables (requirements
0.10, migration 0027): each was built, had no screen that wrote it or none that read it, and held no
rows. So is the baseline proposal flow, which had no route at all. The rows below that named them
are gone (§2.3, §2.4, §2.6, §3).

**v0.19 takes away the repository connector** (requirements 0.11, ADR 0022, migration 0028). It was
built for GitHub and never connected to a repository: its seven tables held no rows. §2.7 keeps only
the evidence search and the citation-open reference, which moved to `api/v1/evidence.py`;
`/admin/sync`, the overview's sync section, the student's identity and contribution rows, the
webhook and `incremental_sync` are gone. A project still records its repository as a link.

**v0.20 takes away the research assistant** (requirements 0.12, ADR 0023, migration 0029). It was
built in full and never used: conversations, messages, the answer cache and supervision notes held
no rows. `/assistant` and its routes are gone (§2.8), and so are the evidence search and
citation-open routes that served it (§2.7), the private supervision note (§2.6), and the workspace
access epoch that expired the cache. The overview computes the same numbers directly. The
notification records nothing read — report submitted and resubmitted, and the professor's in-app
summary of a missed deadline — are no longer written; the professor sees who is outstanding on the
overview.

**v0.21 removes embeddings** (requirements 0.13, ADR 0024, migration 0030). Every indexed chunk was
embedded and nothing read the vectors after v0.20. No route or screen changes: indexing still
happens when a report is submitted or an attachment is read, and is now chunking alone, with no
call to a model provider.

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

v0.4 removed ten endpoints — seven notification routes and three export routes — and v0.5 to v0.9
added nine for workspaces and moving a student, every one of them behind a screen. The milestone
and progress endpoints went with the feature in requirements 0.8 (migration 0026), and tasks,
decisions, reminder offsets and correction requests in 0.10 (migration 0027): a capability nothing
calls is either given a screen or given up, which is what ⚙️ is *for*.

The second number is not the whole answer even so, because reachability is per role:
`GET /periods/{id}/report` is 🖥️ for the student who writes the report and 🚧 for the professor who
is meant to read it.

## 1 The screens

Fifteen routes and one shell, in `frontend/src/app/router.tsx`. The guard is the route's own; the
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
| `/me/assessments/:id` | student | a row on `/me` or `/me/profile` | One released assessment: its week, ratings and rationales |
| `/report/:periodId` | student | the button on `/me` | A tab per required project, autosaving; attachments, which are files (REP-04); submit |
| `/overview` | professor | nav, and the professor's home | Budget and mail warnings, this week's reports by workspace, project and student, outstanding reports, review queue, stalled analyses |
| `/people` | professor | nav | Everyone in the workspace they are working in (ADR 0020); invite, move, suspend / restore / remove |
| `/workspaces` | professor | nav | The workspace being worked in first — its name (rename, for its owner) and its weekly schedule, shown as a sentence and the coming weeks' deadlines. Then the other workspaces they belong to (join, leave, archive with a confirmation), and creating one, folded. *Switching* between them is the workspace name in the header, on every screen (§2.1) |
| `/projects` | signed in | nav (both roles since PROJ-07; a student's bar is their week, then this); a project title on `/me` | Every project the caller may see; create one. For a student, the projects a professor has opened to joining, and a Join on each |
| `/students/:id` | professor | a name on `/people`, or on the overview's outstanding list | Approved assessments, trajectory per project, downloadable materials |
| `/review/:assessmentId` | professor | the overview's review queue, or a student's profile | Ratings per dimension, confidence, the evidence snapshot, approve with a rationale |
| `/projects/:id` | signed in | the list at `/projects`, a title on `/me`, a member row | Research questions, members, the project's related documents; the stage and the milestones to a professor only. Activate the project, open it to joining, assign a student, end a membership (professor); attach a document (anyone on it); edit the record (its creator) |

v0.4 removed two rows, `/notifications` and `/exports`, and they were the two either role could
open; v0.5 added `/workspaces`, and v0.20 removed `/assistant`. What is left is a professor's five and a student's two, meeting
nowhere but the sign-in pages and `/projects/:id` — which nothing links to, so in practice they do
not meet at all.

(v0.2 and v0.3 counted fourteen rows here as "thirteen routes". The table was right and the
sentence was not; the counts here have been correct since v0.4.)

The navigation offers four items to a professor and two to a student, and mirrors the guard
exactly: a page the caller cannot load is never linked, because a link that always fails is worse
than no link. `/` and anything unrecognised go to the home for the role — `/overview` for a
professor, `/me` for a student.

That last rule has an edge the navigation cannot show. Both the guard and the catch-all *redirect*
rather than refuse, so a person who follows a link into a page their role cannot open does not see
a refusal: they arrive at their own home. The redirect now carries the path it turned them away
from, and the shell says so above the page — *"/overview is not a page your account can open, so
this is your own home instead"* — because without it the click was simply swallowed. One link
inside the app does this in normal use: the member names on `/projects/:id` point at
`/students/:id`, which is professor-only, from a screen either role may open. §8.2 is where it
happens.

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
| Join a workspace, or switch to one already joined | `POST /workspaces/{id}/join` | 🖥️ — switching is the workspace name in the header, on every screen; joining one not yet belonged to is here |
| Leave a workspace, keeping the others | `POST /workspaces/{id}/leave` | 🖥️ |
| See everyone across the workspaces they belong to | `GET /users` | 🖥️ (§2.2) |
| Archive a workspace nobody is in | `POST /workspaces/{id}/archive` | 🖥️ |
| Remove a student from a workspace | `POST /users/{id}/remove` | 🖥️ (§2.2) |
| Move a student to another workspace, before they start | `POST /users/{id}/workspace` | 🖥️ (§2.2) |

**Switching is in the header, not on this screen.** The workspace name every screen carries is a
menu of the memberships this professor holds, and choosing one moves the anchor and lands on the
overview — switching is joining a workspace already belonged to (ADR 0015), so it is the same
call. The overview rather than wherever you were, because a record page names a record of the
workspace you just left and staying put would turn a switch into a redirect. It moved because it is
not administration: it is the frame the roll and the overview are read in, and
changing it meant leaving the screen that had prompted the question. What stays here is what
changes the set you can switch between — join, leave, archive — plus create, rename, the calendar
and the budget. A professor with one membership sees the name without a menu.

A student belongs to exactly one workspace and the invitation names it (§2.2), so they have one
from the moment they are enrolled and never have none. `POST /users/invitations` now carries
`workspace_id`; omitting it means the caller's own, which is what the caller's Scope always
supplied implicitly.

Three rules follow from the tenant boundary rather than from taste, and ADR 0012 has the reasoning:
a workspace is **created empty**, because its creator already belongs to theirs and a user belongs
to one; it is **archived, never deleted**, because every foreign key into a workspace cascades and
a delete would take the history with it; and archiving **refuses while any account is still
active**, so the flag never has to be enforced further down.

**Reads and writes both follow the workspace you are working in** (ADR 0020, ADR 0021).
`Scope.workspace_id` is where a write lands and the only workspace a read sees. The comparison lives
in `Scope.within`, one function that all thirty-three visibility predicates call — widening what a
read may see is the most consequential change anyone can make here, and it should be visible in one
diff rather than spread across seven `policies.py` files.

That is why "working here" is the frame every screen is read in: switching workspace in the header
changes which projects, students, reports and evidence a professor sees, as well as where new
things land.

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

`users.workspace_id` is the parent of a composite foreign key on six tables (eight until v0.19), and
v0.7 split them in two (ADR 0014):

| | Tables | On update |
| --- | --- | --- |
| Identity — belongs to the person | `invitations`, `sessions`, `password_resets`, `notifications` | **cascade**, so they follow the account |
| History — belongs to the work | `project_memberships`, `weekly_reports` (and, until ADR 0022 dropped them, `developer_identities`, `contributions`) | **refuse**, so the account cannot leave them |

A professor has only identity rows, so they move. A student who has submitted anything has history
rows, so Postgres refuses — and *that* is now what "history stays in the workspace it was written
in" means. It is not a route that was never written; it is two constraints that say no.

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
| **Send an invitation again** | `POST /users/invitations` | 🖥️ — a button on any row still `invited`, either role |
| See everyone in the workspace | `GET /users` | 🖥️ |
| Read one user's record directly | `GET /users/{id}` | 🖥️ |
| Suspend an account's access | `POST /users/{id}/deactivate` | 🖥️ |
| Reactivate an account | `POST /users/{id}/reactivate` | 🖥️ |
| Remove a student from the workspace | `POST /users/{id}/remove` | 🖥️ |

**Resending was always possible and never offered.** `invite_user` has reissued rather than
refused for an address still in `invited` since ADR 0011 — it revokes the pending link and mails a
new one, and the role travels on the user row so a re-invitation may also change it. The only way
to reach that branch was to retype the address into the invite form and know what would happen, so
the screen now carries a button on every unaccepted row, professors' included: a colleague who
never received their invitation was previously unreachable from this screen, because an accepted
professor correctly has no controls on them (ADR 0011) and the two cases shared a row.

What reissuing costs is stated once, in the note under the invite form rather than in each row:
the earlier link stops working the moment a new one is issued, which matters to whoever is reading
an older email.

Enrolment is invitation-only and there is no self-registration, so the invitation email is the only
door into the system. Deactivation, role change and password reset each revoke every session in
the same transaction. (Until v0.20 they also advanced the workspace access epoch, which expired the
assistant's answer cache; both went in ADR 0023.)

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
| Read a project and its members | `GET /projects`, `/projects/{id}`, `/{id}/members` | 🖥️ |
| **Create a project** | `POST /projects` | 🖥️ both roles |
| **Update a project** — title, research questions, stage, status | `PATCH /projects/{id}` | 🖥️ — a professor sets any field; the creator sets the record but not its standing |
| **Assign a student to a project** | `POST /projects/{id}/members` | 🖥️ |
| End a membership, keeping its history | `POST /projects/{id}/members/{membership_id}/end` | 🖥️ professor only, on the member row ([ADR 0019](adr/0019-ending-a-membership-is-the-professors.md)) |
| **List the projects open to joining** | `GET /projects/joinable` | 🖥️ student |
| **Join a project that is open** | `POST /projects/{id}/join` | 🖥️ student |
| **Attach a document to a project, read the project's documents, remove one you attached** | `POST /artifacts/uploads`, `GET /artifacts?project_id=`, `DELETE /artifacts/{id}` | 🖥️ both roles — on the project page, and on the create form |

**A student no longer leaves a project, and a finished project owes no week**
([ADR 0019](adr/0019-ending-a-membership-is-the-professors.md)). The "Done this project" button is
gone and `end_membership` refuses a student outright: whether research is finished is the judgement
the weekly meeting exists to make, and a student who has stopped owing a report is a student the
professor is no longer told about. The professor gains the control on the member row, and the
usual way to end a project is its status — setting it out of `active` now takes the week off
everyone on it, including the week in progress, which it did not do before. PROJ-07, AUTH-01 and
REP-06 were amended to match in requirements v0.7, so the specification and the product agree
rather than the ADR standing against both.

A student's project view also drops the **stage**: it is the professor's plan for the project
rather than the student's account of it. It is still on the project list and on the create form,
because the API requires one when a project is started.

**A project's related documents are new** ([ADR 0018](adr/0018-project-documents-are-shared-with-the-project.md)).
PROJ-01 has listed "shared resources" among a project's fields since v0.1 and nothing ever wrote
one: a student with a protocol or a dataset description had a weekly report, where it became that
week's private evidence, or a corridor. The artifacts table already carried a nullable
`period_id`, so the file that has none is the project's, and the visibility predicate gained the
one branch that says so — everyone on the project reads it, whoever attached it may remove it, and
a professor reads every one and removes none. The create form takes them too, and attaches them
once the project exists, since there is nothing to attach them to before that. They are not
extracted and not indexed: a project document cannot be cited by an assessment, which is a separate decision about what the model may read.

**Milestones, decisions and tasks are gone from the product.** All three started the same way, and
it is the thing this inventory exists to catch: nothing wrote what they showed. Milestone
completion was weights against a column only an uncalled endpoint set, so every project read 0%;
requirements 0.8 withdrew it and migration 0026 dropped the tables. Decisions had a panel that said
"No decisions recorded" because `POST /{id}/decisions` had no caller, and tasks had no screen at all;
requirements 0.10 withdrew both and migration 0027 dropped the tables.

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
defaults closed: membership is the whole grant of access to a project's record, documents
and member list, so opening one is a disclosure decision rather than a convenience
([ADR 0017](adr/0017-students-own-their-projects.md)).

Joining part-way through a week owes from the *next* week, which is the one place the two ways of
acquiring a membership behave differently: a professor assigning someone on a Saturday means that
Saturday's week is owed, and a student joining then does not.

Nothing in this section is left ⚙️.

### 2.4 The reporting calendar (REP-01, REP-06)

| Use case | Endpoint | |
| --- | --- | --- |
| List reporting periods | `GET /periods` | 🖥️ |
| **Read the calendar in force** | `GET /calendar` | 🖥️ |
| **See who owes a report this period, and who has reported** | `GET /periods/{id}/obligations` | 🖥️ — via the week's board on `GET /overview` |
| **Configure the reporting calendar** — timezone, week start, meeting day, grace | `PUT /calendar` | 🖥️ |
| Materialise periods up to a date | `POST /periods/ensure` | ⚙️ — saving the calendar does it, and so does the nightly job |
| Derive obligations for a period | `POST /periods/{id}/obligations/ensure` | 🖥️ |
| Excuse one student's obligation | `POST /obligations/{id}/excuse` | ⚙️ |
| Extend one student's deadline | `POST /obligations/{id}/extend` | ⚙️ |

The calendar panel lives on `/workspaces` rather than on a route of its own: it is a workspace
setting whose timezone default is the workspace's, and one more screen for one more form is how a
professor ends up with six places to look.

`GET /calendar` was added with it. Without it the panel could only ever render a blank form, and
the alternative signal — an empty period list — stops being true the moment a calendar is replaced
after periods already exist.

**Saving the calendar opens the weeks and makes this week's reports due** (v0.17). It used to be
followed by two more steps a professor had no reason to know about — "open weeks" on the calendar
panel, then "derive" on the overview — and a workspace with five active projects stayed empty
until the nightly job ran. `PUT /calendar` now opens the next eight weeks, re-dates the ones not
yet begun to the new version (the week under way keeps its deadline, REP-01), and derives the
current week's obligations. `POST /periods/ensure` stays for the nightly job and scripts; the
overview's derive button stays as a "do it now". The first week is still the first week start on
or after `effective_from`, which the screen asks as "this week or next".

`GET /periods/{id}/obligations` was 🚧 and is not any more, though the route itself is still one a
professor never calls directly: `useObligations` is called from `/me` and `/report/:periodId`, and
the professor's role is turned away from both. The obligations reach them through the week's board
on `GET /overview` (§2.9), which reads the same table through the same service function.

That board is what replaced "the outstanding list" as the answer to *what is happening this week*.
Outstanding is the same obligations read for one of their three states, and it is the state a
supervisor can do least with: a student who has reported never appears in it, nor does a project
where everyone has, so the screen said nothing about the week that was actually going well. The
board carries all three states — submitted, owed, excused — one row per obligation, grouped by
workspace and then by project, with names rather than the first eight characters of a uuid.

It is grouped by workspace because a professor's reads were built to span every workspace they
belong to (ADR 0016) and each keeps its own reporting calendar; since ADR 0020 and ADR 0021 a read
covers only the one being worked in, so the board shows a single group. There is therefore no single "this week" for
them: `GET /overview` still carries one `current_period` for the header, and the board computes one
period per workspace. `PeriodOut` gained `workspace_id` for exactly this — without it the periods
came back in one list with nothing to group them by.

The deadline is fixed by rule rather than chosen per period: 23:59 local on the day before the
weekly meeting. The calendar decides the rest. Until it is configured, every screen that needs a
current period reads "No reporting period has been configured yet", and the daily `ensure_periods`
task skips the workspace deliberately rather than inventing a schedule.

### 2.5 Reading submitted work (REP-02..05, UI-04)

| Use case | Endpoint | |
| --- | --- | --- |
| Read a weekly report | `GET /periods/{id}/report` | 🖥️ |
| Read one submitted version by id | `GET /report-versions/{id}` | 🖥️ |
| Read every submitted version of one report | `GET /reports/{id}/versions` | 🖥️ |
| Open an attachment | `GET /artifacts`, `GET /artifacts/{id}/download` | 🖥️ |
| See a student's profile and history | — (composed from the above) | 🖥️ |
| Read every stored version of one attachment | `GET /artifacts/{id}/versions` | ⚙️ |
| Request a revision of one project entry | `POST /reports/{id}/revisions` | 🖥️ |
| See outstanding revision requests | `GET /reports/{id}/revisions` | 🖥️ |
| Mark a report reviewed | `POST /reports/{id}/reviewed` | 🖥️ |

This section used to record the sharpest 🚧 in the document: `useReport` was consumed only by
`StudentHomePage` and `ReportEditorPage`, both behind `RequireAuth role="student"`, so **a
professor could not read the text of a submitted report anywhere in the app** — only its
attachments — and the three rows that would let them respond were ⚙️. The read-and-respond loop
REP-02..05 describes had no surface at either end.

`ReportReaderPage` is that surface, at `/students/:studentId/reports/:periodId` for a professor
and `/report/:periodId/submitted` for the student whose week it is. It reads
`version.entries` rather than the obligations, which is what makes an entry for a project the
student has **left** visible: `submit_report` carries such an entry into every new version, and
the editor's tabs — derived from the obligations — could never show one. `GET /reports/{id}/versions`
was added for it, because until then a version was reachable only by id and the only id anyone held
was `current_version_id`, so REP-05's "a resubmission adds a version and never replaces history"
had no reader.

It never renders `draft_content`, though `ReportOut` carries it and the policy permits a professor
to read it. An unsubmitted draft is not a submission, and showing it would make autosave
surveillance.

### 2.6 Assessment (ASSESS-01..10, UI-05)

| Use case | Endpoint | |
| --- | --- | --- |
| Read a draft assessment and the evidence snapshot it was made from | `GET /assessments/{id}`, `/{id}/evidence` | 🖥️ |
| Approve and publish an assessment | `POST /assessments/{id}/approve` | 🖥️ |
| See a student's trajectory on one project | `GET /trends` | 🖥️ |
| Withdraw a published assessment | `POST /assessments/{id}/withdraw` | ⚙️ |
| Re-run one assessment pipeline | `POST /admin/assessments/retry` | 🖥️ |

Drafts are the professor's to approve; nothing reaches a student unapproved. An override requires a
recorded reason and keeps the model's own output beside it. Until v0.20 a professor could also
record a private supervision note, through an endpoint no screen called; the assistant was its only
reader, and both were withdrawn (ADR 0023).

### 2.7 Evidence

No route. What is indexed — report entries and attachments — is read by the assessment pipeline
when it builds a snapshot (§2.6), and by nothing a person calls.

Until v0.19 this section was the repository connector (REPO-01..08): connect a repository, link it
to a project, read and trigger its sync, confirm developer identities, list attributed
contributions. None of it had a screen, and none of it was ever used; it was removed with its
tables (ADR 0022). v0.19 left two ⚙️ routes here, searching the evidence index and opening one
citable reference; both existed for the assistant and went with it in v0.20 (ADR 0023).
The embeddings computed at index time, which nothing read after that, were removed in v0.21 (ADR
0024).

### 2.8 The assistant — *withdrawn in v0.20*

Requirements 0.12 withdrew QA-01..07 (ADR 0023, migration 0029). Until then this section was asking
a cited question about the workspace's research (`/assistant`, 🖥️), reading past conversations,
watching an answer stream, and reading one conversation's turns. It was built in full and never
used: the conversations, messages and answer-cache tables were empty on the running deployment. The
overview borrowed its fact functions for the week's numbers; those now live in `app.overview` and
return the same counts.

The export row is gone as of v0.4, and UI-06 went with it: exports were the whole of that
requirement, so retiring the feature retired the requirement rather than leaving part of it unmet.
It also took the professor's only way to get a record out of the system that is not a screen.

### 2.9 Operations (UI-01, requirements §11)

| Use case | Endpoint | |
| --- | --- | --- |
| The current week at a glance — **this week's reports by workspace, project and student**, outstanding reports, review queue, stalled analyses, AI budget, failed mail | `GET /overview` | 🖥️ |
| See model spend this month | `GET /admin/ai/usage` | ⚙️ — no screen since v0.17 |
| See and set the monthly AI budgets | `GET`/`PUT /admin/ai/budgets` | ⚙️ — no screen since v0.17; with none set nothing is capped |

The week's board is the section a professor opens this screen for, and §2.4 has why it replaced the
outstanding list as the answer to *what is happening this week*. Both are still here: the board is
the week in all three of its states, and outstanding is the count of one of them with the instant it
was true attached, which is what REP-08 asks for.

No budget configured means no limit, not a limit of zero — an empty field and a zero are different
settings, and the panel on `/workspaces` says so, because a zero stops every analysis. Until that
panel existed the budget could only be set through the API, so a deployment with a live model key
spent without a ceiling until someone reached for curl.

The spend beside it is the month's real total whether or not a ceiling is set. `check_budget` runs
before every model call and only totals spend when there is a limit to compare it against, which
is right for that path and wrong for this one: reading its figure regardless meant the overview
reported **$0 spent** in exactly the case where nothing was capping the bill.

## 3 Student

| Use case | Endpoint | |
| --- | --- | --- |
| Accept an invitation and set a password | `POST /auth/accept-invitation` | 🖥️ |
| See their week — period, deadline, what they owe | `GET /periods`, `/periods/{id}/obligations` | 🖥️ |
| Write the weekly report, a tab per required project, autosaving | `PATCH /periods/{id}/report/draft` | 🖥️ |
| Attach a file, straight from the browser to the object store | `POST /artifacts/uploads`, `/artifacts/{id}/confirm` | 🖥️ |
| **Remove a file they attached** | `DELETE /artifacts/{id}` | 🖥️ |
| Submit the weekly package | `POST /periods/{id}/report/submit` | 🖥️ |
| **Read the week they submitted, every version of it, and any revision asked for** | `GET /periods/{id}/report`, `/reports/{id}/versions`, `/report-versions/{id}`, `/reports/{id}/revisions` | 🖥️ |
| Read their own projects and the documents on them | `GET /projects/...`, `GET /artifacts?project_id=` | 🖥️ |
| **Start their own project, active from the moment it exists** | `POST /projects` | 🖥️ |
| **Edit the record of a project they started** | `PATCH /projects/{id}` | 🖥️ |
| **See which projects are open to joining, and join one** | `GET /projects/joinable`, `POST /projects/{id}/join` | 🖥️ |
| Read every week they have been in, not only the current one | `GET /periods` | 🖥️ |
| **Read an approved assessment** | `GET /assessments`, `/assessments/{id}` | 🖥️ |
| **See their own trajectory per project** | `GET /trends` | 🖥️ |
| Read an assessment's evidence snapshot | `GET /assessments/{id}/evidence` | ⚙️ |

The student's surface was two screens and is now five: `/me` is the week — what is owed, when it is
due, the weeks before it, and one link onward — `/report/:periodId` is the editor, and
`/report/:periodId/submitted` is what they actually sent, which is not the same thing and never
was. `/me/profile` is the trajectory and the whole released record, and `/me/assessments/:id` is
one assessment in full. The route `/me/profile` is the one architecture.md §4.2 had named —
"permitted subset at `/me/profile`" — since the table was written. It carries the released
assessments alone: `/me` listed them too until the week's screen was cut back to the week, and with
My progress off the navigation bar the link on `/me` is the only way in.

The editor and the reader are separate screens on purpose. The editor renders the autosaved draft,
which is the thing being edited; the reader renders the submitted version, which is the thing on
the record. Where the two disagree — and they can, because a draft outlives the submission it was
typed over — showing one in place of the other would misstate which is which. The reader is also
the only screen in the product that can show an entry for a project the student has since left:
those entries are carried into every new version, and the editor's tabs come from the obligations,
which no longer include that project.

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
that. The missed-deadline email still goes out under REP-08, and its record is the only
notification still written: the reminder offsets that once configured pre-deadline records went in
v0.18, and the report submitted and resubmitted records and the professor's in-app summary of a
missed deadline stopped in v0.20, because nothing read them (ADR 0023). The professor learns who is
outstanding from the overview (§2.9), not from a notification.

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
| `scan_due_reminders` | 5 min | Finds weeks whose deadline has passed and queues the missed-deadline email |
| `send_queued_emails` | 2 min | Drains the email delivery table |
| `queue_health` | 5 min | Warns when the oldest queued job is over ten minutes old; its runs are the worker heartbeat `/readyz` reads |
| `retention_sweep` | nightly | Deletes queue jobs finished over seven days ago (until v0.20 it also expired the assistant's answer cache) |

Both calendar tasks are idempotent by construction, so a worker that was down for a day catches up
rather than skipping a week.

v0.4 changed none of these. The decision retired the reading of notifications, not their
production or their delivery: `scan_due_reminders` and `send_queued_emails` still run, and `backend/app/notifications/` still holds the invitation and
password-reset templates, the SMTP and console senders and the queued-email table. It has to —
enrolment is invitation-only, so that module is the only door into the system (§5). What changed is
that it is now the only way out as well.

## 8 What this inventory shows

Repository evidence (§2.7) was the one capability area with no screens at all; it went in v0.19
with the connector rather than gaining one, and the two ⚙️ evidence routes it left went with the
assistant in v0.20. Operations
(§2.9) was another until v0.13, when model spend, the budget that caps it and the retry on a
stalled analysis each got one. Project setup (§2.3) and calendar administration (§2.4) were two more until v0.11, and workspace management was a
fourth until v0.5. §8.3 is what the v0.3 scope decision did to the same balance.

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
`/overview`.

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
| `/report/:periodId` | yes, complete | the professor | The student guard redirects them home; the professor reads the week at `/students/:studentId/reports/:periodId` (§2.5) |
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

The assistant made this worse rather than working around it, until v0.20 withdrew it (ADR 0023).
It was professor-only, and its fact layer built a locator for every citation it returned, which
`CitationLink` rendered as a link. Several of those locators named routes that do not exist or that
the professor's guard turns away, so a citation redirected to `/overview` instead of opening —
including the one that mattered most, a report entry cited to the student's `/report/{period_id}`
after the professor's reader at `/students/:studentId/reports/:periodId` existed. The record was
authorized and the answer was right; what was missing was a route.

### 8.3 What the scope change cost

v0.3 predicted two consequences and v0.4 shipped them, so they are now description rather than
forecast. Neither was a reason not to do it; both are things a reader of the code alone would have
to reconstruct.

**Email is the only channel that *announces* anything.** The missed-deadline mail still goes out
(§7) and its record is still written, and nothing in the app displays either, so a student
who does not read their email still has no way to learn that something has happened.

What has changed since v0.3 is what they find when they do look. An assessment released to them is
readable at `/me/assessments/{id}`, and since v0.13 a revision request is readable too — the reason
the professor typed is on the report they submitted, where it is about something, rather than only
in a message about it. The gap is now between *being told* and *being able to find out*, which is
a narrower and more ordinary gap than the one this paragraph used to describe. The overview's mail
warning, which exists because an invitation that never sent is an enrolment that did not happen,
remains the professor's only sight of the channel.

**The student's surface halved, and has since grown back past where it started.** Behind the
sign-in pages a student had four screens; v0.4 left two, both part of the weekly submission flow,
so the product a student saw was exactly one loop — write the report, submit it — with no screen
that showed them anything coming back. Of the four, `/notifications` and `/exports` were the two
that carried anything *out* of the system to the student, and they were the two that went.

There are now five student screens plus the two project screens they share with the professor, and
three of the five carry something back: their own progress, an assessment released to them, and
the week they submitted with whatever the professor asked them to change. The v0.3 decision cost
what it was predicted to cost; what closed it was not reversing the decision but building the
return path deliberately, one screen at a time, which is the argument §8.1 makes about ⚙️ routes
from the other direction.

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

A student who joins an open project can therefore read, for that project: the record, its shared
evidence, **the documents anyone on it has attached** ([ADR 0018](adr/0018-project-documents-are-shared-with-the-project.md)),
and the member list including past members. That last one matters more than it looks:
`user_visible_to` restricts a student to their own account, and `MembershipOut.student_name` is the
only route by which one student learns another's name. Joining every open project in turn is how a
roster gets enumerated.

What it does *not* reach was checked policy by policy and is the more important half. Reports,
report versions, attachments, obligations, assessments, reviews, evidence snapshots and plan baselines are keyed to a `student_id`, never to a `project_id`.
Joining a project tells you what the work is. It tells you nothing about how anyone on it is doing.

Two mitigations, and a rate limit. The flag: `open_to_join` defaults closed and is the
professor's per project, so nothing became joinable when this shipped and the exposure is bounded
by decisions somebody took. The projection: `GET /projects/joinable` serves title, stage, status
and a member count, and not the research questions — though since joining is unilateral and
instant, that is about keeping a directory a directory rather than about confidentiality. The
rate limit: joining a project and ending a membership are capped at thirty an hour, because each
call writes a membership row kept as history and an audit row that is never deleted. Until v0.20
ending a membership also advanced the workspace-wide access epoch and discarded every cached
assistant answer; the epoch went with
the cache (ADR 0023), and access still ends the moment the membership does, because
`scope.project_ids` is compiled from memberships on every request.

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

# every call a screen makes is a route the API serves
python3 scripts/check_docs.py        # "screens call served endpoints"
```

This document no longer carries an endpoint count. v0.13 to v0.17 did, checked by
`scripts/check_docs.py`, and keeping the number in lockstep cost more on every change than the drift
it caught. The script still fails when a screen calls a route that is not served, and skips the
generated OpenAPI types and the test files, which name routes no screen calls.

Two shapes in the call sites need care, and a grep that ignores them is wrong in both directions.
A path is written as a template literal, so `${id}` has to become a parameter before anything else
— and where the expression is not a bare identifier but a ternary building a query string, the
path ends where the expression begins. `POST /users/{id}/{action}` is one call site standing for
three routes.

Those two commands settle 🖥️ against ⚙️. They cannot see 🚧, because an endpoint a screen calls
looks identical whether or not anyone can reach that screen. One more is needed, and it is the one
that found §8.2:

```bash
# every inbound link. A route defined in router.tsx and absent here is orphaned.
grep -rnE '(to=\{?["`]/|navigate\(["`]/)' frontend/src --include=*.tsx | grep -v '\.test\.'
```

It is read against `frontend/src/app/router.tsx` for routes it defines that nothing reaches. A
screen with no inbound link is the way this document goes quietly wrong. (Until v0.20 a second grep
checked the assistant's citation locators against the same file; they went with it.)

None of the three commands can see ✂️ or ◻️, and no command can: those rows record a decision, and
a decision leaves no trace in the code until someone acts on it. They are checked against
[research_management_requirements.md](research_management_requirements.md) instead, and they are
meant to be temporary. A ✂️ row is deleted in the pull request that removes the code — deleting it
earlier makes this document disagree with a running deployment. A ◻️ row becomes ⚙️ or 🖥️ in the
pull request that builds it. A ◻️ row that has been here for several versions is telling you
something, and it is not that the table needs updating.

Update this file in the pull request that changes what it describes, as with
[implementation_status.md](implementation_status.md).
