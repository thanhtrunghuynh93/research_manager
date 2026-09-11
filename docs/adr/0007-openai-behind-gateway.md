# ADR 0007 — OpenAI GPT API behind a single internal gateway

Status: accepted — 2026-09-11

## Context

The professor chose the OpenAI GPT API for assessments and the assistant. The requirements
demand a documented AI data boundary, prompt and model versioning, cost control, per-project
restrictions, no credentials in prompts, and defence against instructions embedded in retrieved
text.

## Decision

`ai/gateway.py` is the only module that imports the OpenAI SDK (enforced by import-linter). It
owns the prompt registry with versions, structured outputs, the `ai_calls` cost ledger and
budgets, redaction, timeouts, and the untrusted-content framing. It exposes no tools or actions
to the model. A project flagged `ai_restricted` never reaches the gateway.

## Consequences

- Swapping or adding a provider touches one module and the prompt manifests.
- Every assessment records the prompt and model versions that produced it.
- Logs carry ids, token counts, and status only; never prompt or completion text.
