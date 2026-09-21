# How professor, student, workspace, project and reports are organized

Version 0.2 — 21 September 2026 — companion to [research_management_requirements.md](research_management_requirements.md) v0.7, [architecture.md](architecture.md) v0.5, [use_cases.md](use_cases.md) v0.15, and the [ADRs](adr/)

This document is an orientation to the central relations: what belongs to what, which of those
relations are plural, and where each one is enforced. It is derived from the documents above and
from the tree; where it abbreviates them, they remain authoritative. It exists because the answer
to "can a professor be in two workspaces?" is spread across five ADRs, an amendment, and a
foreign-key split, and a reader meeting the schema first will reconstruct it wrongly.

## 1 The shape in one paragraph

A **workspace** is the tenant boundary — every row in the schema carries `workspace_id`. A
**professor** may belong to many workspaces; a **student** belongs to exactly one. A **project**
belongs to the workspace it was created in and never moves. A **project membership** joins a student
to a project in that student's own workspace, and is the sole input to a weekly **reporting
obligation**. A **report** is one per student per week, holding one entry per obligated project,
versioned immutably; assessment is per student × project × week. None of this is a rule a caller
applies: the same-workspace invariant is a set of composite foreign keys, and the asymmetry between
what a read may see and where a write lands is one function, `Scope.within`.

```
Workspace ──owner_id──────────────► User (prof)        administration: create, rename, archive
    ▲
    ├──workspace_members───────────► User (prof 1..n, student exactly 1)   belonging: what a read sees
    ├──users.workspace_id──────────► User (exactly one)                    anchor: where a write lands
    │
    ├── Project (pinned at creation)
    │      └── ProjectMembership ──► User (student)     composite FK onto BOTH ends
    │              ├── ReportingObligation (per period)
    │              └── PlanBaseline (per period)
    │
    └── CalendarConfig → ReportingPeriod
                             └── WeeklyReport (unique per student × period)
                                     └── ReportVersion (immutable, n)
                                             └── ProjectReportEntry (unique per version × project)
                                                     └── AssessmentVersion → AssessmentReview
```

## 2 Workspace — the tenant boundary

Three distinct relations connect an account to a workspace. Conflating any two of them is the
failure the ADRs keep circling, so they are named separately here.

| Relation | Column or table | Cardinality | What it governs |
| --- | --- | --- | --- |
| **Ownership** | `workspaces.owner_id` | a professor owns 0..n | create, rename, set timezone, archive; the break-glass contact ([ADR 0012](adr/0012-workspace-ownership.md)) |
| **Belonging** | `workspace_members` | professor 1..n, student exactly 1 | what a read may see; occupancy for archiving; who is on the roll ([ADR 0015](adr/0015-plural-workspace-membership.md)) |
| **Working in** | `users.workspace_id`, not nullable | exactly one | where the next write lands; the parent of every composite foreign key ([ADR 0016](adr/0016-reads-span-membership.md)) |

Owning and belonging genuinely differ — a colleague belongs to a workspace they do not own, and
someone who created a workspace and later left owns one they do not belong to — so `GET /workspaces`
returns the union and every action offered on the screen is gated on the union. Renaming and
archiving stay with ownership alone.

Four rules follow from the boundary rather than from taste:

- **A workspace is created empty.** Its creator owns it; the first account arrives by invitation
  naming the workspace, so every account has one from creation rather than from acceptance
  (AUTH-04).
- **It is archived, never deleted.** Every foreign key into a workspace cascades, so a delete would
  take its users, projects, reports and assessments with it. Archiving counts **memberships** and
  refuses while any account there is still active, so the flag never has to be enforced further
  down.
- **Leaving needs somewhere to land.** `users.workspace_id` is not nullable, so leaving an account's
  only membership is refused; leaving is also refused when it would leave active accounts in a
  workspace with no active professor — AUTH-01's rule applied to an ordinary API call.
