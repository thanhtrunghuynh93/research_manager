# ADR 0017 — A student starts and joins their own projects; the professor keeps the gate

Status: accepted — 2026-09-17
Amends: [ADR 0011](0011-co-equal-professors.md), [ADR 0004](0004-application-level-authorization.md)

## Context

Nothing in this system assigns a report. A weekly obligation is derived, from one input: a
membership on an `ACTIVE` project that overlaps the reporting week
(`projects/repository.memberships_active_in_range`, consumed by `reporting.ensure_obligations`).
The professor's only levers are indirect — add a membership, or excuse an obligation after the
fact. That part of the product matches how the work actually runs: the report is owed every week
because the meeting happens every week, not because anyone asked for it.

But both halves of the one input were the professor's. Only a professor could create a project, and
only a professor could put anyone on one (AUTH-01). A student who started a piece of work had to
ask for a project record to exist before anything they did could be reported against — and the
request had no screen, so it happened in a corridor and then not at all.

The obvious change, letting a student create a project and join one, runs into something that is
not obvious: **a membership is the entire grant of access to a project.** `_in_scope` is
`same_workspace AND project_id IN scope.project_ids`, with no second gate and no status test. So
joining hands over the project record, its milestones, its tasks — including the free-text
`blocker` and `completion_reason` another student wrote about their own work — its research
decisions, its repositories, its shared evidence, and the member list, which is the only route by
which one student learns another's name (`user_visible_to` restricts a student to their own
account). Unbounded self-join would have been a workspace roster-enumeration primitive with a
button on it.

What joining does *not* reach was checked policy by policy and is worth recording: reports, report
versions, attachments, obligations, assessments, reviews, feedback, corrections, supervision notes,
evidence snapshots and plan baselines are keyed to a `student_id`, never to a `project_id`. Joining
a project tells you about the work. It tells you nothing about how anyone on it is doing.

## Decision

**A student may start a project, join an open one, edit what they started, and leave.**

Five parts, because each is a choice a reader would otherwise have to reconstruct from the code:

1. **Joining is gated per project, not per workspace.** `projects.open_to_join` is a professor's
   decision, default false. Nothing became joinable when this shipped, and the exposure above is
   bounded by choices a professor made deliberately rather than by the shape of the schema.

2. **Discovery is a separate, narrower read.** `GET /projects/joinable` returns title, stage,
   status and a member count — not the research questions, intended contributions, venue target or
   shared resources. `project_visible_to` was *not* relaxed: `_in_scope` is shared with `Milestone`,
   `Task` and `ResearchDecision`, so widening it there would have widened four things in one edit.
   This is the argument `Scope.within` already makes in its own docstring, applied one layer down.

3. **A student's project is `active` on creation; a professor's stays `proposed`.** Activation
   exists to make a second party's assent visible, and a student starting their own work has no
   second party. A proposed project derives no obligation, so the alternative was a project that
   looks finished and produces nothing — the same trap the activation control was built to close
   from the other side. The creator is enrolled on it in the same transaction, because a project
   with no members derives nothing either.

4. **A student joining part-way through a week owes from the next week.** This is why
   `project_memberships.origin` exists. A professor assigning someone on a Saturday means that week
   is owed; they know what they are asking for. A student joining on a Saturday does not, and under
   the uniform rule they would have been late by Sunday night — and emailed about it — for a week
   they spent off the project. The rule lives in the membership query in `projects`, which is the
   only layer that can hold it: `projects` cannot import `reporting`, so the join path has no way
   to look a period up.

5. **The creator may edit the record, never its standing.** Title, description, research questions,
   intended contributions, stage and dates; not `status`, not `ai_restricted`, not `open_to_join`.
   The first set is what the work is. The second is whether work is owed, whether the text may be
   sent to a model provider, and who else may read it — all supervision decisions.

**Leaving still advances the workspace's access epoch.** This was questioned and the answer is no:
the answer cache is keyed by `user_id` *and* by the read-set epoch digest, so the leaver's own
cached answers were computed with access they no longer have. Serving them would be the disclosure
AUTH-03 exists to prevent. The cost is real — one student can discard every cached answer in the
workspace by joining and leaving, and each subsequent question re-runs against the workspace's
model budget — and the mitigation is a rate limit on the two routes, not a weaker invalidation.

## Consequences

- Task blockers and completion reasons on an open project are readable by anyone who joins it. This
  is the sharpest edge of the change and it is bounded only by which projects a professor opens.
- The member list of an open project discloses the display names of everyone who has worked on it,
  including past members. For a student this is otherwise unobtainable.
- A student can now create their own obligations, so the professor's outstanding list and the
  missed-deadline emails can be driven by a student's own action rather than only by assignment.
- `projects.created_by` becomes load-bearing for the first time. It is nullable and carries no
  foreign key, so a row without one has no creator and falls to the professor alone; and
  `_on_user_removed` closes memberships without clearing it, so a removed account still matches as
  creator. The policy grants the creator the project row itself, which is what lets the edit right
  outlive the membership, as AUTH-07 requires.
- `POST /projects` now answers with a different status depending on who called it.
- AUTH-01 is amended, not superseded: enrolment into a workspace is still invitation-only and still
  the professor's, and no account may act for another.
