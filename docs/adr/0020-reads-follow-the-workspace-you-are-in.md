# ADR 0020 — Reads follow the workspace you are working in

Status: accepted — 2026-09-24
Supersedes: [ADR 0016](0016-reads-span-membership.md)

## Context

ADR 0016 widened a professor's reads to every workspace they belong to and kept writes in the one
they were working in. The header switcher (added after it) then presented that working workspace as
"the frame every other screen is read in" — and it was not. A professor who switched from one lab to
another still saw both labs' projects and both cohorts on `/projects` and `/people`, and the only
thing the switch changed was where the next project they created would land.

Two consequences of the spanning read had already come back as bugs: the student profile's weekly
list interleaved two calendars (ab3eadb), and the widened period list needed an order postgres did
not give it (6d2ec33). Each was patched on the screen that showed it; the cause was the read-set.

## Decision

**A professor's `Scope.workspace_ids` is `{workspace_id}`, the same as a student's.** Switching
workspace changes what every screen shows, not just where writes go.

`Scope.workspace_ids`, `Scope.access_epochs` and `Scope.within` stay. They are still the one seam
every visibility predicate is built on, so a future widening — or a narrower, explicit one for a
single read — is still one diff. Only `identity.service.scope_for` changed: it no longer adds the
workspaces the professor has joined.

## Consequences

- **The switcher is the frame.** Projects, people, overview, reports, evidence and the assistant
  show the workspace in the header and nothing else. Seeing another lab means switching to it.
- **Belonging is still plural.** `workspace_members` still decides which workspaces a professor
  can switch into, `GET /workspaces` still lists them, and the roll on `/people` is still keyed by
  membership — so a colleague who belongs here but is working elsewhere is still listed.
- **Acting across workspaces is unchanged.** Moving a student names its destination and checks
  administered workspaces directly; it never went through the read-set.
- **Screens that grouped by workspace now show one group.** The grouping is harmless and is left in
  place; it is what a wider read would need again.
- **The cache digest over `access_epochs` still holds**, trivially: it spans one workspace.
