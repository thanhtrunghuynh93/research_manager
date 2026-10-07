# ADR 0003 — Full-text and vector search inside Postgres

Status: superseded by [ADR 0024](0024-no-embeddings.md) — 2026-10-07 (accepted 2026-09-11). Nothing reads embeddings or the full-text column after ADR 0023; both are dropped with the extension.

## Context

Retrieval must be permission-filtered before ranking, cite exact source versions, and handle about
100k evidence chunks. A separate vector database or OpenSearch would add a second store whose
access labels must be kept in sync with Postgres.

## Decision

`evidence_chunks` lives in Postgres with a generated `tsvector` (GIN index) and a `pgvector`
embedding (HNSW index). One SQL statement applies the `visible_to` predicate, then fuses
full-text rank and cosine distance.

## Consequences

- Authorization is one predicate builder for records and retrieval; there is no second model to drift.
- Citations resolve through a foreign key to `evidence_references`, so a chunk always knows its
  source version.
- At millions of chunks, partitioning by year or a dedicated store may be needed; the retrieval
  module isolates that change.
