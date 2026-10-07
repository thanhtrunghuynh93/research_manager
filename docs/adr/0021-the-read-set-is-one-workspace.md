# ADR 0021 — The read-set is one workspace

Status: accepted — 2026-10-07
Amends: [ADR 0020](0020-reads-follow-the-workspace-you-are-in.md)

## Context

ADR 0020 made every read follow the workspace being worked in, and kept `Scope.workspace_ids`,
`Scope.access_epochs` and an `across_workspaces` flag on `GET /periods` as the seam a wider read
would go through. Nothing has widened since. The seam cost a set where a value would do, a second
epoch field the cache had to digest, a query flag four screens asked for by name, and a branch on
`/people` for rows that could no longer arrive.

## Decision

**A `Scope` names one workspace, and a read sees only it.** `Scope.workspace_ids`,
`Scope.access_epochs` and the `across_workspaces` flag are removed. `Scope.within(column)` stays as
the single choke point every visibility predicate is built on, and compares the column with
`Scope.workspace_id`. Widening a read again is a new decision, not a flag.

## Consequences

- `GET /periods` has no `across_workspaces` parameter; it lists the weeks of the workspace being
  worked in. The screens that asked for the wide list ask for the ordinary one.
- `/people` lost the not-in-this-workspace branch (`people.elsewhere`): every row on the roll is in
  the workspace the professor is in, so every row carries the professor's controls.
- The answer cache's fingerprint is the anchor workspace and its epoch, which is what it already
  digested in practice.
- Shapes that group by workspace (the overview's week, `PeriodOut.workspace_id`) are left as they
  are; they now always hold one group.
