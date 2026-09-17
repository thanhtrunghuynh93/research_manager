# ADR 0012 — Ownership is the workspace administration relation

Status: accepted — 2026-09-16
Amends: [ADR 0011](0011-co-equal-professors.md)

## Context

Use cases v0.3 added workspace management as a professor capability: create a workspace, rename it,
archive it, and move a student between workspaces. Nothing of it existed, and the reason nothing of
it existed turned out not to be a missing screen.

A workspace is the tenant boundary. `Scope` carries exactly one `workspace_id`
(`app/core/authz.py`), `users.workspace_id` is non-null, and the `(workspace_id, user_id)` unique
constraint is the target of every composite foreign key in the schema. A professor is a user, so a
professor is in one workspace. "A professor administers several" does not typecheck against that.

Workspaces were already plural — `bootstrap_workspace` has no guard against a second one, and
`revoke_all_sessions` iterates workspaces and writes one audit row per workspace it touched. What
was missing was any relation saying which of them a given professor may administer.

Two relations were available.

**Scope spans workspaces.** Give `Scope` a set of administrable workspace ids beside the one it
acts in. Most faithful to the requirement, and it widens the predicate that every module compiles
against — the single thing ADR 0004 exists to keep singular.

**Ownership, separate from membership.** `workspaces.owner_id` already exists. A professor
administers the workspaces they own and belongs to one. Nothing existing changes.

ADR 0011 put `owner_id` there as the break-glass contact and said so in the column comment:
*"the break-glass contact, not a privilege: professors are co-equal and nothing authorizes against
this column."* Choosing it means reversing that sentence deliberately rather than quietly.

## Decision

**`workspaces.owner_id` is the administration relation.** A professor administers a workspace when
they own it. `Scope` is unchanged and still names exactly one workspace: the one the caller acts
in.

ADR 0011's co-equality is unchanged *within* a workspace. Every professor there still sees every
student, every report and every note, and still cannot demote another professor through the API.
What ownership governs is the container, not the work inside it: creating, renaming, archiving,
and accepting a student moved from elsewhere.

Three rules follow from the boundary rather than from taste:

- **A workspace is created empty.** Its creator owns it and does not join it — they already belong
  to their own. The first account arrives by invitation naming the workspace, which is the only
  door AUTH-01 allows. This is the one real difference from `app.cli identity bootstrap`, which
  creates a workspace *and* a professor because it runs before any account exists.
- **A move requires owning both ends.** Owning only the destination would let a professor pull any
  student out of any workspace by id. Requiring both keeps every move inside one administrator's
  domain, so no call ever reaches across a tenancy (AUTH-02).
- **Archiving, not deleting.** Every foreign key into a workspace cascades; a delete would take its
  users, projects, reports and assessments with it and leave no audit row explaining why. Archiving
  refuses while any account there is still active, so the flag never needs enforcing further down:
  an archived workspace has nobody left to enforce it against.

A student moved between workspaces **leaves their history behind**. Reports, assessments,
artifacts, contributions and membership rows stay in the workspace they were written in;
`UserWorkspaceChanged` ends the memberships there so no obligation goes on deriving against a
project the student can no longer read. Both access epochs advance and every session ends.

## Consequences

- **A professor who owns nothing administers nothing.** A colleague invited into an existing
  workspace can do everything ADR 0011 grants — students, projects, reports, assessments — and
  cannot rename the workspace they work in. `owner_id` is nullable and `SET NULL` on user deletion,
  so a workspace can end up with no administrator at all; `breakglass transfer-professor` moves the
  column and is the way back. This is the cost of the decision and the most likely thing to be felt.
- **The co-equality in ADR 0011 is now scoped, not global.** "Professors are co-equal" reads as
  "co-equal over the work in a workspace" from here on. The column comment that said nothing
  authorizes against `owner_id` is no longer true and has been corrected.
- **A reassigned student looks new.** They arrive with no projects, no reports and no assessments,
  because those stayed. This is the recorded decision and not a defect, but it means reassignment
  is not a way to move a supervision relationship — only the account.
- **`Scope` did not change, so no predicate did.** The permission model stays one builder, which
  is what made this the cheaper of the two options and is the reason to prefer it even though it
  costs an amendment to ADR 0011.
- **Requirements §1 and §11 have not caught up.** They describe one workspace of up to 50 students
  and professors who "manage workspace settings". Nothing here has a requirement ID yet; see
  use_cases.md §2.1.
