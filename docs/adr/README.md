# Architecture decision records

One file per decision, numbered, never edited after acceptance except to mark it superseded.
Format: Context, Decision, Consequences. Keep each under a page.

Every file in this directory appears below; `scripts/check_docs.py` asserts it, because an index
that silently stops is worse than no index — a reader takes the last row for the last decision.

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
| [0012](0012-workspace-ownership.md) | Ownership is the workspace administration relation (amends 0011) |
| [0013](0013-active-workspace-on-the-session.md) | *Superseded by 0014* — which workspace you are in was a property of the session |
| [0014](0014-joining-and-leaving-a-workspace.md) | An account joins and leaves a workspace; four identity foreign keys cascade (supersedes 0013) |
| [0015](0015-plural-workspace-membership.md) | Belonging to a workspace is plural; working in one is singular |
| [0016](0016-reads-span-membership.md) | *Superseded by 0020* — reads spanned every workspace you belong to; writes went to one |
| [0017](0017-students-own-their-projects.md) | A student starts and joins their own projects; the professor keeps the gate |
| [0018](0018-project-documents-are-shared-with-the-project.md) | A project's documents belong to the project, not to whoever uploaded them |
| [0019](0019-ending-a-membership-is-the-professors.md) | Ending a membership is the professor's, and a finished project owes no week (amends 0017) |
| [0020](0020-reads-follow-the-workspace-you-are-in.md) | Reads follow the workspace you are working in (supersedes 0016) |
