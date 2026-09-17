# ADR 0015 — Belonging to a workspace is plural; working in one is singular

Status: accepted — 2026-09-16
Extends: [ADR 0014](0014-joining-and-leaving-a-workspace.md)

## Context

ADR 0014 made an account's workspace movable, which let a professor join one workspace and leave
another. It did not let them be in two at once, because `users.workspace_id` is a single column:
joining was moving, so every join was also a departure. A professor supervising two labs had to
choose which one the product knew about.

The column cannot simply become a set. It is the parent of a composite foreign key on eight tables
and the field every visibility predicate compares against — `Scope` names exactly one workspace,
and that is what keeps the permission model a single builder (ADR 0004).

The two jobs the column was doing had to come apart:

- **Belonging** — which workspaces this account is a member of. Naturally plural.
- **Working in** — which workspace a request is scoped to, and what every per-user row is anchored
  to. Necessarily singular.

## Decision

**`workspace_members` records belonging. `users.workspace_id` records working in.**

A student has exactly one membership, written when they are invited and deleted when they are
removed. A professor may have many.

- `POST /workspaces/{id}/join` adds a membership *and* moves the anchor, so you go where you
  joined. Joining one you already belong to does only the second, which is how switching is spelled.
- `POST /workspaces/{id}/leave` deletes the membership. If it held the anchor, the anchor moves to
  another workspace you still belong to.
- `POST /workspaces` creates, joins and takes you there, leaving every other membership alone.

`Scope` is unchanged and still names one workspace, so **no visibility predicate changed**.

Three rules follow, and each replaces a check that used to read the wrong column:

- **Archiving counts memberships**, not `users.workspace_id`. A professor who belongs to a
  workspace but is working elsewhere still occupies it, and counting the column would have let it
  be archived out from under them.
- **The roll is keyed by membership.** A colleague who belongs here but is working elsewhere stays
  on the roll. The query is a subquery on `workspace_members` so a professor in two of the listed
  workspaces still appears once.
- **Leaving your only membership is refused.** `users.workspace_id` is not nullable, so an account
  is always in at least one workspace. Leaving the last one has nowhere to put the anchor.

Invitation writes the membership, not acceptance. An invited account is on the roll and counts
against archiving from the moment it is invited, which is what stops a workspace being archived out
from under someone who is about to accept.

## Consequences

- **A professor can supervise several labs at once**, which is what this was for, and the workspace
  list now shows three distinct states per row: belong and working in, belong but elsewhere, and
  neither (owned only).
- **Owning and belonging are now fully separate.** Ownership (ADR 0012) decides which workspaces
  you *may* join and archive; membership decides which you are *in*. A professor can own a
  workspace they have left — that is how one is emptied and then archived.
- **`users.workspace_id` is a worse name than it was.** It now means "the workspace this account is
  working in", and the comment on the column says so. Renaming it would touch eight foreign keys
  and every module's predicate, which is exactly the cost this decision avoided paying.
- **A user's row on a cross-workspace roll is labelled by their anchor**, not by the workspace the
  reader is thinking of. For a student, who has one membership, those are the same. For a colleague
  professor it shows where they are working, which is the more useful of the two but is worth
  knowing when reading the list.
- **Nothing about students changed.** One membership each, written at invitation, removed at
  removal. Every existing behaviour — obligations, reports, history pinning — reads the anchor, and
  for a student the anchor and the membership are the same workspace.