- **Moving an account is decided by the schema** (AUTH-06). Of the eight tables keyed on
  `users(workspace_id, id)`, the four holding identity records — `invitations`, `sessions`,
  `password_resets`, `notifications` — carry `ON UPDATE CASCADE` and follow the account; the four
  holding research history — `project_memberships`, `weekly_reports`, `developer_identities`,
  `contributions` — do not. So `POST /users/{user_id}/workspace` moves an account that has written
  nothing and Postgres refuses one that has. That is the rule, not a gap
  ([ADR 0014](adr/0014-joining-and-leaving-a-workspace.md), [use_cases.md](use_cases.md) §2.1).

## 3 Professor

- **Belonging is plural, writing is singular.** Reads span `Scope.workspace_ids`, every workspace
  the account belongs to; writes land in `Scope.workspace_id`. The comparison lives in
  `Scope.within` ([`backend/app/core/authz.py`](../backend/app/core/authz.py)), which all
  thirty-three visibility predicates call, so widening what a read may see is one diff. Screens
  group by workspace rather than labelling every row.
- **Co-equal inside a workspace** ([ADR 0011](adr/0011-co-equal-professors.md)): every professor
  there sees every student, report, assessment and supervision note, and any professor may invite a
  student, invite a colleague as a professor, and remove a student.
- **No professor may demote, deactivate or remove another through the API.** That is break-glass,
  run from the host shell, and every command that could reduce the professor count refuses to leave
  a workspace with none.
- **A role is fixed at acceptance.** Before acceptance a re-invitation may reissue at a different
  role, because the role travels on the user row; after acceptance there is no route to change one.
- **Acting on someone does not span.** `POST /users/{id}/suspend` and `.../remove` resolve their
  target through the caller's `workspace_id`, so a student listed under another workspace shows no
  controls. Moving a student is the exception, because it names the destination explicitly.
- Reserved to the professor: the reporting calendar; a project's *standing* (status, whether it is
  open to joining, whether its text may reach a model provider); excusing and extending obligations;
  approving or overriding an assessment; supervision notes; the research assistant.

## 4 Student

- **Exactly one workspace**, written at invitation, so belonging and anchor coincide and nothing
  about a student's access changed when belonging became plural.
- **Enrolment is invitation-only.** There is no self-registration, and an address that already
  belongs to a user in another workspace is refused, so a second invitation is not how a student
  moves.
- **A student owns the projects they report on** ([ADR 0017](adr/0017-students-own-their-projects.md),
  PROJ-07, AUTH-07): they may start a project, join one a professor has marked open to joining, and
  edit the record of what they started — including after their membership on it has ended. They may
  not place another account on a project, and **they may not end a membership, their own included**
  ([ADR 0019](adr/0019-ending-a-membership-is-the-professors.md)): joining adds work to a student's
  week and ending one removes an obligation, and only the second is a supervision decision.
- **Reads:** their own reports and drafts; their own assessments, and only once a review has
  approved them; the projects they are a member of; the contributions and identity mappings
  attributed to them, which is the precondition for contesting misattribution (REPO-04).
- **Never reads:** another student's report or assessment, supervision notes, professor-only
  feedback, or the assistant, which is professor-facing by decision rather than by omission.
- **Removal** ends every open project membership and deactivates the account in one transaction,
  which is what stops obligations deriving. Deactivation alone is suspension and leaves memberships
  open.

## 5 Project

`projects` holds title, description, `research_questions[]`, `intended_contributions[]`, `stage`,
`status`, `start_on` and `target_on`, `venue_target`, `repo_url`, `shared_resources`,
`ai_restricted`, `open_to_join`, `created_by`. `repo_url` is a pointer for the people on the project
and nothing more: it is not a connected repository, nothing is ingested from it, and no contribution
is attributed from it (PROJ-01).

- **Pinned to one workspace at creation, forever.** A student's projects are therefore the projects
  of their one workspace.
- **Status** is `proposed`, `active`, `paused`, `completed`, `archived`, and only `active` derives an
  obligation ([`backend/app/projects/repository.py`](../backend/app/projects/repository.py)). A
  professor's project starts `proposed`, because activation is where a second party's assent is
  recorded; **a student's starts `active`**, because there is no second party and a proposed project
  owes nothing, so leaving it proposed would give them a project that produces nothing and no screen
  saying why.
