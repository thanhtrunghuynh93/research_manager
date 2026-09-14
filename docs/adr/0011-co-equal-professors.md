# ADR 0011 — Professors are co-equal; the role is fixed at acceptance

Status: accepted — 2026-09-14

## Context

The workspace was specified with one professor (requirements §1), and the code follows: every
visibility predicate is `if scope.is_prof: return same_workspace`, and the two self-action guards
in `set_role` and `deactivate_user` — a professor may not change their own role or deactivate
themselves — were together enough to guarantee at least one professor always existed.

A second supervisor breaks that reasoning rather than the code. Nothing ever prevented a second
professor; the role enum, the invitation path, and the notification fan-out all take a set. What
was missing was a decision about what two professors mean to each other.

Full symmetry — each able to eject the other — has no tiebreaker. A disagreement becomes a race,
and the loser's recourse is shell access. The asymmetry has to go somewhere, and the question is
which direction costs less when it is wrong.

## Decision

Professors are equal over students and unequal over each other.

Any professor may invite a student, invite a colleague as a professor, and remove a student from
the workspace. All three are ordinary audited API calls. No professor may demote, deactivate, or
remove another professor through the API; that is a break-glass command run from the host shell,
guarded by an explicit "at least one active professor" check.

**A role is fixed at acceptance.** Before acceptance an invitation is an offer, and reissuing it at
a different role is allowed — the role travels on the user row, which re-invitation updates. After
acceptance the role is immutable except through break-glass. `PATCH /users/{id}/role` is therefore
removed: with two roles, no promotion and no demotion, it had no valid transition left.

Removing a student is a compound operation in one transaction: every active project membership is
ended today, then the account is deactivated. Identity emits `UserRemoved`; the projects module
subscribes and ends the memberships, so identity stays unaware of projects as the layering
requires. Removal keeps the ledger — submitted reports, assessments, artifacts, attributed
commits, and audit history all survive, and past memberships remain as history rows carrying
`left_on`.

Deactivation stays a separate, narrower act: it suspends login and is undone by `reactivate_user`.
Removal is not reversible; a removed student is re-invited and returns with fresh memberships.

## Consequences

- Two professors see everything about each other's work, including supervision notes. That is the
  point of co-supervision, not a leak, but it means "professor-only" now means "not a student"
  rather than "not another professor". Notes carry `author_id` so the UI can say who wrote what.
- A professor can add a professor unilaterally and cannot undo it without shell access. This is
  the asymmetry most likely to be felt. It is the right way round: adding a colleague is a normal
  act with a visible audit row, and ejecting one should require deliberation off the happy path.
- Membership-ending had to stop being implicit. A merely deactivated student keeps accruing
  obligations and reminders because nothing in the obligation path filters on user state; removal
  ends memberships precisely so that stops. The underlying wart is fixed separately.
- `system_scope` borrows a professor's identity so scheduled jobs inherit professor visibility.
  With a set rather than a single row, the borrowed identity is now chosen deterministically and
  the Scope is marked `is_system`, so an audited job path cannot silently blame a professor for
  work a cron ran.
- Workspace settings — reminder offsets, AI budgets — remain last-writer-wins. For two people that
  is acceptable, but every write is now audited so "who changed it" is answerable.
