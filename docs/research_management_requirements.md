# Research Management System Requirements

Version 0.6 — proposed specification — 17 September 2026 (revised; see section 15)

This system gives a professor a persistent, evidence-based view of each student's research. It manages project participation, collects weekly reports, connects optional code repositories, proposes weekly progress assessments, and answers research questions using attributable sources. The primary unit of assessment is one student working on one project during one reporting week.

This specification describes the intended product, its functional requirements, data model, assessment rules, and acceptance criteria. Defaults and numerical targets below are proposals to validate during implementation and a pilot, not established measures of research productivity.

## 1 Purpose and scope

The system must let the professor answer four questions quickly: What did each student accomplish? What evidence supports that account? Where is the research blocked? What should be discussed or done next?

The initial deployment is a private research workspace with one or more professors and multiple students. There are exactly two user roles, `prof` and `student`; professors also manage workspace settings and invitations. Professors are co-equal: each has the same authority over every student in the workspace, and none has authority over another (ADR 0011). Projects have multiple students, and students can participate in multiple projects. A project can have zero, one, or several repositories. The system must support literature review, theory, data preparation, implementation, experimentation, analysis, and paper writing.

The initial release covers supervision and research records. Automatic grading, student leaderboards, plagiarism judgments, publication authorship decisions, arbitrary code execution, institutional administration, and a complete reference manager are outside its scope. AI-generated assessments support the professor's judgment and must retain their draft or approved status.

## 2 Roles and permissions

| Capability | Professor | Student |
| --- | --- | --- |
| Invite, deactivate, and manage users | Yes | Manage own profile only |
| Create, archive, and configure projects | Yes | Start their own; edit what they started |
| Assign students and reporting obligations | Yes | Join a project opened to joining; leave one |
| Manage repository connections | Yes | Propose links and map own developer identities |
| Create and edit a weekly report | Annotate and request revisions | Own drafts and authorized revisions |
| Read submitted reports | All reports in own workspace | Own reports by default |
| Access shared project resources | All authorized resources | Resources explicitly shared with project members |
| View individual assessments | All students in own workspace | Own released assessments |
| Approve or override assessments | Yes, with recorded reason | Request correction and supply evidence |
| Maintain private supervision notes | Yes | No |
| Query the research assistant | All authorized workspace research | Optional later feature, restricted to permitted material |
| Create, configure, and archive workspaces | Yes, for workspaces they own | No |
| Belong to several workspaces at once | Yes; reads span them, writes land in the one being worked in | No — exactly one |

**AUTH-01 — Authentication.** Require authenticated accounts, invitation-based enrollment, session expiration, and account deactivation. Only a professor can enrol a user or remove a student from the workspace. A professor may place any student on any project and end any membership; a student may start a project, join one their professor has opened to joining, and end their own membership on a project, and may do none of these on another account's behalf (PROJ-07). A user's role is fixed when they accept their invitation: any professor may invite a colleague as a professor, but no professor may demote, deactivate, or remove another through the application. Provide account recovery for every user through a verified out-of-band channel. The deployment must document an audited break-glass procedure — run from the host and not reachable from any account, student or professor — for recovering, transferring, demoting, or deactivating a professor account, and that procedure must refuse to leave a workspace with no active professor.

**AUTH-02 — Authorization.** Enforce workspace, project, ownership, and document-visibility permissions in every API, search, download, and AI retrieval operation. A project membership does not grant access to other students' private reports, individual assessments, or professor notes.

**AUTH-03 — Access changes.** Removing a membership or deactivating a user must invalidate subsequent access, including cached answers and download authorization. Preserve historical records for authorized supervision. Repository authorization and application visibility must be checked separately: access to a derived record must not bypass its source restrictions. A cached answer built from records in several workspaces must be invalidated when any of them changes, not only the one the request was made in (AUTH-05).

**AUTH-04 — Workspaces.** A workspace is the tenant boundary: every record belongs to exactly one, and no read crosses out of the set the caller belongs to. A professor may create a workspace, which they then own; rename it; set its timezone; and archive it once nobody belongs to it. A workspace is archived, never deleted, because every record in the schema points at one and deleting it would take the research history with it. An invitation names the workspace it enrols into, so every account has one from the moment it is created rather than from acceptance ([ADR 0012](adr/0012-workspace-ownership.md)).

**AUTH-05 — Belonging and scope.** A professor belongs to one or more workspaces and works in exactly one at a time; a student belongs to exactly one. Reads span every workspace the account belongs to; writes land in the one it is working in, and screens group what they show by workspace. Joining a workspace adds a membership and moves where writes land — joining one already belonged to therefore moves only the latter, which is how switching is expressed. Leaving gives up a membership and must be refused when it would leave active accounts in a workspace with no active professor (AUTH-01), or when it is the account's only membership ([ADR 0015](adr/0015-plural-workspace-membership.md), [ADR 0016](adr/0016-reads-span-membership.md)).

**AUTH-06 — Moving an account.** A professor may move a student to another workspace they administer, but only before that student has written anything. Project memberships, submitted reports, developer identities, and attributed contributions are pinned to the workspace they were written in, and the system must refuse a move that would separate an account from them rather than dragging the history along or leaving it orphaned. The refusal is a property of the schema, not a check that a later caller can forget ([ADR 0014](adr/0014-joining-and-leaving-a-workspace.md)).

**AUTH-07 — Project authorship.** The account that created a project may change its record — title, description, research questions, intended contributions, stage, and dates — for as long as the project exists, including after they have left it. It may not change the project's standing: status, whether the project is open to joining, and the restriction on sending its text to a model provider are the professor's alone. A professor may change any project in their workspace. A project with no recorded creator is the professor's alone to change.

