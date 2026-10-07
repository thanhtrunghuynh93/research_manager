# ADR 0024 — No embeddings

Status: accepted — 2026-10-07
Supersedes: [ADR 0003](0003-pgvector-in-postgres.md)

## Context

ADR 0003 put the evidence index's search inside Postgres: a generated `tsvector` with a GIN index
and a `pgvector` embedding with an HNSW index, fused into one ranked, permission-filtered query.
The only caller of that query was the research assistant's hybrid retrieval, and the assistant was
removed in ADR 0023.

What remained was the cost side. Every chunk of every submitted report entry and every extracted
attachment was still embedded at index time — a paid call to the model provider on the student's
upload path, which once took submissions down when the provider ran out of credit — and the vectors
were written to a column nothing read. The full-text column was the other half of the same search
and had no reader either. A project marked `ai_restricted` needed its own embedder so its text
would not reach the provider at index time, and the gateway needed an `embed` method, a vector
cache and ledger rows for it.

The assessment snapshot reads chunk *text* — by time window, by source, by reference — through the
B-tree on `(workspace_id, project_id, visibility, source_time)`. None of those reads ranks anything.

## Decision

**There are no embeddings and no full-text search.** Indexing is chunking: a report entry or an
attachment's extracted text becomes `evidence_chunks` rows carrying their source's access label, and
nothing else. Removed: the embedder registry and cache, the gateway's `embed`, the restricted
project's local embedder, the embedding prices and the `RM_OPENAI_EMBED_MODEL` setting, the
`pgvector` package, and — in migration 0030 — `evidence_chunks.embedding` with its HNSW index,
`evidence_chunks.tsv` with its GIN index, and the `vector` extension.

The database then needs nothing beyond stock PostgreSQL 16, so the compose service moves from
`pgvector/pgvector:pg16` to `postgres:16-bookworm` — the base the pgvector image is built on — in a
follow-up change, deployed after 0030 has run (docs/runbooks/deploy.md).

## Consequences

- No project's text leaves the host when it is indexed. `ai_restricted` still governs the one step
  that calls a provider, the assessment, which uses the gateway that calls nobody.
- Uploads and submissions no longer wait on, or pay for, a provider call.
- Chunking stays: chunks are what an assessment cites, and citations resolve through
  `evidence_references` exactly as before.
- Bringing similarity search back means a new embedding column, a backfill of every existing chunk,
  and the extension again; downgrading 0030 restores the column empty and on the pgvector image only.
