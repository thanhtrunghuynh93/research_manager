# ADR 0010 — Uploads are granted, then verified; extraction has three outcomes

Status: accepted — 2026-09-12

## Context

REP-04 asks for file attachments up to 25 MB, with the original preserved, text extracted, and
extraction failures marked. Architecture §5.6 puts the bytes in MinIO behind presigned URLs.

Two things had to be decided that neither document settles.

First, what the application is authoritative about. If the API streams the file, a 25 MB upload
occupies a worker process for its whole duration and the host's concurrency is set by the slowest
student's connection. If the API only issues a URL, the application never sees the bytes and has to
take the client's word for what was uploaded.

Second, what to record when a file cannot be read. The obvious schema has two states — extracted or
not — and that collapses two situations that mean opposite things.

## Decision

**Granted, then verified.** The API validates the size and the declared SHA-256, issues a presigned
PUT for exactly one key, and returns. The browser uploads directly. A second call then confirms:
the server reads the stored object, recomputes the checksum, and refuses if it does not match what
was declared. A presigned URL is a grant, not a fact; nothing counts as attached until the bytes are
there and are the bytes that were promised.

Keys are derived from ids and the content hash, never from the filename, and only recognised
extensions are carried through. A filename is user input; a key is a path.

**Three extraction outcomes, not two.**

- `ok` — the text is here.
- `unsupported` — this file has no text to extract and that is expected. A figure is evidence
  whether or not OCR ever arrives; a scanned PDF has no text layer.
- `failed` — we should have been able to read this and could not.

Only `failed` reduces the evidence coverage of the assessment that leans on it (ASSESS-06), and
every state carries a note in words the coverage summary can use.

Versions are kept. Replacing a figure creates version 2 and leaves version 1 readable, because an
assessment that cited version 1 has to be able to open version 1 (ASSESS-09).

## Consequences

- A 25 MB transfer never touches the application process, and the same path serves a 200 KB figure
  and a large dataset.
- A client that uploads different bytes than it declared gets a refusal rather than a silent
  correction: a mismatch means we do not know which file this is.
- An abandoned upload leaves an unconfirmed `artifact_versions` row and possibly an orphan object.
  Both are harmless — the row is not `uploaded` and nothing cites it — and both are retention's
  problem rather than the upload path's.
- The extraction distinction is what stops a week being read as empty when it was merely
  unreadable, which is the unfairness nobody would have noticed.
- Text is indexed with the artifact's own label (`student_private`), so a project-mate cannot
  retrieve through search what they cannot open directly.