## 3 Projects and research planning

**PROJ-01 — Project records.** Store title, description, research questions, intended contributions, research stage, status, start and target dates, paper or venue targets when applicable, an optional link to the project's repository, and shared resources. That link is a pointer for the people on the project and nothing more: it is not a connected repository (REPO-01), no events are read from it, and no contribution is attributed from it. Statuses are proposed, active, paused, completed, and archived. A project a professor creates is proposed and becomes active by an explicit change, because activation is where a second party's assent is recorded. A project a student creates is active on creation — there is no second party, and nothing is owed on a proposed project, so leaving it proposed would give them a project that produces nothing and no way to see why.

**PROJ-02 — Membership.** Record each student's responsibility, join and leave dates, first and last required reporting periods, planned allocation if used, and exemptions. Retain membership history instead of deleting it when a student leaves. Record how each membership began — assigned by a professor, created with the project, or joined by the student — because they differ in which weeks they oblige. A membership that was assigned or created with the project owes the week it lands in: the professor knows what they are asking for, and a student starting a project is announcing work already under way. A student joining an existing project owes from the following week, so that joining on a Saturday is not a report due that Sunday for a week spent off the project. An obligation is derived as soon as the membership exists rather than waiting for the next scheduled run.

**PROJ-03 — Milestones and tasks.** Support milestones with an owner or contributors, target date, status, success criteria, and evidence. Weekly tasks link to milestones and have planned outcomes, effort weights, completion criteria, and blockers. Completion may be partial and must include a reason and evidence.

**PROJ-04 — Baselines.** Preserve the plan used to assess a week. Next-week plans submitted in the previous report become the next baseline under the workspace's configured policy. The baseline freezes at a configured point, by default the start of the reporting period. If no plan exists at the freeze point, because the membership is new, the previous report was missing or late, or the project was paused, the baseline is empty: the student enters a plan in the current report, the professor may accept it as the baseline with a recorded timestamp, and until acceptance commitment completion is marked unavailable (ASSESS-05). Later changes require a new version, timestamp, and reason; they must not erase missed original commitments. Professor-approved changes must be distinguishable from student-proposed changes.

**PROJ-05 — Different research stages.** Configure rubric examples and applicable evidence by stage. A literature-review project and an implementation project use appropriate outputs; neither requires commits merely to receive a positive assessment.

**PROJ-06 — Project progress.** Show milestone status, accepted deliverables, blockers, and timeline changes. If showing percentage completion, compute it from professor-defined milestone weights and accepted completion fractions. Do not treat average student scores as a project's completion percentage. When milestone scope or weights change, retain and display the baseline version.

**PROJ-07 — Self-service membership.** A student may start a project, and may join any project in their workspace that a professor has marked open to joining. Joining is direct: there is no approval step, because the professor's decision was taken when they opened the project. A student may end their own membership on a project and no one else's, effective from the day they leave, and may not place any other account on a project or remove it. Every membership records which of the two ways it began, and both are written to the audit log with the acting account as the actor. Opening a project to joining is a professor's decision per project, and the default is closed, because a membership grants the project's shared records and the identities of everyone who has worked on it (AUTH-02).

## 4 Weekly reporting

**REP-01 — Reporting calendar.** Configure timezone, the weekly meeting day, week boundaries, and grace period. The submission deadline is fixed by rule: 23:59 local time on the day before the weekly meeting. Proposed default: meeting on Monday, reporting period Monday through Sunday in Asia/Ho_Chi_Minh, therefore due Sunday at 23:59. Changing the meeting day creates a new calendar configuration version that applies to future periods only; periods already open keep their original deadline. Store timestamps in UTC together with the calendar definition and effective configuration version. Use an explicit reporting-period ID and local start/end dates.

**REP-02 — One report with project entries.** Maintain one report per student per reporting period, containing one entry for each project for which a report is required. The student submits the weekly package once. Assessments remain separate for each student–project–week. A package is complete only when each required project has an entry or recorded exemption.

**REP-03 — Report template.** Each project entry must contain:

| Field | Requirement |
| --- | --- |
| Research stage and milestone | Select the stage and link relevant milestones |
| Planned work | Reference the frozen plan for this week |
| Work performed | Explain concrete actions and individual contribution |
| Results and research learning | Record findings, including negative or inconclusive results |
| Evidence | Attach or link artifacts; identify what each item supports |
| Experiments when applicable | Hypothesis, setup, dataset/version, baseline, metrics, result, and interpretation |
| Deviations and blockers | Explain changes, dependencies, unsuccessful attempts, and help needed |
| Next-week plan | Specify outcomes, acceptance criteria, and relevant milestones |
| Questions for the professor | Identify decisions or feedback requested |

Hours worked may be an optional self-reported field. They must not be treated as independently verified productivity. Support English and Vietnamese report text and preserve technical terminology, equations, tables, and links.

**REP-04 — Editor and evidence.** Provide autosave, Markdown or rich-text editing, draft recovery, and file attachments. MVP inputs should include text/Markdown, PDF, DOCX, figures, and links to repository objects or experiment results. Preserve original files and extracted text, mark extraction failures, read the text out of a file after the upload has been accepted rather than during it — so attaching returns as soon as the bytes are safe and the attachment says it is still being read — and propose a configurable upload limit of 25 MB per file with a configurable total per project entry. The student who attached a file may remove it while that week is still a draft, and removal is real: the stored object, the extracted text, the search index entries and the cached answers that could quote it all go (§11). Once the week is submitted its attachments are part of the record and only the professor's retention policy reaches them. OCR and specialist experiment integrations can follow later. Restrict and validate link fetching.

