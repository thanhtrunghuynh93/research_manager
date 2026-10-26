# ADR 0026 — Professor feedback, written through MCP and published to the student

Status: accepted — 2026-10-26

## Context

The MCP endpoint (ADR 0025) only reads. A professor who has asked Claude about a student's weeks
wants to keep the answer: save feedback on those reports, attach a document (an HTML or PDF write-up),
check it, and show it to the student. Migration 0027 removed an earlier, unread feedback feature; this
one is professor-initiated and the student only ever reads it.

## Decision

**A new module `app.feedback` holds feedback as drafts and revisions, and six MCP tools write it.**
It sits above `app.reporting` and below `app.mcp` in the layer order and calls services only.

- **Tools.** `create_feedback`, `upload_feedback_attachment`, `update_feedback`, `publish_feedback`
  write; `get_feedback`, `list_feedback` read. `list_workspaces` already existed. Every tool takes
  `workspace_id`; `call_tool` resolves it with `identity.service.scope_in` (ADR 0025), so a write
  goes to exactly the workspace named, and one the professor does not belong to is "not found".
- **A write needs its own grant.** ADR 0025 said writes would need their own scope. The token's
  scope string now carries `rms:feedback` besides `rms:read`; a client that names no scope is asked
  for both and the consent page says so. A token granted earlier has only `rms:read`, so a professor
  who consented to a read-only connector is not silently upgraded: the write tools answer with how
  to reconnect. Tool annotations say which tools write (`readOnlyHint: false`).
- **Revisions.** A feedback is an identity (`feedbacks`) with one `feedback_revisions` row per
  change: create, edit, adding a file, removing a file. `feedbacks.version` is the newest revision
  and is the token callers hand back as `expected_version`; a stale one is a 409/tool error. The
  row is locked (`FOR UPDATE`) while it is changed, so two writers take turns and the second is
  refused rather than merged. Revision content is never updated; only `published_at/by` are set.
- **Publishing.** `publish_feedback(expected_version)` points `feedbacks.published_version` at the
  revision the professor reviewed. A student's visibility predicates (`feedback/policies.py`) show a
  feedback only when it is published *to them*, and then only the published revision and its files.
  Editing afterwards makes a newer revision; students keep reading the published one until the next
  publish. There is no unpublish yet.
- **No notification.** Creating, uploading and publishing send nothing. `notify_student: true` is
  *refused*, not ignored, until a notification exists; the field is there so the contract does not
  change when it does.
- **Author and time are the backend's.** `author_id`, `created_at` and publish time come from the
  `Scope` and the clock. The schema has no author field, and an extra one in a call is dropped.
- **Reports.** A feedback is about one student's *submitted* reports (at least one), each with a
  section on the feedback's project. A report that is someone else's, a draft, in another
  workspace, or lacks the project is one error message, so ids cannot be probed.
- **Idempotency.** `create` and `publish` take an optional `idempotency_key`, kept in
  `feedback_idempotency` per (workspace, professor, operation, key). The first call under a key does
  the work; a later one returns the current state of the same feedback and writes nothing, including
  no second audit row. Claiming is `INSERT … ON CONFLICT DO NOTHING` inside a savepoint with the
  work, so concurrent first calls do not both proceed and a call that fails leaves no key behind. The
  same key with different arguments is refused.
- **Files.** `.html .pdf .docx .txt .md`, 20 MB (`RM_FEEDBACK_UPLOAD_MAX_FILE_MB`). The platform's
  upload is the presigned PUT of ADR 0010, split in two steps of one tool: `filename + byte_size +
  sha256` records a `pending` file and returns `upload_url`; the same tool with `attachment_id`
  re-reads the object, checks size, SHA-256 and that the bytes look like their extension (`%PDF-`, a
  zip with `word/document.xml`, UTF-8 without NUL), and only then marks it `ready` and puts it in a
  new revision. A file that fails is deleted from storage and stays `pending`, which no read lists, so
  a failed upload leaves no attachment. Confirming twice changes nothing. A connector that cannot
  make an HTTP PUT may send a file up to 2 MB inline as base64 (`RM_FEEDBACK_INLINE_UPLOAD_MAX_MB`);
  it runs the same two steps back to back, with the server computing the digest, so it proves storage
  integrity and not what the client held. No tool accepts a local path.
- **Downloads and HTML.** Files are private, in the workspace's prefix; a link is a presigned GET
  that lasts five minutes, issued after the visibility check (`get_feedback` for the professor,
  `GET /api/v1/feedback/attachments/{id}/download` for either role). The store always sets
  `Content-Disposition: attachment`, so an uploaded `.html` is downloaded, never rendered in the
  storage origin. **There is no HTML preview.** If one is added it must be a sandboxed iframe with no
  `allow-scripts` and a CSP of `default-src 'none'`, served from a different origin.
- **File text is data.** Nothing reads an attachment's contents into a tool result; the server
  never interprets them. The tool description and initialize instructions tell the model not to
  follow instructions found in files or student text.
- **Audit.** `feedback.created`, `.updated`, `.upload_requested`, `.attachment_added`,
  `.published`, each with the professor as actor, in the workspace written. The connector is named
  by the `mcp.tool_called` row of the same call (same `request_id`, `target_id` = the token).
  Bodies are not copied into the log; the title and the version are.
- **Reading, for students.** `GET /api/v1/feedback`, `/feedback/{id}` and the attachment download.
  A professor uses the same routes to see every feedback, drafts included. There are no write routes.

## Consequences

- Five new tables (migration 0032), all keyed on `workspace_id` with composite foreign keys, so a row
  cannot reference another workspace's student, project, feedback or file.
- `Tool` gains `requires_scope`, `idempotent` and `destructive`; `tools/list` annotations are per
  tool instead of all read-only. `McpContext` carries the granted scopes.
- Every revision stays: there is no way to delete a draft or a file's bytes through MCP. Removing a
  file from a draft only leaves it out of the next revision.
- `view_url` is `{RM_PUBLIC_URL}/feedback/{id}`, a page of the SPA (`/feedback` lists, `/feedback/:id`
  reads), for both roles: the API scopes what each sees. The body is rendered with `react-markdown`,
  which drops raw HTML and unsafe link schemes; files are download buttons, never opened in the page.
- The row lock and the key's unique index are tested with two real committed sessions
  (`tests/module/feedback/test_concurrency.py`), not only in the suite's single transaction. Those
  tests leave their workspace behind: submitted report versions are immutable, so it cannot be deleted.
- A key that was claimed and then abandoned cannot exist (savepoint), so keys never need expiry,
  but the table grows with use; a retention sweep is a later decision.
