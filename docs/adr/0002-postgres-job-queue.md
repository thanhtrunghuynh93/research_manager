# ADR 0002 — Postgres-backed job queue (procrastinate)

Status: accepted — 2026-09-11

## Context

Section 10 of the requirements demands: persist the report first, run jobs asynchronously, bounded
retries, idempotent job keys, manual retry without duplicates, and distinguishable job states.
Options: Celery + Redis, arq + Redis, or a Postgres-backed queue.

## Decision

procrastinate with the psycopg connector, running in the worker process, which also hosts the
periodic tasks. Every defer uses a `queueing_lock` built by `core.jobs.key()`.

## Consequences

- Enqueue is a row insert in the same transaction as the domain write; a crash cannot leave a
  submitted report without its pipeline jobs, or jobs for a report that was never committed.
- No Redis to run, back up, or secure. Postgres is the single stateful service besides MinIO.
- Queue throughput is bounded by Postgres, which is ample at 50 students. If the queue ever
  becomes a bottleneck, the job functions are plain callables and can move to another executor.
- A second queued job with the same lock is refused, which gives idempotency for webhooks and retries.