**REP-05 — Submission lifecycle.** Support draft, submitted, revision requested, resubmitted, and reviewed states. Submission creates an immutable version. Revisions create new versions without replacing history. The professor comments and requests changes; substantive author edits remain attributable to the student. Timing status is separate: on time, late, missing, or excused. Revision requests target specific project entries. A resubmission carries unchanged entries forward with a marker identifying the version in which their content last changed, so revising one entry does not create a new assessment for an unchanged entry (ASSESS-09).

**REP-06 — Missing and exceptional weeks.** Record leave, holidays, paused projects, partial enrollment, and extensions. An absent report without an approved exemption is recorded as a missing-report condition on the obligation; it does not create an invented research assessment or automatically assign a zero. Late reports retain their actual timestamps and may trigger a new assessment version.

**REP-07 — Feedback and reminders.** Support report-level and section-level feedback, a student acknowledgement or response, and configurable reminders before the deadline, delivered by the channel UI-07 leaves in place. *Amended in 0.5:* the reminder records are written on the configured offsets, but with the in-app surface withdrawn (UI-07) nothing displays them and only the missed-deadline message is emailed (REP-08) — so a pre-deadline reminder reaches nobody today. Feedback beyond the released assessment is likewise unbuilt: no code path authors professor feedback. Respect timezone, extensions, and exemptions. Reminders and professor review status must not change a report's original submission time.

**REP-08 — Missed-deadline email.** When the deadline passes, the system automatically emails every student whose reporting obligation for that period is still unfulfilled, at 00:00 local time on the meeting day. An obligation is unfulfilled when no package has been submitted or a required project entry is missing without a recorded exemption or extension. Evaluate obligation state at send time, not when the job is scheduled, so a submission at 23:59 receives no email. Send at most one such email per student per period, with idempotent delivery keys; retry bounded failures and record delivery state in the Notification record. The email lists the missing entries and the link to submit, states that the report will be recorded as late or within grace according to REP-05, and contains no assessment content or other students' information. Also notify the professor in-app with the list of unfulfilled obligations at the same time. *Amended in 0.4:* the notification record is still written, but with the notifications screen withdrawn (UI-07) what the professor actually reads is the outstanding list on the overview, derived from the obligations themselves rather than from the message about them. Email delivery is therefore a required MVP channel and needs a configured mail provider before the first reporting period.

## 5 Repository and artifact evidence

**REPO-01 — Optional connections.** Provide a connector contract for GitHub and GitLab, with one provider implemented in the MVP according to the repositories selected for the pilot. Support private repositories and multiple repositories per project. Use read-only credentials limited to the required repositories and data. The product must remain fully usable without a repository.

**REPO-02 — Collected evidence.** Where permissions and provider capabilities permit, collect commit metadata and relevant diffs, branches, pull/merge requests, reviews, issues, linked task references, test/CI summaries, and relevant documentation changes. Store source URLs, provider IDs, commit hashes or source versions, event timestamps, ingestion timestamps, and repository visibility. Record content omitted due to limits.

**REPO-03 — Identity mapping.** Map each student to verified provider accounts and explicitly confirmed email aliases. Record bots, co-authored commits, and ambiguous identities. Author, committer, reviewer, and merger are distinct roles. Merging another person's change does not establish authorship.

**REPO-04 — Attribution.** Attribute work using report claims, linked artifacts, author/co-author records, review contributions, and explicit confirmation. Deduplicate repeated events and shared artifacts. Preserve joint contributions without assigning the entire team's output to every student. If a repository serves several projects, use an approved path/label mapping or explicit links; otherwise mark project attribution unresolved. Each student can view the contributions, identity mappings, and evidence references attributed to them, so misattribution can be challenged under ASSESS-08.

**REPO-05 — Synchronization.** Support an initial historical import, incremental scheduled sync, manual resync, and webhooks where available. Use pagination, stable external IDs, idempotency, retries, and rate-limit handling. Display last successful sync, covered time range, partial failures, and authorization errors. Reprocessing the same source event must not increase contributions or scores.

**REPO-06 — Temporal accuracy.** Preserve source-specific event dates. Commit author time, commit time, merge time, and ingestion time are not interchangeable. Group events using a documented policy and explicit week boundaries. For old commits newly merged this week, distinguish work creation from integration. Handle force-pushed or removed objects by retaining permitted snapshots and marking the live source unavailable.

**REPO-07 — Evidence interpretation.** Summarize the substance of changes, such as a baseline implementation, an evaluation correction, or a reproducibility improvement. Raw commit counts and lines changed are contextual activity statistics only. Exclude or label bot activity, generated files, vendored code, and mechanical formatting when interpreting contributions.

**REPO-08 — Limits of verification.** Reading a diff or CI result does not prove scientific correctness or successful replication. Distinguish a student claim, an inspected artifact, an observed external test result, and professor confirmation. Do not execute repository code in the MVP. Broken links, truncated diffs, and unavailable histories must reduce evidence coverage explicitly.

## 6 Weekly progress assessment

### Assessment contract

**ASSESS-01 — Assessment unit.** Produce a versioned assessment for each student–project–week, based on the submitted report version, applicable baseline plan, relevant history, and a recorded evidence snapshot. The evidence snapshot must exclude private supervision notes and any record the student is not authorized to see, because the approved assessment is published to the student (QA-06). A weekly student overview groups these assessments and distinct contributions; the MVP does not collapse different projects into a single ranking score.

