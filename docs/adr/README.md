# Architecture decision records

One file per decision, numbered, never edited after acceptance except to mark it superseded.
Format: Context, Decision, Consequences. Keep each under a page.

| ADR | Decision |
| --- | --- |
| [0001](0001-modular-monolith.md) | Modular monolith with enforced module boundaries |
| [0002](0002-postgres-job-queue.md) | Postgres-backed job queue (procrastinate) instead of Redis/Celery |
| [0003](0003-pgvector-in-postgres.md) | Full-text and vector search inside Postgres |
| [0004](0004-application-level-authorization.md) | Authorization in one application policy layer; RLS deferred |
| [0005](0005-github-app-connector.md) | GitHub App as the first repository connector |
| [0006](0006-deterministic-metrics.md) | Rubric arithmetic outside the language model |
| [0007](0007-openai-behind-gateway.md) | OpenAI GPT API behind a single internal gateway |
| [0008](0008-facts-outside-the-model.md) | The assistant computes facts in SQL, never through the model |
| [0009](0009-access-epoch-for-cached-answers.md) | A counter, not an invalidation sweep, expires cached answers |
| [0010](0010-presigned-uploads-verified-after-the-fact.md) | Uploads are granted, then verified; extraction has three outcomes |
| [0011](0011-co-equal-professors.md) | Professors are co-equal; the role is fixed at acceptance |
