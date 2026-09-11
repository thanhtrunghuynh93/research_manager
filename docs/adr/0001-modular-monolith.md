# ADR 0001 — Modular monolith with enforced module boundaries

Status: accepted — 2026-09-11

## Context

One professor, up to 50 students, one VPS. The requirements describe seven bounded contexts
(identity, projects, reporting, evidence, assessment, assistant, notifications) plus an AI gateway.
Separate services would multiply deployment, authorization, and transaction boundaries for no
capacity benefit at this scale.

## Decision

One FastAPI codebase deployed as two processes (api, worker). Each bounded context is a package
with a fixed file shape; cross-module access goes only through `service.py`; reactions go through
in-process domain events. The dependency direction
`core → identity → projects → reporting → evidence → assessment → assistant` is enforced by
import-linter in CI, as are the rules that only `assessment` and `assistant` may use `ai`, and that
only `ai.gateway` may import the OpenAI SDK.

## Consequences

- Transactions can span a report write and its job enqueue, which is how "no report loss" is met.
- A module can be extracted into a service later because its public surface is already `service.py`.
- Violating the layering fails CI rather than being discovered in review.