**ASSESS-02 — Separate signals.** Present four separate outputs:

1. A research-progress rubric and optional 0–100 progress index.
2. Reporting consistency: on-time/late/missing/excused and outstanding feedback.
3. Evidence coverage and assessment confidence, with reasons.
4. Milestone status and support needs, with evidence-linked explanations.

The index is a supervision aid within a consistent project and rubric. It is neither a grade nor a scientifically validated measure of a person's research ability. Compare a student's trajectory within the same context and mark changes in stage, workload, rubric, or project scope.

### Proposed initial rubric

**ASSESS-03 — Rubric dimensions.** The following default weights are configurable and must be piloted with professor-rated examples.

| Dimension | Default weight | What the assessor considers |
| --- | ---: | --- |
| Progress toward agreed outcomes | 30% | Meaningful advancement against the frozen plan and milestone criteria, accounting explicitly for approved changes |
| Research learning and reasoning | 30% | Useful findings, hypothesis refinement, diagnosis, synthesis, or justified changes in direction |
| Rigor and evidence quality | 25% | Appropriate methodology, traceable claims, reproducibility information, and acknowledgement of limitations |
| Usable research artifacts | 15% | Relevant code, notes, proofs, datasets, experiment records, figures, or manuscript sections that others can inspect or build on |

Each dimension uses a 0–4 rating with dimension-specific, stage-specific anchors. A 3 means the agreed standard for that dimension is met. A 4 requires documented value beyond that standard, not simply more hours, more text, or more commits. A 0 requires evidence that the criterion was not met; unavailable evidence is `unknown`, not zero.

Example anchors for progress toward agreed outcomes: 0 = evidence shows no meaningful advancement against the agreed outcomes; 1 = limited advancement; 2 = material partial advancement; 3 = agreed weekly outcome met; 4 = a justified additional outcome materially advances the milestone. Negative experiments can meet an outcome when the agreed aim was to test a hypothesis and the test was rigorous.

**ASSESS-04 — Calculation.** For applicable dimensions with adequate evidence, compute:

`progress_index = round(100 × sum(weight[d] × rating[d] / 4) / sum(weight[d]))`

With ratings 3, 4, 3, and 2 and the default weights, the unrounded index is 78.75 and the displayed index is 79. Display the component ratings beside the index. Use an explicit round-half-up rule for nonnegative totals.

Generate the overall index only when all applicable dimensions have enough evidence to assign a rating. Otherwise display `Not rated — insufficient evidence` and show the assessable dimensions. A dimension may be `not applicable` only under an explicit, versioned rubric decision; it must not be excluded merely because evidence is missing. Renormalize weights only over dimensions legitimately marked applicable.

**ASSESS-05 — Commitment completion.** Separately show weighted plan completion: `100 × sum(planned_weight × accepted_completion_fraction) / sum(planned_weight)`. Use frozen weights and supported fractions in [0,1]. The student reports a completion fraction with a reason and evidence; the draft assessment may propose a different fraction; a fraction becomes accepted only when the professor approves the assessment, and before approval it is labelled proposed. Show unplanned work separately and retain original versus revised plan completion after approved changes. If the baseline is missing or ambiguous, mark completion unavailable. This measures commitments, not scientific value.

**ASSESS-06 — Coverage and confidence.** Record each dimension's evidence sufficiency and calculate coverage as the percentage of applicable rubric weight supported well enough to rate. Show source coverage separately, including report status and repository freshness. Use high/medium/low confidence with rule-based reasons rather than an unexplained model probability. A project without a repository can have full evidence coverage through other artifacts. A stale repository must not be interpreted as zero work.

**ASSESS-07 — Reasoned output.** Every assessment must provide accomplishments, component ratings and rationales, supporting source references, limitations, blockers, unresolved report–repository discrepancies, next-step suggestions, and a short professor discussion agenda. Each factual claim and rating justification must link to its evidence.

**ASSESS-08 — Review and correction.** Generated assessments begin as drafts and are visible to the professor. Approval publishes the assessment to the student. The professor can adjust a rating or narrative with a recorded reason. Students can request corrections and add evidence. Preserve original model output, approved output, actor, timestamp, and revision history. Corrections to one student's contribution must trigger review of affected shared attributions.

**ASSESS-09 — Reproducibility.** Store rubric version, configuration, model and prompt versions, retrieval/evidence references, report version, and assessment timestamp. New reports, evidence, or models create new assessment versions and never silently rewrite approved history. A new report version creates a new assessment version only for project entries whose content changed since the version the current assessment used. Scores and published trends must identify which version they use. Calculate arithmetic deterministically outside the language model.

**ASSESS-10 — Trends and support flags.** Show recent weekly trajectories and repeated blockers. Suggested configurable flags include a missing report after the grace period, a blocker repeated for two reporting periods, an overdue milestone, and a report claim with unresolved evidence. Label these conditions directly; a discrepancy is a request for clarification. Preserve context such as leave, unavailable compute, changed scope, and supervisor dependencies. Do not infer misconduct, effort, or personal characteristics from sparse telemetry.

