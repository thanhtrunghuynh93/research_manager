# Architecture decision records

One file per decision, numbered, never edited after acceptance except to mark it superseded, withdrawn or amended. A superseded or withdrawn ADR is history: it describes no running code.
Format: Context, Decision, Consequences. Keep each under a page.

Every file in this directory appears below; `scripts/check_docs.py` asserts it, because an index
that silently stops is worse than no index — a reader takes the last row for the last decision.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-modular-monolith.md) | Accepted | Modular monolith with enforced module boundaries |
| [0002](0002-postgres-job-queue.md) | Accepted | Postgres-backed job queue (procrastinate) instead of Redis/Celery |
| [0003](0003-pgvector-in-postgres.md) | Superseded by 0024 | Full-text and vector search inside Postgres (pgvector) |
| [0004](0004-application-level-authorization.md) | Accepted | Authorization in one application policy layer; RLS deferred |
| [0005](0005-github-app-connector.md) | Withdrawn by 0022 | GitHub App as the first repository connector |
| [0006](0006-deterministic-metrics.md) | Accepted | Rubric arithmetic outside the language model |
| [0007](0007-openai-behind-gateway.md) | Accepted | OpenAI GPT API behind a single internal gateway |
| [0008](0008-facts-outside-the-model.md) | Withdrawn by 0023 | The assistant computes facts in SQL, never through the model (the rule lives on in `app.overview`) |
| [0009](0009-access-epoch-for-cached-answers.md) | Superseded by 0023 | A counter, not an invalidation sweep, expired cached answers |
| [0010](0010-presigned-uploads-verified-after-the-fact.md) | Accepted | Uploads are granted, then verified; extraction has three outcomes |
| [0011](0011-co-equal-professors.md) | Accepted; amended by 0012 | Professors are co-equal; the role is fixed at acceptance |
| [0012](0012-workspace-ownership.md) | Accepted | Ownership is the workspace administration relation (amends 0011) |
| [0013](0013-active-workspace-on-the-session.md) | Superseded by 0014 | Which workspace you are in was a property of the session |
| [0014](0014-joining-and-leaving-a-workspace.md) | Accepted; amended by 0015 and 0022 | An account joins and leaves a workspace; the identity foreign keys cascade and the history keys refuse (supersedes 0013) |
| [0015](0015-plural-workspace-membership.md) | Accepted | Belonging to a workspace is plural; working in one is singular (amends 0014) |
| [0016](0016-reads-span-membership.md) | Superseded by 0020 | Reads spanned every workspace you belong to; writes went to one |
| [0017](0017-students-own-their-projects.md) | Accepted; amended by 0019 | A student starts and joins their own projects; the professor keeps the gate |
| [0018](0018-project-documents-are-shared-with-the-project.md) | Accepted | A project's documents belong to the project, not to whoever uploaded them |
| [0019](0019-ending-a-membership-is-the-professors.md) | Accepted | Ending a membership is the professor's, and a finished project owes no week (amends 0017) |
| [0020](0020-reads-follow-the-workspace-you-are-in.md) | Accepted; amended by 0021 | Reads follow the workspace you are working in (supersedes 0016) |
| [0021](0021-the-read-set-is-one-workspace.md) | Accepted | The read-set is one workspace; the spanning seam is removed (amends 0020) |
| [0022](0022-no-repository-connector.md) | Accepted | No repository connector: students link a repository and attach their evidence (withdraws 0005, corrects 0014's history keys) |
| [0023](0023-no-research-assistant.md) | Accepted | No research assistant: the overview computes its own numbers; the access epoch goes with the cache (withdraws 0008, supersedes 0009) |
| [0024](0024-no-embeddings.md) | Accepted | No embeddings: indexing is chunking; pgvector and the full-text column are dropped (supersedes 0003) |
