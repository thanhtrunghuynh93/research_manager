# The Research Management Framework — Problem, Innovation, Impact

Version 0.1 — 18 September 2026 — an overview of what this framework is for and what is new in it.
It summarises [research_management_requirements.md](research_management_requirements.md) v0.6,
[architecture.md](architecture.md) v0.4, the seventeen [ADRs](adr/), and
[implementation_status.md](implementation_status.md); those documents remain authoritative where
this one abbreviates them.

## Abstract

Research supervision is an evidence problem before it is a management problem: a professor meeting
ten students each week must reconstruct, from memory and from prose, what was actually done and
what supports it. However, the instruments available for this are either administrative — task
trackers and learning-management systems that record activity but not research reasoning — or
generative: a language model handed the week's material, which will produce a plausible account of
progress whether or not the evidence exists. To this end, we propose a supervision framework whose
unit of record is one student, on one project, in one reporting week, assessed against a plan frozen
before the week began and a permission-labelled snapshot of the evidence available for it. The
framework separates what a model may do from what only code may do: a model rates and explains,
while every number, every count and every date is computed deterministically in SQL or in Python,
and a citation that is not in the snapshot cannot reach the professor. Assessments are drafts until
a professor approves them, and every published figure carries the rubric, prompt, model, report and
evidence versions it was produced from. In essence, our idea is to make absence of evidence
representable — as `unknown`, as withheld coverage, as a stated gap — so that a supervision record
can be trusted precisely because it declines to answer.

## 1 The problem

A professor supervising a research group must answer four questions every week: what did each
student accomplish, what evidence supports that account, where is the research blocked, and what
should be discussed next (requirements §1). Answering them well is expensive, and answering them
badly is invisible. Four gaps make the existing instruments unsuitable.

**(1) Activity is not progress.** Commit counts, lines changed and report length are the signals
that are easy to collect, and they are the signals least related to research value. A literature
review week, a theory week and a rigorous negative result all produce little or no repository
activity, and each can be the most valuable week of a term. Conversely, repetitive commits and
verbose prose can be produced without new substantive evidence (AC-14). Any framework that scores
what it can count will reward the wrong weeks, and it will do so consistently enough that students
learn to produce them.

**(2) Plans are reconstructed after the fact.** Without a plan frozen before the week, "did the
student do what was agreed?" is answered from whatever the student now says was agreed. Retrofitted
agreement is unfalsifiable, and it quietly erases missed commitments as scope is restated.

**(3) A confident wrong answer is worse than a missing one.** This is the gap that motivates most of
the design. A language model asked how many reports are missing will answer, and it will usually be
right; nothing in the answer distinguishes the usual case from the exception, and the professor acts
on it either way ([ADR 0008](adr/0008-facts-outside-the-model.md)). The same holds for fabricated
citations, for an index computed from missing evidence, and for a stale repository read as a week of
no work. Each of these fails by producing something plausible, which is the worst available failure
mode for a record that a person's standing depends on.

**(4) Supervision records are confidential in a way that is easy to leak.** One student's private
report, another's individual assessment, and the professor's own supervision notes sit in the same
store and feed the same retrieval index. Access changes retroactively: a membership ends, and every
cached answer built under the old membership is a fresh disclosure the next time it is served
(AC-11). Retrieved text is itself untrusted — a README can contain instructions addressed to the
model that reads it (AC-12).

Against this background, the framework treats supervision as a records problem with an AI component
bounded inside it, rather than as an AI application with records attached.

## 2 The framework in brief

**Unit of record.** One student × one project × one reporting week. A student submits a single weekly
package containing one entry per project they owe (REP-02); assessments remain separate per
student–project–week, and the framework does not collapse different projects into one ranking score
(ASSESS-01, ASSESS-02).

**Weekly cycle.** Obligations are derived from membership dates, project status and exemptions; the
plan submitted last week freezes as this week's baseline; the package is accepted and versioned
immutably; repository activity and attachments are ingested; a permission-labelled, time-bounded
evidence snapshot is built; claims are extracted and matched to that snapshot; the rubric is applied
and the metrics computed; a draft assessment enters the professor's review queue; approval publishes
it to the student (requirements §10, architecture §9.1).

**Rubric.** Four dimensions — progress toward agreed outcomes (30%), research learning and reasoning
(30%), rigor and evidence quality (25%), usable research artifacts (15%) — each rated 0–4 against
stage-specific anchors, with a 0–100 progress index as a supervision aid rather than a grade
(ASSESS-03, ASSESS-04). Commitment completion against the frozen plan is reported separately,
because it measures promises kept, not scientific value (ASSESS-05).

**Assistant.** A professor-facing, read-only research assistant answers factual, comparative,
longitudinal and planning questions over the records the caller may already see, under an explicit
answer contract: time range, scope, answer, facts with their as-of instants, synthesis marked apart
from facts, citations that open the authorised source, and disclosed gaps (QA-01…QA-07).

**Implementation.** A modular monolith — FastAPI, PostgreSQL 16 with `pgvector` and full-text search,
a Postgres-backed job queue, MinIO for files, React SPA — on a single host, sized for fifty students
and thirty active projects per workspace (architecture §1, §3, requirements §11). The model provider
is reachable from exactly one module.

