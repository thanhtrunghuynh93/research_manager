# ADR 0023 — No research assistant

Status: accepted — 2026-10-07
Withdraws: [ADR 0008](0008-facts-outside-the-model.md)
Supersedes: [ADR 0009](0009-access-epoch-for-cached-answers.md)

## Context

Requirements section 7 specified a professor research assistant (QA-01..07), and all of it was
built: a model router with a keyword fallback, a registry of deterministic fact functions (ADR
0008), hybrid lexical and vector retrieval over the evidence index, an answer contract with
citations re-checked before every render, a streamed chat screen, persisted conversations, private
supervision notes on a professor-only branch, and an answer cache expired by a per-workspace access
epoch (ADR 0009).

Nobody used it. On the running deployment `conversations`, `messages`, `answer_cache` and
`supervision_notes` were all empty. No screen ever wrote a supervision note, so the one private
input the assistant had was never there. Meanwhile the access epoch was advanced by a dozen code
paths — ending a membership, removing an artifact, deactivating, moving or transferring an account
— and every one of them existed to expire a cache that held nothing.

The one part with a live caller was the fact functions: the professor overview read its next
deadline, outstanding count, week board, review queue and stalled runs through `facts.run(name)`.

## Decision

**There is no research assistant.** The chat screen, its API, the router, retrieval, answer
generation, the answer cache, conversations, supervision notes, the `route_question` and `answer`
prompts and their schemas, and the evidence search and citation-open routes that existed to serve
it are removed (migration 0029; requirements 0.12 withdraws QA-01..07).

- **The overview's numbers move, unchanged, to `app.overview`.** Plain functions the endpoint calls
  directly, with no registry and no citation objects the overview never returned. They read the
  same tables through the same services at the same instant, so the counts are the ones the
  assistant would have given; AC-15 is restated against the overview.
- **The access epoch is removed** with the cache it expired: `workspaces.access_epoch`,
  `evidence_snapshots.access_epoch` (written, never read) and `Scope.access_epoch`. Access is still
  revoked the moment a membership ends, because every read compiles `scope.project_ids` from the
  memberships table on every request; nothing caches a read any more.
- **Private supervision notes are withdrawn** with their only reader.
- **The notification records nobody read** — report submitted/resubmitted, and the professor's
  in-app summary of a missed deadline — are no longer written. The professor sees who is
  outstanding on the overview (REP-08); the student's missed-deadline email is unchanged.

The evidence index stays, because assessments are built from it: indexing on report submission and
attachment extraction, the access label on every chunk (now a registered policy on
`EvidenceChunk`), and the window and by-source reads the snapshot builder uses. Embeddings are still
computed at index time; nothing reads them now, and removing them is a separate change.

## Consequences

- AC-10 is read where the professor reads a trajectory: `progress_series` labels every point with
  its rubric and the Trajectory component marks the break. AC-11 is the ordinary revocation of a
  project's evidence and documents. AC-12 is about what an assessment may read.
- `rm_citation_validation_failures_total` keeps its `surface` label with one value, `assessment`.
- The membership join/leave rate limit stays, for the audit and history rows each call writes
  rather than for cache wipes.
- Bringing an assistant back starts from requirements section 7's *Was:* text, and would have to
  bring its own cache invalidation with it.
