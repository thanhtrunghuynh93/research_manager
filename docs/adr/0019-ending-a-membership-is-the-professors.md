# ADR 0019 — Ending a membership is the professor's, and a finished project owes no week

Status: accepted — 2026-09-21
Amends: [ADR 0017](0017-students-own-their-projects.md), PROJ-07, AUTH-01

## Context

ADR 0017 gave a student four things: start a project, join an open one, edit what they started,
and leave. The first three have held. The fourth turned out to be a different kind of act from the
other three, and the screen said so out loud — the button read **Done this project**, and its note
explained that the project would stop appearing in their week "including this one".

That is a supervision judgement wearing a student's control. Whether a piece of research is
finished is the thing the weekly meeting exists to decide, and a student who has stopped owing a
report for a project is a student the professor is no longer told about. The mechanism was sound
— the row is kept, the history stays, `left_on` is exclusive so the week is dropped cleanly — and
the authority was wrong.

There was also a gap on the other side. A professor ending a project — setting its status to
`completed` — stopped *new* obligations deriving and left the ones already derived sitting on the
current week. `memberships_active_in_range` requires `Project.status == ACTIVE`;
`memberships_open_through`, which judges obligations that already exist, tested only `left_on`.
So the professor closed a project and the student still owed a report for it that week, and was
emailed about it at 00:00 on the meeting day (REP-08). The docstring on `memberships_still_owing`
already claimed the two agreed: *"an obligation already derived has to be judged by the same rule
that would derive it today"*. It was half true.

## Decision

**A student joins a project and does not leave it.** `end_membership` requires a professor;
`POST /projects/{id}/members/{membership_id}/end` refuses a student outright rather than only
refusing them somebody else's membership. The student's control is gone from the project screen,
and the professor gains one on the member row, where the person is.

**A project that is not `ACTIVE` owes no week, including the week in progress.**
`memberships_open_through` gains the project-status test its sibling already had, so the rule is
the same on the way in and on the way out. One query, three callers: the student's own week, the
completeness check when a package is submitted, and the professor's outstanding list — which is
what the missed-deadline email is built from.

Two things follow that are worth stating rather than deriving:

- **"This project is done" is a status change, not a row per student.** A professor who finishes a
  project sets its status once, and everyone on it stops owing that week. Ending one membership is
  for the other case: one student leaving work that continues without them.
- **Pausing and archiving behave the same way**, because REP-06 already names a paused project
  beside leave and holidays as a week nobody owes. There is no separate rule for them, which is
  the point: there is one rule, and it is the project's status.

The obligation rows are not deleted or excused. They stay, because they are how the week was
derived and the professor's history reads them, and they are filtered on the way out — the pattern
`_obligations_still_owed` already used for a membership that ended mid-week.

## Consequences

- **PROJ-07 and AUTH-01 were amended rather than left standing.** Both said a student may end
  their own membership; requirements v0.7 says the professor does, and REP-06 gained the rule
  about a project that is no longer active. The specification and the product agree, which is
  what stops this ADR from being the only place the real rule is written down.
- **A student who wants off a project has to ask.** That is the intent, and it is a real cost: the
  corridor conversation ADR 0017 was written to remove comes back for this one case. It is the
  trade for the professor knowing that a project stopped producing reports.
- **`origin` keeps mattering.** A student can still put themselves on a project, and the asymmetry
  is now sharper — self-joining is theirs, self-leaving is not. That is deliberate: joining adds
  work and leaving removes an obligation, and only one of those is a supervision decision.
- **A completed project stops the week silently.** Nothing tells the student why their tab
  disappeared. The obligation is not marked excused, so `/me` simply stops listing the project.
  A note on the week's screen naming the finished project would be the honest version, and it is
  not built.