## 3 Innovation

What is new here is not any single component but the boundary drawn between deterministic records
and generative interpretation, and the fact that the boundary is enforced by schema and by tests
rather than by prompt instructions. Seven decisions carry most of that novelty.

**I1 — Facts are computed in SQL; the model never produces a number.** Registered fact functions
compute counts, dates, deadlines, memberships and scores through the owning module's service layer,
so they compile the same permission predicate as every other read. For a question classified as
factual, the generation step is not called at all; for a mixed question, facts are supplied as
authoritative and rendered in their own field, apart from the prose. The router may name a fact
function but may not invent one: an unregistered name is dropped rather than approximated
([ADR 0008](adr/0008-facts-outside-the-model.md)). The AC-15 test scripts the fake gateway to answer
"seven", so passing proves the model was never consulted for the count. Note that this makes the
dashboard and the assistant incapable of disagreeing — both are built from the same functions.

**I2 — Rubric arithmetic lives outside the model, and unknown is not zero.** The model returns only
per-dimension ratings, rationales and evidence reference ids through a structured-output schema;
`metrics.py` computes the index, completion, coverage and confidence in `Decimal` with round-half-up
([ADR 0006](adr/0006-deterministic-metrics.md)). A 0 requires evidence that the criterion was not
met; unavailable evidence is `unknown`, and if any applicable dimension is `unknown` the index is
withheld with *Not rated — insufficient evidence* rather than computed over what happens to be
present (ASSESS-04). The specification's worked example — ratings 3, 4, 3, 2 giving 78.75 and
displaying 79 — is a unit test, not an illustration.

**I3 — Fabricated citations cannot survive validation.** `validate_output` drops every evidence id
not present in the snapshot and downgrades the affected rating to `unknown` with a recorded reason
(architecture §9.3). The gateway exposes no function-calling tools to the model at all, and every
retrieved text is framed as a delimited data block that is evidence to analyse rather than
instructions to follow, so an injection attempt inside a README is text (AC-12). Put it altogether,
a claim can reach the professor only as supported, partially supported, unsupported or
unverifiable — never as verified because the model said so (REPO-08, ASSESS-07).

**I4 — Coverage and confidence are first-class outputs with rule-based reasons.** Each dimension
records its evidence sufficiency; coverage is the percentage of applicable rubric weight supported
well enough to rate; confidence is high/medium/low from a small versioned rule table with its
reasons named, not an unexplained model probability (ASSESS-06). A project with no repository can
reach full coverage through other artifacts, and a stale repository is reported as stale rather than
read as zero work (AC-04, AC-05). Similarly, file extraction has three outcomes rather than two —
`ok`, `unsupported`, `failed` — so that a figure is evidence whether or not OCR exists, and only a
genuine read failure reduces coverage ([ADR 0010](adr/0010-presigned-uploads-verified-after-the-fact.md)).
This is the unfairness nobody would have noticed: a week recorded as empty when it was merely
unreadable.

**I5 — A single counter expires every cached answer, and over-invalidation is the intended failure
mode.** `workspaces.access_epoch` increments in the same transaction as any membership end,
deactivation, role change or visibility change; a cached answer or snapshot records the epoch it was
built under and is served only while it matches, after which each citation is additionally re-checked
against the caller's current scope ([ADR 0009](adr/0009-access-epoch-for-cached-answers.md)).
Nothing has to find the stale answers, which is what makes the rule reviewable: deciding whether a
change is covered means asking whether it advances the epoch. The cost is a few wasted regenerations
a term; the alternative — an invalidation sweep — fails silently and looks exactly like normal
operation.

**I6 — Approval, immutability and reproducible provenance are the publication contract.** Generated
assessments are drafts visible only to the professor; approval publishes, an override records its
reason, and the original model output is retained beside it (ASSESS-08). Every assessment version
stores the rubric version, prompt and model versions, evidence references, report version and
timestamp, and a new report version re-assesses only the entries whose content changed
(ASSESS-09, AC-17). Trends are grouped by rubric version, so a rubric change appears as a labelled
break rather than as a comparable series (AC-10). It is worth noting what this forecloses: the model
has no path to publishing anything, because publication is a product action taken by a person
(QA-07).

**I7 — Attribution preserves joint work, and time is not one thing.** Author, committer, reviewer and
merger are distinct roles; merging another person's change does not establish authorship; shared
artifacts are deduplicated at the project level while remaining jointly attributed, and a correction
to one student's contribution re-flags every assessment whose snapshot contained the affected event
(REPO-03, REPO-04, AC-06). Commit author time, commit time, merge time and ingestion time are kept
distinct, and an old commit merged this week is flagged as integration of earlier work (REPO-06).
Each student can see the contributions and identity mappings attributed to them, which is what makes
misattribution challengeable rather than merely regrettable.