- **Authorship is split** (AUTH-07). The creator may change what the work *is* — title, description,
  research questions, intended contributions, stage, dates — for as long as the project exists. The
  creator may not change its *standing*: `status`, `open_to_join` and `ai_restricted` are whether
  work is owed, who else may read it, and whether the text may be sent to a model provider. A
  project with no recorded creator is the professor's alone.
- **A project carries its own documents.** Files attached to the project and to no week are its
  shared resources (PROJ-01): everyone on the project reads them, whoever attached one removes it,
  and they are not extracted, indexed or citable
  ([ADR 0018](adr/0018-project-documents-are-shared-with-the-project.md)).
- **A membership is the entire grant of access to a project.** The predicate is same workspace and
  `project_id IN scope.project_ids`, with no second gate, so joining hands over the project record,
  its milestones, its tasks — including the free-text blockers and completion reasons another
  student wrote — its research decisions, its repositories, its shared evidence, and the member
  list, which is otherwise the only route by which one student learns another's name. That is why
  `open_to_join` defaults false and discovery is a separate, narrower read returning title, stage,
  status and a member count only ([ADR 0017](adr/0017-students-own-their-projects.md)).
- **`project_memberships`** records responsibility, `origin`, `joined_on`, `left_on`,
  `first_required_period_id` and `last_required_period_id`, and planned allocation. It is unique per
  `(project_id, student_id)` while `left_on IS NULL`; history is retained rather than deleted.
  `left_on` is exclusive — the first day the student is no longer a member — so ending a membership
  today revokes access today.
- **`origin` decides which week is owed.** A membership that was assigned by a professor or created
  with the project owes the week it lands in; a student who joined an existing project owes from the
  following week, so joining on a Saturday is not a report due that Sunday for a week spent off the
  project (PROJ-02).
- **What a membership does not reach:** reports, versions, attachments, obligations, assessments,
  reviews, feedback, corrections, supervision notes, evidence snapshots and plan baselines are keyed
  to a `student_id`, never to a `project_id`. Joining a project tells you about the work and nothing
  about how anyone on it is doing.

## 6 Reports

The chain is `CalendarConfig` → `ReportingPeriod` → `ReportingObligation` → `WeeklyReport` →
`ReportVersion` → `ProjectReportEntry`.

- **The calendar is versioned.** Changing the meeting day inserts a new configuration with an
  `effective_from` and applies to future periods only; periods already open keep their original
  deadline. The deadline is derived, not stored: 23:59 local on the day before the meeting, so with
  the proposed default it falls inside the period it closes (REP-01).
- **Obligations are derived, never assigned.** The input is a membership on an `active` project
  overlapping the week, bounded by the first and last required period and edited by exemptions and
  extensions. An obligation is derived as soon as the membership exists rather than at the next
  scheduled run, and the same two tests are applied again when one is read — so a project taken out
  of `active` owes no week, including the one in progress (REP-06,
  [ADR 0019](adr/0019-ending-a-membership-is-the-professors.md)).
- **One package, many entries** (REP-02). A report is unique per student and period; an entry is
  unique per report version and project. The student submits once a week, and assessments stay
  separate per student–project–week rather than collapsing into one ranking score.
- **Submission is immutable.** `report_versions`, `project_report_entries`, `plan_baselines`,
  `assessment_versions` and their neighbours carry an immutability trigger, and
  `first_submitted_at` has a trigger of its own, so revisions, reminders and review status cannot
  restate when a week was filed.
- **Change is tracked per entry.** `content_hash` over the canonical entry JSON decides whether
  `content_changed_in_version_id` is carried forward, so a resubmission after a revision request on
  one of two entries re-assesses only the entry that changed (ASSESS-09, AC-17).
