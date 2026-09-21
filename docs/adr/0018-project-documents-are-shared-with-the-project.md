# ADR 0018 — A project's documents belong to the project, not to whoever uploaded them

Status: accepted — 2026-09-21
Extends: [ADR 0017](0017-students-own-their-projects.md)

## Context

PROJ-01 has listed "shared resources" among a project's fields since the first specification, and
nothing has ever written one. A student with a protocol, a dataset description or the paper their
project replicates had two places to put it, and neither was the project: a weekly report, where it
became that week's private evidence, or a corridor.

The machinery was already there. `artifacts` carries a nullable `project_id`, `period_id` and
`entry_id`, `POST /artifacts/uploads` has always taken a project id, and the presigned upload path
does not care what the file is for. What stopped a project document existing was one predicate:

    return and_(same_workspace, Artifact.owner_student_id == scope.user_id)

and the reason written above it — *"Project membership is deliberately not enough. An attachment
supports one student's report, and a report is private to its author and the professor."*

That reason is right about report evidence and says nothing about a document that supports the
project. The two had no way to be told apart, so the narrow rule covered both.

## Decision

**A file attached to a project and to no week is readable by everyone on that project.** Any member
may attach one; whoever attached it may remove it, which is the rule report evidence already has.

The two kinds are told apart by what they are *not* attached to:

| | `project_id` | `period_id` | `entry_id` | Who reads it |
| --- | --- | --- | --- | --- |
| Report evidence | set | **set** | set once submitted | its author, and the professor |
| Project document | set | **null** | null | everyone on the project, and the professor |

Both columns are tested rather than `entry_id` alone. A draft week's attachment has no entry either
— the entry is written at submission — so keying on `entry_id` would have shared every unsubmitted
file with the whole project, which is the leak the old rule existed to prevent, arriving as a
refactor.

Three things follow, and each is a choice rather than a consequence of the schema:

- **The grant is the membership, not the workspace.** A student enrolled in the workspace but not
  on the project sees nothing, and the download refuses for the same reason the list omits it.
- **Removal stays with the uploader.** A professor can read every document and remove none, exactly
  as with report evidence (REP-04). The file is the uploader's to take back.
- **Nothing is extracted or indexed.** A project document is not evidence for a week, so it is not
  read into `evidence_references`, does not enter retrieval, and cannot be cited by an assessment
  or the assistant. Its extraction state stays `pending`, and the badge says "Uploaded", which is
  what has happened. Making it citable is a larger decision about what the model may read, and it
  is not this one.

## Consequences

- **What a membership grants grows by one kind of record.** ADR 0017 enumerated it — the project
  record, milestones, tasks, decisions, the member list — and this adds the project's documents.
  The enumeration is the point: the set is small enough to write down, and that is what makes
  opening a project to joining a decision a professor can actually weigh.
- **A professor who opens a project to joining now opens its documents too.** This is the sharpest
  edge, and it is the same edge ADR 0017 recorded for task blockers and the member list. It is
  bounded by `open_to_join`, which defaults false.
- **An upload no longer implies a week.** Code that assumed every artifact has a period — a report
  reading its attachments, an evidence snapshot gathering a week's files — must filter rather than
  assume, and both already do, because both key off the entry.
- **The predicate is one function with a branch in it**, not a second predicate. ADR 0004's single
  builder holds: `artifact_visible_to` still answers for every artifact, and the widening is
  visible in one diff of one function.
