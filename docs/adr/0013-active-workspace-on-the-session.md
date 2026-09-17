# ADR 0013 — Which workspace you are in is a property of the session

Status: superseded by [ADR 0014](0014-joining-and-leaving-a-workspace.md) — 2026-09-16.
The constraint it worked around was paid off instead: four of the eight foreign keys now cascade
on update, so the account moves and the session no longer has to.
Extends: [ADR 0012](0012-workspace-ownership.md)

## Context

> **Superseded — read as history.** Nothing below describes running code.
> `sessions.active_workspace_id` was added by migration 0019 and dropped by migration 0020, so a
> fresh database has never had it. The routes named here — `POST /workspaces/{id}/enter` and
> `POST /workspaces/leave` — do not exist; joining and leaving act on the account (ADR 0014) and on
> membership (ADR 0015). The constraint this ADR works around, "none of the eight foreign keys
> cascades", was paid off for four of them.

ADR 0012 gave a professor workspaces they administer but do not belong to. That left two things
a person immediately wants and could not have: entering a workspace they had just created, and
leaving one.

The obvious implementation is to change `users.workspace_id`. It does not work, and the reason is
worth stating precisely because it will come up again.

`users.workspace_id` is the parent of a composite foreign key on eight tables — `invitations`,
`sessions`, `password_resets`, `project_memberships`, `weekly_reports`, `developer_identities`,
`contributions`, `notifications`. None carries `ON UPDATE CASCADE`, so Postgres refuses to change
the column while any child row exists, and enrolment is invitation-only, so every account has an
`invitations` row from the moment it is created. **No account can change workspace.** That is
requirements §9's *foreign keys scoped to the same workspace* read from the other direction: a
workspace is part of an account's identity rather than an attribute of it.

Relaxing those constraints was the alternative. Four of the eight hold identity records rather
than research history — a session and an invitation belong to the person, not to the work — so
cascading just those would let a professor's account move while still pinning any student who has
written a report. It is a real option and it is a migration on live foreign keys, taken to make
a column mutable that nothing else needs to be mutable.

## Decision

**The account never moves. The session does.**

`sessions.active_workspace_id` records which workspace a session is acting in; `NULL` means the
account's own, which is what every session meant before the column existed. `scope_for` builds
`Scope.workspace_id` from it.

`Scope` still names exactly one workspace. Every visibility predicate in the system compares
against `scope.workspace_id`, and **not one of them changed** — which is the whole reason to
prefer this over widening the Scope to carry a set.

- `POST /workspaces/{id}/enter` — a professor enters a workspace they own.
- `POST /workspaces/leave` — back to the account's own workspace. Never refused.
- `POST /workspaces` creates and enters in one call, because a workspace you made and are not
  looking at is a confusing thing to be handed.

The entered workspace is **re-checked on every request** rather than trusted from the session row.
Ownership can be transferred and a workspace can be archived while a session is open; either would
otherwise leave a live Scope pointing somewhere the caller no longer administers. A failed check
falls back to the account's own workspace, which is always somewhere they belong.

## Consequences

- **Leaving is not emptying.** A session leaves; an account stays. The workspace an account belongs
  to still holds that account, so it can never be archived from inside the product — `archive_workspace`
  refuses it by name. AUTH-01's "never leave a workspace with no active professor" is untouched,
  because that rule is about accounts and this is about sessions.
- **`/auth/me` now answers two questions.** `workspace_id` is where the account lives and never
  changes; `active_workspace_id` is where it is working. Every screen reads the second, because
  that is what the API scopes its answers by. A client that reads the first will show the right
  name and the wrong data.
- **Entering changes what every screen shows.** The client has to discard its cached queries on
  entering or leaving, or it will render one workspace's data under another's name.
- **A professor with no owned workspaces sees no change at all**, and neither does any student:
  `active_workspace_id` stays NULL and `Scope` is built exactly as it was.
- **The four cascadable foreign keys were left alone.** If moving an account ever becomes
  necessary — to empty a workspace so it can be archived, most likely — that migration is still
  available and this decision does not block it.
