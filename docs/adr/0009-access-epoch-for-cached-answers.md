# ADR 0009 — A counter, not an invalidation sweep, expires cached answers

Status: accepted — 2026-09-12

## Context

An answer is expensive to produce and the same question gets asked twice in a meeting, so caching
is worth having. But a cached answer is a record of what someone was allowed to know at the moment
it was written, and serving it later is a fresh disclosure decision.

AC-11 is the scenario: a student's membership is removed after an answer was cached, and subsequent
access to the restricted underlying content, its citations, and the cached answer must be denied.

The obvious implementation is an invalidation sweep — on every membership change, find and delete
the answers that touched it. It is also the wrong one. It has to be correct at the moment of the
change, it has to know which answers touched which records, and if it misses one the failure is
silent and looks exactly like normal operation.

## Decision

`workspaces.access_epoch` increments inside the same transaction as any membership end, user
deactivation, role change, or visibility change. Every cached answer and every evidence snapshot
records the epoch it was built under.

A cached answer is served only when its epoch equals the workspace's current one. Nothing has to
find it; it simply stops matching.

The cache key includes the asker as well as the question, because two people may ask the same words
and be entitled to different answers.

A second, finer check runs on top: each citation is re-checked against the caller's current scope
before the answer is served, which catches an individual record that moved out of reach without the
epoch moving. Cheap and coarse first, then precise — both, because either alone has a gap.

Snapshots keep their epoch but are not invalidated: they are historical records of what an
assessment considered. A student's view of an assessment re-checks each citation at render time and
shows "source no longer available to you" for anything that fails.

## Consequences

- The failure mode is over-invalidation, not under-invalidation. A membership change expires every
  cached answer in the workspace, including ones it did not affect. For a workspace of fifty
  students that is a few wasted regenerations a term, which is the right thing to trade.
- Correctness does not depend on a sweep running. `purge_stale` exists and is housekeeping only.
- The rule is legible: one integer decides it, and the column is in the answer, the snapshot, and
  the Scope. Reviewing whether a change is covered means asking whether it advances the epoch.
- Any future cache — rendered exports, a materialised dashboard — gets the same property by
  recording the same column.
