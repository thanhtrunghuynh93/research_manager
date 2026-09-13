# ADR 0008 — The assistant computes facts in SQL, never through the model

Status: accepted — 2026-09-12

## Context

The professor's most common questions have exact answers already sitting in the database: how many
reports are missing, when the next deadline is, who is on a project, how many drafts are waiting.

A language model handed the week's records will produce a number for any of these, and it will
often be the right one. That is the problem. An answer that is usually correct, with no way to tell
from the answer which time it is, is worse than one that is reliably absent — the professor acts on
it either way, and the one time it is wrong is invisible.

Requirements QA-02 says to use permission-filtered structured queries for exact dates, counts,
deadlines, membership and scores, and to perform numerical calculations with deterministic code.
AC-15 makes it a scenario: the count of missing reports must match the obligations table after
exemptions and deadline rules, with an explicit as-of time.

## Decision

Registered fact functions compute every number, in SQL, through the owning module's `service.py` so
they compile the same permission predicate as every other read.

The router may *name* a fact function; it may not invent one. A name not in the registry is dropped
rather than approximated, because answering a near-neighbour of the question asked is worse than
answering nothing.

For a question the router classifies as `fact`, the generation step is not called at all: the
answer is rendered from the fact, its `as_of`, and the rule that produced it. For a mixed question,
the facts are given to the generation step as authoritative and the prompt forbids recomputing
them, but what reaches the professor as a number still comes from the fact, in its own field of the
answer contract, rendered apart from the prose.

Every fact carries the instant it was true. "Three missing" is not a fact without an as-of.

## Consequences

- The answer to "how many reports are missing" cannot drift, cannot be rounded, and cannot be
  softened. The AC-15 tests script the fake gateway to answer "seven" so that passing proves the
  generation step was never consulted.
- The dashboard and the assistant cannot disagree: the professor overview is built from the same
  functions.
- Adding a question kind means adding a fact function, which is more work than extending a prompt.
  That is the intended trade: a question the system cannot answer exactly is one it should say it
  cannot answer.
- A fact function that fails takes only its own fact with it; the rest of the answer still stands,
  and the gap is stated.