The principle of using several dimensions rather than activity counts alone is consistent with the software-productivity research in [The SPACE of Developer Productivity](https://www.microsoft.com/en-us/research/publication/the-space-of-developer-productivity-theres-more-to-it-than-you-think/). The research-specific rubric, weights, and workflow above are design proposals, not a validation result from that paper.

## 7 Professor research assistant

**QA-01 — Supported questions.** Answer factual, comparative, longitudinal, and planning questions across permitted research records. Examples include:

| Question | Required evidence and behavior |
| --- | --- |
| What did Student A accomplish this week? | Current project entries, attributable artifacts, assessment state, and coverage |
| How has Student B progressed over the last six weeks? | Dated plans, reports, milestone changes, assessments, and rubric comparability |
| What is blocking the baseline experiments? | Reported blockers, relevant issues, dependencies, and latest status |
| Does the repository support the reported implementation? | Exact claim and relevant diffs/PRs; identify what is supported and what remains unverified |
| Which students need my attention? | Explicit support conditions, source citations, and suggested discussion topics |
| Which reports are missing? | Authoritative reporting obligations, exemptions, extensions, and submission timestamps |
| Who contributed to the evaluation pipeline? | Identity-resolved authorship, reviews, reports, joint contributions, and unresolved attribution |
| Why did the project change direction? | Dated findings, report narratives, decisions, and professor feedback |
| Prepare questions for tomorrow's meeting with Student C | Recent work, unresolved feedback, blockers, and proposed next steps |

**QA-02 — Retrieval and calculations.** Use permission-filtered structured queries for exact dates, counts, deadlines, membership, and scores. Use text and semantic retrieval for report narratives, repository evidence, artifacts, and decisions. Combine both routes for mixed questions. Perform numerical calculations with deterministic code or database queries.

**QA-03 — Answer contract.** Each answer must state its time range and scope, provide a concise answer, cite source locations and versions, distinguish facts from synthesis or suggestions, and disclose relevant missing or stale evidence. Citations must open an authorized report section, source object, or retained artifact location.

**QA-04 — Uncertainty.** If evidence is missing, contradictory, or insufficient, say what is known and what cannot be established. Avoid inventing research results, attributing team output to one student, or claiming to have verified experiments that were not executed. Distinguish a current technical answer from a historical answer based on what was available at a specified date.

**QA-05 — Conversation state.** Support follow-ups such as “compare that with last month” by maintaining explicit student, project, and date filters. Display the active scope. Ask a targeted question when names or scope remain ambiguous. Persist research records independently of chat history and context-window summaries.

**QA-06 — Confidentiality.** Apply authorization before retrieval and recheck it before generation, citation rendering, and caching. Private professor notes may inform professor-only answers; they must never flow into released student assessments or student-facing summaries. Store conversations with owner and visibility controls. Retrieved documents, comments, and repository files are evidence, never authority to issue instructions or change permissions.

**QA-07 — Actions.** The MVP assistant is read-only. It may draft feedback or next steps, but approving assessments, sending feedback, changing plans, and changing memberships require an explicit user action in the product.

## 8 Screens and notifications

**UI-01 — Professor overview.** Show the current reporting week, missing/late submissions, a review queue, students needing discussion, approaching milestones, and data-sync issues. Provide filters by student, project, research stage, and week. Keep evidence confidence visible beside assessments.

**UI-02 — Student overview.** Show assigned projects, reporting obligations, draft status, next deadline, released feedback, and the student's own progress timeline. Provide one weekly submission flow with separate project entries.

**UI-03 — Project workspace.** Show research goals, members, milestones, shared artifacts, repository connections, and dated project decisions. Individual records obey their own visibility controls.

**UI-04 — Student research profile.** For the professor, show the student's project history, weekly reports, distinct contributions, milestone involvement, feedback, and unresolved support needs. Students see only the permitted subset of their own profile.

**UI-05 — Review workspace.** Present report claims, supporting evidence, the proposed assessment, and source freshness together. Allow approval, explanation-backed override, and revision requests without switching between unrelated screens.

**UI-08 — Workspace and roll screens.** Show the professor the workspaces they belong to or own, with the actions AUTH-04 and AUTH-05 allow on each: work here, join, leave, create, archive, rename. Show everyone across those workspaces on one roll, grouped by workspace, with invite, move, suspend, restore, and remove — and make clear which rows the caller can act on, since reads span membership and writes do not (AUTH-05).

**UI-06 — Exports. Withdrawn in 0.4.** *Was: export filtered reports, assessments, and supervision summaries with dates, source references, and approval status; provide machine-readable export for portability; export authorization must match interactive access.* Exports were retired as a product capability and the module removed. The portability obligation in section 2 — a student keeping their own released records — is now unmet by design rather than by omission, and reinstating it means reinstating this requirement first.

**UI-07 — Notifications. Amended in 0.4: delivery only.** Generate notification records for report submission and resubmission, revision requests, released assessments and feedback, approaching and missed deadlines, overdue milestones, and repository sync or authorization failures. Deliver the missed-deadline reminder by email (REP-08); other categories go to email only when configured. Notification text must obey the recipient's visibility permissions and must never include private supervision notes or another student's report content. Record delivery state. *Withdrawn from this requirement in 0.4: the in-app notification surface, and muting non-critical categories.* Email is therefore the only channel that reaches a recipient, which section 12 should be read against.

## 9 Core data model

The following are logical entities, not a requirement to create one table per row.

| Entity | Principal fields or relationships |
| --- | --- |
| Workspace | Owner, timezone, weekly meeting day, reporting policy, mail provider configuration, retention settings |
| User | Workspace, role, profile, account state |
| Project | Workspace, goals, stage, status, dates, visibility |
| ProjectMembership | Project, student, responsibility, effective dates, reporting obligations, allocation |
| Milestone and Task | Project, owners/contributors, criteria, baseline versions, dates, status, weights |
| PlanBaseline | Membership, period, frozen tasks and weights, version, freeze time, source report version, change reason, approver |
| ReportingPeriod | Workspace, start/end UTC and local dates, timezone, meeting date, deadline, policy version |
| ReportingObligation | Membership, period, required/excused state, extension, reason |
| WeeklyReport | Student, period, workflow state, original submission time |
| ReportVersion | WeeklyReport, immutable content version, author, submitted time |
| ProjectReportEntry | ReportVersion, project, planned work, findings, blockers, next plan, version in which content last changed |
| Artifact and ArtifactVersion | File or URL, checksum/version, extracted text, visibility, storage reference |
| Repository and ProjectRepository | Provider, external ID, connection state, credential reference, project mapping |
| DeveloperIdentity | Student, provider account or email alias, verification state |
| RepositoryEvent | Repository, stable source ID, type, authors, event dates, source version |
| Contribution | Student, project, evidence, individual/joint role, attribution status and provenance |
| EvidenceReference | Source/version, locator, visibility, supported claim, ingestion and source times |
| RubricVersion | Stage applicability, anchors, weights, calculation rules, effective dates |
| AssessmentVersion | Student/project/period, report version, evidence snapshot, ratings, coverage, confidence, model configuration |
| AssessmentReview | AssessmentVersion, draft/approved/superseded state, reviewer, rationale, publication time |
| Feedback and SupervisionNote | Subject record, author, text, visibility, responses |
| ResearchDecision | Project, decision, rationale, related evidence, date, participants |
| Conversation and Answer | Owner, explicit scope, message content, citations, generation metadata |
| SyncRun and AnalysisRun | Source scope, job status, watermark, retries, input/output versions, error summary |
| Notification and AuditEvent | Actor/recipient, action, target, timestamp, delivery or change state |

Required invariants: unique report per student–period; unique project entry per report version–project; unique reporting obligation per membership–period; at most one baseline version in effect per membership–period at any time; idempotent external-event identifiers; immutable submitted and approved versions; foreign keys scoped to the same workspace; and explicit access labels on indexed evidence. Store credential references in application records and secrets in a protected secret store.

## 10 Processing and service boundaries

The framework needs a web application and API, a structured database, file storage, searchable evidence indexes, background workers, and an AI gateway. These are logical boundaries; the MVP can deploy as a modular application with a separate worker. The requirements do not depend on a particular web framework, LLM vendor, or vector database.

The weekly processing sequence is:

1. Determine reporting obligations from membership dates, project status, extensions, and exemptions.
2. Accept and version the student's report package; validate required project entries.
3. Sync relevant repository activity and ingest newly supplied artifacts.
4. Resolve identities and contributions; build a permission-labeled, time-bounded evidence snapshot.
5. Extract claims and match them to evidence, the frozen plan, and research history.
6. Apply the rubric, calculate deterministic metrics, and create a draft assessment with confidence and citations.
7. Present the draft for professor review; publish the approved version to the student.
8. Update dashboards, trends, and searchable research records using explicit version references.

Report acceptance must not wait for a repository or LLM provider to recover. Persist work first, then run jobs asynchronously. Job states must distinguish queued, running, completed, partial, and failed. Use bounded retries and idempotent job keys; provide manual retry without duplicate assessments or notifications.

The API must cover users and memberships, projects and milestones, report drafts/submissions/revisions, repository connections and sync status, evidence inspection, assessments and review actions, and professor queries. Exports were withdrawn in 0.4 (UI-06). Mutations must record actor and time; retryable submissions and external events must support idempotency.

## 11 Nonfunctional requirements

| Area | Proposed requirement and acceptance basis |
| --- | --- |
| Initial capacity | Up to 50 students, 30 active projects, and three years of reports **per workspace**, with a small number of workspaces per professor (AUTH-05); benchmark against at least 100,000 indexed evidence items |
| Interactive performance | p95 ordinary page/API response under 2 seconds, excluding upload transfers, initial imports, and AI generation; benchmark at 10 concurrent sessions |
| AI response time | p95 first meaningful response within 10 seconds and ordinary completion within 30 seconds on a defined test set and configured provider; show progress and a recoverable timeout |
| Assessment latency | 95% of ordinary assessments ready within 10 minutes after all required inputs are available; define bounded artifact sizes and measure under the pilot workload |
| Availability and recovery | Proposed 99.5% monthly availability; daily encrypted backups; target recovery point of 24 hours and recovery time of 4 hours; prove a restore before launch |
| Reliability | No report loss on worker/model failure; idempotent sync and processing; clear partial-data status; observable retry queues |
| Security | Encryption in transit and at rest, protected secrets, least-privilege connections, permission checks, audited administrative changes, safe file parsing and restricted URL fetching |
| Data control | Professor-configured retention and deletion; propagate authorized deletion to file storage, searchable indexes, answer caches, and derived records; document backup expiration |
| AI data boundary | Document what content reaches each model provider; support project-level restrictions or approved local processing for restricted research; never send credentials to a model |
| Source integrity | Treat retrieved text as untrusted input; it cannot override instructions, invoke actions, expose secrets, or alter access scope |
| Cost control | Track usage per job/project, cache unchanged artifacts, limit diff and document processing, and support configurable budgets with clear delayed-analysis states |
| Observability | Monitor ingestion failures, stale connections, queue latency, assessment versions, model errors, citation failures, and access denials without logging secrets or unrestricted raw research text |
| Usability | Responsive professor/student screens, keyboard-accessible reporting, readable tables and equations, and visible autosave and submission confirmation |
| Portability | Support model-provider replacement without migrating the authoritative research history. *The record-export half was withdrawn with UI-06 in 0.4 and is unmet by design; reinstating it means reinstating that requirement first* |

Capacity and latency figures are initial engineering targets. The implementation should specify benchmark corpus sizes, maximum per-job inputs, concurrency, and provider conditions before claiming compliance.

## 12 MVP and subsequent releases

| Release | Included capabilities |
| --- | --- |
| MVP | Two roles; invitations and permissions; projects and memberships; basic milestones and frozen weekly plans; structured weekly reports with attachments and history; one repository provider; identity mapping; permission-filtered evidence search; draft assessments and professor approval; cited professor Q&A; dashboards; workspaces and plural professor membership; the automatic missed-deadline email; backup |
| Next release | Second repository provider; richer review and issue evidence; experiment-tracker integrations; improved manuscript/version support; calendar integrations and further email notifications; configurable research-stage templates; longitudinal calibration tools; student-side assistant |
| Later, only when justified | Multi-professor collaboration, multiple labs, institutional SSO, richer scheduling, resource/compute-cost tracking, and isolated experiment verification |

Implement the MVP in dependency order: establish the records and reporting workflow; add repository evidence; calibrate the assessment rubric; then enable the professor assistant over the same authorized records. The rubric and assistant can be piloted before exposing assessments to students.

## 13 Acceptance scenarios and AI evaluation

| ID | Scenario | Required result |
| --- | --- | --- |
| AC-01 | A student belongs to two projects, one with a repository and one without | One weekly package contains both project entries; two separate assessments use appropriate evidence |
| AC-02 | A student on one project requests another student's private report or its citation URL | Access is denied in API, UI, search, cached responses, and downloads |
| AC-03 | A submitted report is revised after the professor has approved an assessment | Original report and assessment remain intact; a new assessment references the new version and awaits review |
| AC-04 | A repository connection fails during the reporting week | Report submission succeeds; the dashboard identifies stale evidence; no zero-work inference is made |
| AC-05 | A student documents a rigorous negative result or a useful theoretical result without commits | The rubric can credit learning, rigor, and relevant artifacts without requiring repository activity |
| AC-06 | Two students co-author a contribution, and one merges it | Joint attribution is retained; merger status alone does not transfer authorship; project totals deduplicate the artifact |
| AC-07 | A report claims a result for which accessible evidence is incomplete | The assessment labels the claim and uncertainty; the assistant does not present it as independently verified |
| AC-08 | An approved holiday, project pause, or extension applies | The obligation and deadline reflect the exception; no incorrect missing-report alert is generated |
| AC-09 | A webhook is delivered twice and the same sync range is retried | No duplicate event, contribution, notification, or score increase occurs |
| AC-10 | The professor asks for six-week progress across a rubric change | Answer cites the relevant weeks and labels the change; it does not present incompatible scores as directly comparable |
| AC-11 | A student's membership is removed after an answer was cached | Subsequent access to restricted underlying content, citations, and cached answers is denied |
| AC-12 | A repository README contains instructions to disclose private notes | The content is treated as evidence text and cannot change retrieval permissions or answer scope |
| AC-13 | A report is late, an LLM call fails, or a source arrives after approval | Original submission time is preserved; jobs can recover; approved history is not silently changed |
| AC-14 | A student submits repetitive commits or verbose text without new substantive evidence | Activity counts or length alone do not increase research-progress ratings |
| AC-15 | The professor asks for the number of missing reports | The answer matches structured obligations after exemptions and deadline rules, with an explicit as-of time |
| AC-16 | The application is restored from backup | Submitted versions, attachments, approvals, permissions, and source references are recoverable within agreed recovery targets |
| AC-17 | A student resubmits a package after a revision request on one of two project entries | The unchanged entry keeps its existing assessment; only the changed entry produces a new draft assessment |
| AC-18 | A student joins a project mid-period, or the previous report was missing, so no frozen plan exists | The report accepts a first plan; commitment completion is unavailable until the professor accepts the baseline; the progress rubric can still be applied to the available evidence |
| AC-19 | The deadline passes with one student unsubmitted, one submitted at 23:58, and one on approved leave | At 00:00 local time on the meeting day exactly one email goes to the unsubmitted student, none to the others, and the professor sees the unfulfilled obligation in-app; a retried job sends no duplicate |

Before enabling routine AI assessments, build a de-identified evaluation set containing coding, literature, theory, experiments, and writing. Include incomplete evidence, shared contributions, negative results, changed plans, multilingual reports, and adversarial repository text.

Proposed pilot gates: at least 30 student–project–weeks reviewed by the professor and 50 representative professor questions; all authorization scenarios pass; all exact count/date calculations match the authoritative data; at least 95% of evaluated factual claims are supported by their cited evidence; and missing-evidence examples produce an appropriate uncertainty response. Each scored rationale must include an evidence reference or explicit limitation.

Measure professor–model agreement by dimension, material correction rate, and variation across repeated runs. Establish an acceptable agreement threshold with the professor during the pilot rather than inventing a universal accuracy figure. If the rubric is inconsistent, retain qualitative drafts and component evidence while revising the scoring design. Approval remains a required publication step.

## 14 Decisions to confirm during implementation

Work can begin using the proposed defaults. Before implementing the relevant integration or publishing scores, confirm: the first repository provider and whether self-hosted instances are required; the weekly meeting day, which fixes the deadline, and whether any project needs a different meeting day; the mail provider; the baseline freeze point; permitted model/data-processing locations; the default student visibility policy; research-stage examples and rubric calibration; and the backup/hosting environment.

These choices do not change the central model: persistent research records, weekly student–project assessments, optional repository evidence, professor review, and source-cited answers.

## 15 Revision history

| Version | Date | Changes |
| --- | --- | --- |
| 0.1 | 11 September 2026 | Initial proposed specification |
| 0.2 | 11 September 2026 | Added baseline freeze point and empty-baseline handling (PROJ-04, AC-18); per-entry revision and re-assessment rules (REP-05, ASSESS-09, AC-17); excluded private supervision notes from the assessment evidence snapshot (ASSESS-01); defined who accepts completion fractions (ASSESS-05); added account recovery and professor break-glass procedure (AUTH-01); added notifications requirement (UI-07); added PlanBaseline entity and related invariant (section 9); clarified upload limit scope (REP-04), missing-report wording (REP-06), and student visibility of attributed contributions (REPO-04) |
| 0.3 | 11 September 2026 | Deadline is now fixed at 23:59 local time on the day before the weekly meeting (REP-01); added automatic missed-deadline email at 00:00 on the meeting day (REP-08, AC-19); email became a required MVP channel (UI-07, section 12); added meeting day and mail configuration to the data model (section 9); updated decisions to confirm (section 14) |
| 0.4 | 16 September 2026 | Withdrew exports (UI-06) and the in-app half of notifications, including muting (UI-07); both were built and are now removed — see use_cases.md §8.3 for what that cost. Dropped `notification_preferences` from the data model (section 9). Added professor-managed workspaces: create, rename, set timezone, archive, and an invitation that names the workspace it enrols into, so every student has one from enrolment. Ownership is the administration relation and `Scope` still names one workspace ([ADR 0012](adr/0012-workspace-ownership.md), amending ADR 0011). **Moving an enrolled student between workspaces is not possible and is not merely unbuilt:** eight tables carry a composite foreign key onto `users(workspace_id, id)` with no `ON UPDATE CASCADE`, and enrolment is invitation-only, so every account is pinned from creation. *(Corrected in 0.5: migration 0020 gave four of the eight `ON UPDATE CASCADE`, so an account that has written nothing does move. The later half of this row, which describes the move rule, is the accurate one.)* A workspace is part of a user's identity, not an attribute of it — section 9's same-workspace invariant read from the other direction. A professor may belong to several workspaces at once and works in one of them at a time ([ADR 0015](adr/0015-plural-workspace-membership.md)); joining adds a membership and takes them there, leaving gives one up, and a workspace can be archived once nobody belongs to it. A professor reads across every workspace they belong to and writes into the one they are working in ([ADR 0016](adr/0016-reads-span-membership.md)); screens group what they show by workspace. A professor may also move a student to another workspace they administer, but only before that student has done any work: project memberships, submitted reports and attributed contributions are pinned to the workspace they were written in and the database refuses to move an account that has any. Leaving needs a destination and is refused while it would leave people in a workspace with no active professor (AUTH-01). Still unspecified: requirement IDs for any of the above, and whether section 11's one-workspace sizing still holds |
| 0.5 | 16 September 2026 | Minted the requirement IDs 0.4 left unwritten: **AUTH-04** (workspaces), **AUTH-05** (belonging and scope), **AUTH-06** (moving an account) and **UI-08** (the workspace and roll screens). Without them the whole feature was invisible to `scripts/check_traceability.py`, which only checks IDs that exist. Corrected 0.4's claim that moving an enrolled student is impossible: migration 0020 gave `invitations`, `sessions`, `password_resets` and `notifications` `ON UPDATE CASCADE`, so an account with no history moves and `POST /users/{user_id}/workspace` does it; `project_memberships`, `weekly_reports`, `developer_identities` and `contributions` still refuse, which is the rule rather than a gap. Removed the export residue 0.4's withdrawal of UI-06 left behind (§2 capability table, AUTH-02, QA-06, §10 API coverage, §11 Data control and Portability, §12 MVP, AC-02). Amended REP-07: the reminder records are written but nothing displays them and only the missed-deadline message is emailed, and no code path authors professor feedback — so the pre-deadline half of REP-07 reaches nobody today. Restated §11 capacity per-workspace, which 0.4 left open. Extended AUTH-03 to say that a cached answer spanning workspaces dies when any of them changes |
| 0.6 | 17 September 2026 | Students own the projects they report on. **AUTH-01** no longer reserves every membership change to the professor: a student may start a project, join one opened to joining, and leave one, but may still not act for another account, and enrolment into the workspace stays invitation-only. Minted **PROJ-07** (self-service membership) and **AUTH-07** (project authorship). **PROJ-01** now states that a student's project is active on creation while a professor's is proposed — activation records a second party's assent and a student's project has no second party, and a proposed project owes nothing (REP-01), so the alternative was a project that produces nothing and no screen saying why. **PROJ-02** now records how each membership began, because a student joining part-way through a week owes from the next one while a professor assigning part-way through a week owes that week. Joining is gated per project by a professor's flag, default closed, so nothing became joinable when this shipped: a membership grants the project's plan, milestones, tasks and decisions and the identity of everyone who has worked on it, so unbounded joining would have made the member list a roster of the whole workspace ([ADR 0017](adr/0017-students-own-their-projects.md)). No private record moves: reports, assessments, feedback, plan baselines and supervision notes are keyed to a student, not to a project |
