# The Research Management Framework — Problem, Innovation, Impact

Version 0.5 — 7 October 2026 — a short account of what this framework is for and what is new in it.
It summarises [research_management_requirements.md](research_management_requirements.md) v0.14,
[architecture.md](architecture.md), the [ADRs](adr/) and
[implementation_status.md](implementation_status.md); those documents are authoritative where this
one abbreviates them.

## Abstract

Research supervision is an evidence problem before it is a management problem: a professor meeting
ten students each week must reconstruct, from memory and from prose, what was actually done and
what supports it. The available instruments are either administrative — trackers that record
activity but not research reasoning — or generative: a language model handed the week's material,
which will produce a plausible account of progress whether or not the evidence exists. This
framework's unit of record is one student, on one project, in one reporting week, assessed against
a plan frozen before the week began and a permission-labelled snapshot of the evidence available for
it. A model rates and explains; every number, count and date is computed in SQL or Python; a
citation that is not in the snapshot cannot reach the professor; and nothing is published to a
student until a professor approves it. Absence of evidence is representable — as `unknown`, as
withheld coverage, as a stated gap — so the record can be trusted because it declines to answer.

## 1 The problem

A professor must answer four questions every week: what did each student accomplish, what evidence
supports that account, where is the research blocked, and what should be discussed next
(requirements §1). Four gaps make existing instruments unsuitable.

1. **Activity is not progress.** Report length and file counts are easy to collect and least related
   to research value. A literature week, a theory week and a rigorous negative result produce little
   output and can be the most valuable weeks of a term; verbose prose and piles of attachments can be
   produced without new evidence (AC-14).
2. **Plans are reconstructed after the fact.** Without a plan frozen before the week, "did the
   student do what was agreed?" is answered from whatever the student now says was agreed.
3. **A confident wrong answer is worse than a missing one.** A model asked to score a week will
   score it; fabricated citations and an index computed from missing evidence look exactly like
   correct ones.
4. **Supervision records are confidential and easy to leak.** One student's private report and
   another's assessment sit in the same store; access changes when a membership ends (AC-11); and an
   attached file can contain instructions addressed to the model that reads it (AC-12).

## 2 The framework in brief

**People and workspaces.** Professors and students meet in a workspace, the tenant boundary. A
professor may belong to several and works in one at a time; a student belongs to exactly one.
Professors are co-equal ([ADR 0011](adr/0011-co-equal-professors.md)). Students may start projects
and join ones a professor has opened; ending a membership is the professor's
([ADR 0017](adr/0017-students-own-their-projects.md), [ADR 0019](adr/0019-ending-a-membership-is-the-professors.md)).

**Weekly cycle.** A versioned weekly schedule derives each week's obligations from membership dates,
project status and exemptions; last week's next-week plan freezes as this week's baseline; the
student submits one package with an entry per project and attached files; a missed deadline sends one
email at 00:00 on the meeting day; the submission is versioned immutably, its attachments extracted
and indexed; an evidence snapshot is built through the student's own view; claims are extracted and
matched; the rubric is applied and metrics computed; a draft enters the professor's review queue;
approval publishes it to the student (requirements §10, architecture §9).

**Rubric.** Four dimensions — progress toward agreed outcomes (30%), research learning and reasoning
(30%), rigor and evidence quality (25%), usable research artifacts (15%) — each rated 0–4 against
stage-specific anchors, with a 0–100 progress index as a supervision aid, not a grade
(ASSESS-03, ASSESS-04). Commitment completion against the frozen plan is reported separately
(ASSESS-05).

**Overview.** The professor's week — next deadline, who is outstanding, the week's reports, the
review queue and stalled analyses — computed from the records with an explicit as-of instant
(UI-01, REP-08, AC-15).

**Implementation.** A modular monolith — FastAPI, PostgreSQL 16, a Postgres-backed job queue, MinIO,
a React SPA — on a single host, sized for fifty students and thirty active projects per workspace.
The model provider is reachable from exactly one module, and only the assessment calls it.

## 3 Innovation

The novelty is the boundary between deterministic records and generative interpretation, enforced by
schema and tests rather than by prompt instructions.