- **The template asks three questions, not five** (REP-03): stage and milestone, planned work,
  **Progress** — work, results and findings including negative ones — **Evidence**, experiments
  where applicable, **Challenges** — deviations, blockers and the questions they raise — and next
  steps. The `results` and `questions` columns remain because a week filed under the older template
  is shown as filed and never rewritten. **Hours are not asked for**; weeks that recorded one keep
  it.
- **Evidence is a file, not a link** (REP-04). Originals and extracted text are stored, extraction
  has three outcomes — `ok`, `unsupported`, `failed` — so an unreadable figure is not a week
  recorded as empty, and extraction runs when the report is submitted rather than as each file
  arrives. The student who attached a file may remove it, submitted week or not, and removal reaches
  the stored object, the extracted text, the index and the cached answers; an assessment written
  against a removed file keeps its rationale and loses the citation.
- **Lifecycle** is draft, submitted, revision requested, resubmitted, reviewed, with timing — on
  time, late, missing, excused — tracked separately. A missing report is a condition recorded on the
  obligation, never an invented assessment or an automatic zero (REP-06).
- **Plan baselines are the frozen half of the week** (PROJ-04). Last week's next-week plan freezes at
  period start as `frozen`, or as `empty` when there is none, which the student fills as `proposed`
  and the professor `accept`s. Commitment completion is computed only against `frozen` or `accepted`
  rows and is otherwise reported unavailable, and at most one is in effect per membership and period.
- **The missed-deadline email** reads obligation state at send time, so a submission at 23:59 gets
  none, and the unique key on recipient, period and kind makes a retried dispatch a no-op (REP-08,
  AC-19).

## 7 The invariants that hold it together

| Invariant | Where it lives |
| --- | --- |
| A membership cannot straddle two workspaces | Composite foreign keys onto `projects(workspace_id, id)` and `users(workspace_id, id)` |
| History stays in the workspace it was written in | The four history foreign keys without `ON UPDATE CASCADE` |
| Widening what a read may see is one diff | `Scope.within(column)`, called by every visibility predicate |
| A cached answer dies when access changes | `workspaces.access_epoch`, incremented in the same transaction as any membership end, deactivation, role change or visibility change |
| Submitted and approved history is never rewritten | The immutability triggers, and one approved review per assessment version |
| No private record follows a project | Everything confidential is keyed to a `student_id` |

## 8 Where the build diverges from the specification

Recorded here because a reader of sections 2 to 6 would otherwise assume all of it is reachable;
[implementation_status.md](implementation_status.md) §3 is the authority. The list is shorter than
it was: requirements v0.7 amended UI-03, PROJ-01, PROJ-06, PROJ-07, AUTH-01 and REP-06 to say what
the product does, so those are no longer divergences at all.

- Moving a student who has written anything is refused, by the constraint set rather than by a check
  (§2).
- Milestone completion and dated decisions are computed and stored but shown on no screen, because
  nothing writes what they would show — `accepted_completion` and `POST /{id}/decisions` have no
  authoring screen (UI-03, amended).
- A finished project leaves a student's week silently: the obligation is filtered rather than
  excused, so nothing on `/me` names the project that stopped owing
  ([ADR 0019](adr/0019-ending-a-membership-is-the-professors.md)).
- Pre-deadline reminder rows are written and nothing reads them: the in-app surface was withdrawn
  and only the missed-deadline message is emailed, so no student is reminded before a deadline
  today (REP-07).
- No code path authors professor feedback beyond the released assessment.
- Exports were withdrawn (UI-06), so a student cannot keep a copy of their own released records.
- The student has no assistant, which is recorded as next-release work rather than a gap in the
  permission model: the retrieval path and the predicate are already shared.

## 9 Keeping this document true

Nothing here is checked by `scripts/check_docs.py` beyond its links and its version
cross-references, because everything it says is a relation rather than a count. The load-bearing
claims are pinned elsewhere: the foreign-key split by `backend/tests/module/identity/test_workspaces.py`,
the visibility rules by the `authz`-marked tests, and the weekly chain by the acceptance scenarios.
When one of those tests changes, this document is the second place to look.
