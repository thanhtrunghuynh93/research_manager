# ADR 0006 — Rubric arithmetic outside the language model

Status: accepted — 2026-09-11

## Context

ASSESS-04, ASSESS-05, ASSESS-09, and QA-02 require deterministic, reproducible numbers and forbid
the model from doing the arithmetic. Language models are unreliable at weighted sums and rounding
and cannot be replayed exactly.

## Decision

The model returns only per-dimension ratings (0–4 or `unknown`), rationales, and evidence
reference ids, through a structured-output JSON schema. `assessment/metrics.py` computes the
progress index, plan completion, coverage, and confidence with `Decimal` arithmetic and
round-half-up. `validate_output` drops any evidence id not in the snapshot and downgrades the
affected rating to `unknown`.

## Consequences

- The specification's worked example (ratings 3, 4, 3, 2 → 78.75 → 79) is a unit test.
- A rubric or weight change is a `rubric_versions` row, and trends are grouped by that version.
- A fabricated citation cannot reach the professor as support for a rating.