- **I1 — The model never produces a number.** Counts, dates, deadlines and memberships come from the
  owning module's queries under the same permission predicate as every other read; in an assessment
  the model returns ratings, rationales and evidence ids, and every figure is derived from them.
- **I2 — Rubric arithmetic lives outside the model, and unknown is not zero.** `metrics.py` computes
  index, completion, coverage and confidence in `Decimal` with round-half-up
  ([ADR 0006](adr/0006-deterministic-metrics.md)). If any applicable dimension is `unknown` the
  index is withheld (*Not rated — insufficient evidence*). The specification's worked example —
  3, 4, 3, 2 giving 78.75, displayed 79 — is a unit test.
- **I3 — Fabricated citations cannot survive validation.** Every evidence id not in the snapshot is
  dropped and the affected rating downgraded to `unknown` with a reason. The gateway offers the model
  no tools, and every attached text is framed as data, so an injection attempt is text (AC-12). A
  claim reaches the professor only as supported, partially supported, unsupported or unverifiable
  (ASSESS-07).
- **I4 — Coverage and confidence are first-class, with rule-based reasons** (ASSESS-06). A project
  with no code can reach full coverage (AC-05). Extraction has three outcomes — `ok`, `unsupported`,
  `failed` — so only a genuine read failure reduces coverage
  ([ADR 0010](adr/0010-presigned-uploads-verified-after-the-fact.md)).
- **I5 — Access is compiled on every request.** The readable projects come from the memberships
  table per request and nothing caches a read, so an ended membership is out of every read at once
  (AC-11).
- **I6 — Approval, immutability and provenance are the publication contract.** Drafts are visible
  only to the professor; an override records its reason beside the original output (ASSESS-08).
  Every version stores rubric, prompt, model, report and evidence versions; a resubmission
  re-assesses only changed entries (ASSESS-09, AC-17); trends break at a rubric change (AC-10).
- **I7 — Evidence belongs to whoever supplied it, and a week is the week it is about.** An attachment
  is indexed private to its student (AUTH-02, AC-02), and a late entry still belongs to the week it
  describes (ASSESS-01).

## 4 Impact

**For the professor.** Reviewing a cited draft replaces reconstructing a week; "who is missing" is
the obligations table after exemptions, with an as-of instant; a trajectory across a rubric change
shows the break.

**For the student.** The basis of an assessment is inspectable: the frozen plan, the ratings with
rationales, the cited evidence and the stated limitations. A student who disputes a rating raises it
with the professor, who can override it with a recorded reason. Negative and theoretical results are
creditable without code, and unavailable evidence never becomes a zero.

**For the group.** Reports, plans, attachments and assessments accumulate as versioned,
permission-labelled records that outlive the model reading them (requirements §11, Portability).

**Deliberately not done.** Automatic grading, leaderboards, plagiarism or authorship judgments, code
execution and institutional administration (requirements §1). Several features were built and
withdrawn unused — a repository connector, a chat assistant, embeddings, tasks and milestones; the
list is in [implementation_status.md](implementation_status.md) §2.

## 5 How the impact is measured

The [evaluation protocol](evaluation/protocol.md) separates two questions. **Contract properties** —
the index withheld when evidence is absent, no citation outside the snapshot, an instruction inside an
attachment treated as text — are pass/fail and run on every CI pass against a deterministic gateway.
**Agreement with the professor** is a calibration question: it needs the real provider and the
professor's ratings, and is reported, not asserted — per-dimension exact and within-one agreement,
material correction rate, citation support, uncertainty behaviour, injection resistance, run-to-run
variation. Pilot gates: at least 30 professor-rated student–project–weeks, exact counts and dates
matching the database, all authorization scenarios passing, citation support ≥ 95 %, an uncertainty
response on every incomplete-evidence case, and an agreement threshold agreed with the professor.

**Limitations.** The ten seed cases carry the specification's anchors applied by the set's author, not
the professor's judgement, so agreement numbers check the prompt rather than the rubric. The weights
and anchors are proposals. The latency targets have not been benchmarked, and the rubric's construct
validity is a question the pilot opens rather than settles.