Two further design commitments are worth naming because they shape day-to-day use rather than the
assessment contract. Professors are co-equal, and a professor may belong to several workspaces at
once, reading across all of them and writing into the one they are working in
([ADR 0011](adr/0011-co-equal-professors.md), [ADR 0016](adr/0016-reads-span-membership.md)); and
students own the projects they report on — a student may start a project, join one a professor has
opened to joining, and leave one — while no private record follows a project, because reports,
assessments, feedback and notes are keyed to a student
([ADR 0017](adr/0017-students-own-their-projects.md)).

## 4 Impact

**For the professor.** The review workspace presents the student's claims, the evidence, the draft
assessment and source freshness together, so that the weekly act becomes reviewing a cited draft
rather than reconstructing a week. Because the assistant and the overview compute from the same fact
functions, the answer to "which reports are missing" is the obligations table after exemptions and
deadline rules, with an explicit as-of instant, and it is the same number on every screen.
Longitudinal questions that span a rubric change are answerable without pretending the scores are
comparable.

**For the student.** The framework makes the basis of an assessment inspectable: the frozen plan, the
component ratings with rationales, the cited evidence, the stated limitations, and a correction
channel with the right to add evidence (ASSESS-08). Negative and theoretical results are creditable
without commits (AC-05), unavailable evidence never becomes a zero, and a week's standing does not
depend on whether a repository connector happened to be healthy. Students also see what has been
attributed to them, which is the precondition for contesting it.

**For the group as a research record.** Reports, plans, decisions, contributions and assessments
accumulate as versioned, permission-labelled records independent of chat history, which makes the
history of a project answerable years later — why direction changed, what was tried and abandoned,
who contributed what. The record is designed to outlive the model that currently reads it:
provider replacement does not migrate the authoritative history (requirements §11, Portability).

**What it deliberately does not do.** Automatic grading, leaderboards, plagiarism judgments,
authorship decisions, arbitrary code execution and institutional administration are out of scope
(requirements §1). Reading a diff or a CI result does not prove scientific correctness, and the
framework says so wherever it reports evidence (REPO-08). Hours worked may be recorded and are never
treated as verified productivity (REP-03).

## 5 How the impact is to be measured

The framework's claims are testable, and the evaluation protocol separates two questions that are
routinely conflated ([evaluation/protocol.md](evaluation/protocol.md)).

**Contract properties** — the index withheld when evidence is absent, no citation outside the
snapshot, joint work kept joint, an instruction inside a README treated as text — are pass/fail
properties of the system. They run on every CI pass against a deterministic gateway, because they
must never regress.

**Agreement with the professor** is a calibration question about the rubric and the prompts. It needs
the real provider and the professor's own ratings, and it is *reported rather than asserted*:
per-dimension exact and within-one agreement, material correction rate, citation support rate,
uncertainty behaviour, injection resistance, and run-to-run variation of the index. This is because
asserting a threshold nobody has agreed to would turn calibration into a test that gets tuned until
it passes. The pilot gates are explicit: at least 30 student–project–weeks rated by the professor on
real work, 50 professor questions with exact counts and dates matching the database, every
authorisation and adversarial scenario passing, citation support at or above 95%, every
incomplete-evidence case producing an uncertainty response, and an agreement threshold agreed with
the professor and recorded with its date. Approval remains a required publication step whatever the
numbers say.

**Limitations.** The ten evaluation cases in this repository are a de-identified seed set whose
ratings are the specification's anchors applied by the set's author, not the professor's judgement;
until the pilot weeks exist, agreement numbers check the prompt rather than the rubric. The default
weights and anchors are proposals, not validated measures of research productivity. The interactive,
first-token and assessment-latency targets in requirements §11 have not yet been benchmarked against
the 100,000-chunk corpus, and the rubric's construct validity — whether these four dimensions
capture research progress across stages — is a question the pilot opens rather than settles.

## 6 Status

All twelve implementation steps are built: identity and authorisation, projects and reporting,
notifications and the missed-deadline email, repository evidence and retrieval, the assessment
pipeline, the AI gateway and cost ledger, the assistant and overview, the seams between them, the
review that followed, deployment preparation, and workspaces. Counted from the tree: 25 migrations,
98 `/api/v1` endpoints, 17 ADRs, and a test for each of the 19 acceptance scenarios, asserted by
`scripts/check_traceability.py` on every CI run. What remains before a pilot is calibration and
operation rather than construction, together with the decisions still owed by the professor — the
mail provider, what content may reach the model provider, the rubric calibration itself, the AI
budget, hosting and backup destinations, and the retention policy, which is irreversible and
therefore theirs to set. Current gaps and their reasons are listed in
[implementation_status.md](implementation_status.md) §3, and the open decisions in §5.

Two lessons from building it are recorded there and are worth repeating here, because they generalise
beyond this framework. First, a step marked done means its module is done, and the separate question
worth asking is what calls it: three seams between finished modules were missing while every
module-level test was green. Second, wrong numbers look like numbers — commitment completion computed
with every fraction hardcoded to zero, coverage taking its denominator from the model's own output, a
snapshot carrying a fortnight of already-assessed evidence. None of these failed; each produced a
plausible figure, which for an assessment system is the outcome that matters most to prevent.
