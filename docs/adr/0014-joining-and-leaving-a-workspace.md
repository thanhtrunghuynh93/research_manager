# ADR 0014 — An account joins and leaves a workspace

Status: accepted — 2026-09-16
Supersedes: [ADR 0013](0013-active-workspace-on-the-session.md)
Amends: [ADR 0012](0012-workspace-ownership.md)

## Context

ADR 0013 put "which workspace am I in" on the session, because `users.workspace_id` could not
change. That made the professor's *view* movable and left their *account* where it was, which
meant leaving a workspace never emptied it, and a workspace an account belonged to could never be
archived. The screen had to say so, and saying so did not make it less wrong: the thing people
want when they leave somewhere is to no longer be there.

The obstacle was real. `users.workspace_id` is the parent of a composite foreign key on eight
tables and none cascaded on update, so Postgres refused the change while any child row existed.
Enrolment is invitation-only, so every account has an `invitations` row from creation and the
update was refused for everyone.

But the eight are not alike. Four hold identity records — an invitation, a session, a reset link,
a notification — which belong to the person. Four hold research history — memberships, reports,
developer identities, contributions — which belong to the work.

## Decision

**The account moves.** `users.workspace_id` is updatable again, because the four identity foreign
keys now carry `ON UPDATE CASCADE` and follow the account.

The four history keys deliberately do not:

    project_memberships   weekly_reports   developer_identities   contributions

So a student who has submitted anything is refused by the database, and "history stays in the
workspace it was written in" is enforced by the schema rather than remembered by a caller. The rule
use_cases.md §2.1 records is now a property of the constraint set.

- `POST /workspaces/{id}/join` — move this account here.
- `POST /workspaces/{id}/leave` — move it out, to another workspace this professor owns.
- `POST /workspaces` creates and joins, so a new workspace is one you are in.

`sessions.active_workspace_id` is dropped and `Scope` is compiled from the user row again. One
question, one answer.

Two rules keep leaving honest:

- **Leaving needs a destination.** `users.workspace_id` is not nullable, so an account is always in
  exactly one workspace. Leaving lands on another workspace the professor owns, oldest first, and
  is refused when there is none rather than guessed at.
- **Leaving must not strand people.** A workspace that still holds active accounts is never left
  without an active professor — AUTH-01's rule, applied to an ordinary API call rather than only to
  break-glass. Leaving the *last* account out is allowed, and is how a workspace becomes archivable.

**Sessions are not revoked on a move.** `sessions.workspace_id` cascades with the account and
`Scope` is compiled per request, so the next request is already scoped to the new workspace.
Revoking instead would sign a professor out for the ordinary act of creating a workspace. Both
access epochs still advance, which is what AUTH-03 actually needs: cached answers and evidence
snapshots were built under an access the account no longer has.

## Consequences

- **Leaving empties.** A workspace whose last account leaves has no active accounts and can be
  archived, which is what made the previous design feel broken.
- **A professor's records follow them.** Their notifications move with the account even though the
  content describes the workspace they came from. Notifications have had no read path since
  use_cases.md v0.4, so this is a property of rows nothing displays; it would need revisiting if a
  read path returned.
- **The ownership rule from ADR 0012 still decides what you may join.** You can only join a
  workspace you own, so the list on the screen is exactly the set you can move between. "Administer"
  is gone from the interface as a word — it was the mechanism showing through.
  *Amended by [ADR 0015](0015-plural-workspace-membership.md): once belonging became plural, joining
  one you already belong to became how switching is spelled, and a colleague belongs to a workspace
  they do not own. What you may join is therefore what you own **or** belong to — the same set
  `list_workspaces` puts on the screen. Ownership still decides what you may create and archive.*
- **A student still cannot be moved, and now the schema says why.** Not "no route exists" but four
  foreign keys that refuse. A future decision to allow it has to name which history it is willing
  to drag along.
- **ADR 0013's re-check on every request is gone with the column it guarded.** There is no second
  source of truth left to go stale.
