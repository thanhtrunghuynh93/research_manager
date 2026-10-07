# ADR 0022 — No repository connector

Status: accepted — 2026-10-07
Withdraws: [ADR 0005](0005-github-app-connector.md)
Corrects: [ADR 0014](0014-joining-and-leaving-a-workspace.md) (the history keys)

## Context

ADR 0005 chose a GitHub App as the first repository connector, and REPO-01..08 specified what it
had to do: sync commits, pull requests, reviews and issues; map provider accounts to students;
attribute each event to an author, reviewer or merger; tell work merged this week from work written
earlier. All of it was built — a connector protocol, a GitHub client, a fake for tests, webhooks,
a half-hourly incremental sync, identity mapping, contribution attribution, an admin sync screen
and an overview section for stale repositories.

None of it was ever connected. On the running deployment `repositories`, `project_repositories`,
`sync_runs`, `repository_events`, `contributions`, `developer_identities` and
`webhook_deliveries` were all empty, while the periodic sync had run some 775 times over nothing.
Meanwhile a project could already record its repository as a plain link (migration 0024), and
students attach the files they want read to their reports. The connector carried a secret, a bind mount,
a webhook endpoint, eight enum types, a guard trigger, a confidence rule and a snapshot pass, and
every change near evidence had to keep all of them working.

## Decision

**There is no repository connector.** The connector, its tables, routes, jobs, settings and
screens are removed (migration 0028; requirements 0.11 withdraws REPO-01..08 and AC-04, AC-06,
AC-09). What replaces it is what the product already offered:

- A project names its repository as `projects.repo_url`, a link for the people on the project.
  Nothing reads it and nothing is attributed from it (PROJ-01).
- Code, results or a commit log a student wants assessed is attached to the weekly report. It is
  extracted, indexed as `student_private` evidence owned by that student, and cited like any other
  attachment (REP-04).

The evidence index stays: `evidence_references` and `evidence_chunks`, indexing on report
submission and attachment extraction, retrieval, and the citation-open route, which moves from
`api/v1/repositories.py` to `api/v1/evidence.py`.

## Consequences

- **Two history keys, not four.** ADR 0014 named four non-cascading composite keys onto `users`
  that pin a student who has written anything: `project_memberships`, `weekly_reports`,
  `developer_identities`, `contributions`. The last two are dropped, so the rule "history stays in
  the workspace it was written in" now rests on memberships and reports. Behaviour is unchanged: a
  student with either is still refused a move (AUTH-06), and one with neither still moves.
- Attachments belong to the student who attached them, so there is nothing to attribute and no
  joint/merger distinction to keep (AC-06 is withdrawn, not failed).
- Assessment confidence loses its stale-repository and unresolved-attribution rules; a project
  with no code was already not a gap in coverage. The snapshot's second pass for work "authored
  earlier, merged this week" is gone; `integration_lag_days` and `integration_of_earlier_work`
  stay as columns for the rows written before and are now 0 and false.
- `evidence_source_kind` keeps its `repository_event` label: dropping a label means rebuilding the
  type under `evidence_references`, which has rows. Nothing writes it.
- The professor's overview loses its repository sync section, `/admin/sync` and the assistant's
  stale-repository fact go, and `/api/metrics` no longer exports `rm_sync_staleness_seconds` or
  `rm_repositories`.
- Deploying this needs no secret: `RM_GITHUB_*` and `infra/secrets/github-app.pem` can be removed
  from a host once the release is running.
- If a pilot later wants repository evidence, it is a new decision against this context — reading
  a repository the student names, under their own authority, may well be simpler than an App.
