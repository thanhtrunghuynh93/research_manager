# ADR 0004 — Authorization in one application policy layer; Row-Level Security deferred

Status: accepted — 2026-09-11

## Context

AUTH-02 requires the same permissions in every API, search, download, export, and AI retrieval
path. Postgres Row-Level Security enforces at the database, but complicates connection pooling,
migrations, background jobs acting on behalf of users, and the retrieval SQL.

## Decision

A per-request `Scope` and a registry of `visible_to(scope, Model)` predicate builders in
`core.authz`. Every repository query, presigned-URL issue, export, and retrieval statement uses
them. An aggregate without a registered policy cannot be queried (fail closed). A workspace
`access_epoch` invalidates cached answers on membership changes.

## Consequences

- One place to audit and test; the authz test suite parametrises every access scenario over
  API, search, download, and export.
- Developers must route reads through `repository.py`; the API layer is forbidden from importing
  ORM models, which makes bypassing the filter awkward by design.
- RLS remains available as defence in depth after the MVP (open decision 6 in the architecture).
