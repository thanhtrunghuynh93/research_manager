import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { Failure } from "@/components/Failure";
import { Attachments } from "@/features/report/components/Attachments";
import { AutosaveIndicator } from "@/features/report/components/AutosaveIndicator";
import { EntryForm } from "@/features/report/components/EntryForm";
import {
  draftOfEntry,
  emptyEntry,
  firstHoursProblem,
  planOfText,
  type EntryDraft,
} from "@/features/report/entry";
import {
  useArtifacts,
  useObligations,
  usePeriods,
  useProjects,
  useReport,
  useRevisionRequests,
  useSaveDraft,
  useSubmitReport,
  useVersion,
} from "@/features/report/queries";
import { useAutosave } from "@/hooks/useAutosave";
import { useTimezone } from "@/features/calendar/queries";
import { formatInstant, formatLocalDate } from "@/lib/dates";

type Drafts = Record<string, EntryDraft>;

/**
 * REP-02: one weekly package with a tab per required project entry. The student submits once;
 * the assessments that follow are separate per project (AC-01).
 */
export function ReportEditorPage() {
  const { t } = useTranslation();
  const { periodId = "" } = useParams();
  const timezone = useTimezone();
  const periods = usePeriods();
  const obligations = useObligations(periodId);
  const projects = useProjects();
  const report = useReport(periodId);
  const revisions = useRevisionRequests(report.data?.id);
  const submittedVersion = useVersion(report.data?.current_version_id);
  const saveDraft = useSaveDraft(periodId);
  const submit = useSubmitReport(periodId);

  const [drafts, setDrafts] = useState<Drafts | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [active, setActive] = useState<string | null>(null);

  const period = periods.data?.find((candidate) => candidate.id === periodId);
  const required = (obligations.data ?? []).filter((item) => item.state === "required");
  // REP-05: the professor asked for one project's entry to be changed. The request was on the
  // student's home screen and in the read-only reader, and absent from the one screen where the
  // change is actually made — so a student arrived at the editor knowing a revision was wanted
  // and with nothing to say which entry or why.
  const openRequests = (revisions.data ?? []).filter((request) => !request.resolved_in_version_id);
  const requestsFor = (projectId: string) =>
    openRequests.filter((request) => String(request.project_id) === projectId);
  const titleOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.title ?? projectId;
  const stageOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.stage ?? "implementation";

  // Recover what the student last wrote once the obligations, the report, the submitted version
  // *and* the projects have arrived. Projects are in the guard because `stageOf` falls back to
  // "implementation" without them, and drafts are seeded once: a slow /projects response would
  // otherwise submit every entry under the wrong stage, with nothing on screen to show it (the
  // stage is not an editable field).
  //
  // Draft first, then the last submitted version, then empty. The middle step is the one that was
  // missing: a report submitted without an autosaved draft — the seed does exactly this — reopened
  // as blank boxes over a version that had content, and submitting them overwrote it.
  const versionReady = !report.data?.current_version_id || submittedVersion.isFetched;
  // The revision requests are in the guard for the same reason the projects are: the tab this
  // opens on is chosen from them, and seeding before they arrive opened the first project every
  // time — including when the professor had asked about the third.
  const revisionsReady = !report.data?.id || revisions.isFetched;
  if (
    drafts === null &&
    obligations.data &&
    report.isFetched &&
    projects.data &&
    versionReady &&
    revisionsReady
  ) {
    const saved = (report.data?.draft_content as { entries?: Drafts } | undefined)?.entries ?? {};
    const sent = new Map(
      (submittedVersion.data?.entries ?? []).map((entry) => [
        String(entry.project_id),
        draftOfEntry(entry),
      ]),
    );
    const initial: Drafts = {};
    for (const obligation of required) {
      initial[obligation.project_id] =
        saved[obligation.project_id] ??
        sent.get(obligation.project_id) ??
        emptyEntry(obligation.project_id, stageOf(obligation.project_id));
    }
    setDrafts(initial);
    // Open on the entry that was asked about, when one was: it is the reason the student is here.
    const asked = required.find((obligation) =>
      openRequests.some((request) => String(request.project_id) === obligation.project_id),
    );
    setActive(asked?.project_id ?? required[0]?.project_id ?? null);
  }

  // `drafts`, not `drafts ?? {}`: an empty object would be taken as the loaded draft, and merely
  // opening the editor would PATCH it 1.5 s later — creating a DRAFT report and flipping the
  // student off "not started" without them typing anything.
  const autosave = useAutosave(drafts, (value) => saveDraft.mutateAsync({ entries: value }));

  // The error states come first, because the loading state below cannot end without them: the
  // obligations seed the drafts and the guard waits for the drafts, so a period this student
  // cannot read 404s and the screen sat on "Loading…" for ever rather than reaching the message
  // written for exactly this case.
  if (obligations.isError) {
    return <p className="text-sm text-muted-foreground">{t("report.unknownPeriod")}</p>;
  }
  // A report that is merely absent is `null` and not an error — that is a week not yet started.
  // An error here is a real failure, and it must not fall through to an empty form: the fields
  // would seed blank over a version that has content, which is how a resubmission erased a week.
  if (report.isError) {
    return (
      <p className="text-sm text-muted-foreground">
        <Failure error={report.error} />
      </p>
    );
  }
  if (periods.isPending || obligations.isPending || projects.isPending || drafts === null) {
    return <p className="stamp">{t("common.loading")}</p>;
  }
  // Not "no calendar has been configured": the calendar is fine, this week is not one of ours.
  if (!period) return <p className="text-sm text-muted-foreground">{t("report.unknownPeriod")}</p>;

  const problem = submit.error instanceof ApiError ? submit.error.problem : null;
  // The API names the projects it is missing; rendering `detail` alone told a student whose tabs
  // were all full that the package was incomplete and left them to guess which one.
  const missing = (Array.isArray(problem?.missing_project_ids) ? problem.missing_project_ids : [])
    .map((projectId) => titleOf(String(projectId)))
    .join(", ");
  const owed = required.filter((obligation) => !obligation.submitted).length;
  // An hours figure the server will refuse. Checked here rather than left to the round trip: the
  // box advertised bounds it did not enforce, and the 422 that came back took the whole page with
  // it. That crash is fixed, but a student should not meet a server error for a rule the form
  // already knows, and the tab it is on has to be named — the offending field may be behind a tab
  // that is not open.
  const badHours = drafts ? firstHoursProblem(drafts) : null;
  // More than one version means the record has moved on from the first submission, and the notice
  // should say so — `/me` has read "Resubmitted" for this state all along.
  const resubmitted = (submittedVersion.data?.version_no ?? 1) > 1;

  async function onSubmit() {
    // The flush is a full round-trip, and `submit.isPending` is false throughout it — so without
    // this the button stayed enabled and a second click started a second submission (REP-05).
    if (submitting) return;
    if (badHours) {
      setActive(badHours.projectId);
      return;
    }
    setSubmitting(true);
    try {
      await autosave.flush();
    } finally {
      setSubmitting(false);
    }
    submit.mutate(
      Object.values(drafts ?? {}).map((draft) => ({
        project_id: draft.project_id,
        stage: draft.stage,
        work_performed: draft.work_performed,
        results: draft.results,
        deviations: draft.deviations,
        questions: draft.questions,
        next_plan: planOfText(draft.next_plan_text),
        hours: draft.hours === "" ? null : Number(draft.hours),
      })),
    );
  }

  return (
    <section className="max-w-3xl animate-rise-in">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-4">
        <div>
          <p className="eyebrow mb-1.5">
            {formatLocalDate(period.local_start)} – {formatLocalDate(period.local_end)}
          </p>
          <h1 className="page-title">{t("report.title")}</h1>
        </div>
        <div className="text-right">
          <p className="font-mono text-[12.5px] text-muted-foreground" data-testid="deadline">
            {t("me.dueBy")} {formatInstant(period.deadline_utc, timezone)}
          </p>
          {/* Without this a submitted week and an untouched one were pixel-identical, which is
              what made resubmitting over your own package an easy mistake to make.

              The time is the *current version's*, not `first_submitted_at`. Reading the first
              submission meant this line never moved: it said "Submitted Sep 17, 10:54" in the
              same breath as "Submitted as version 16", four versions and a day later. A student
              checking near a deadline whether this week's work went in was told about a different
              week's submission. */}
          {report.data?.first_submitted_at ? (
            <p className="stamp mt-1" data-testid="already-submitted">
              {t(resubmitted ? "report.resubmitted" : "report.alreadySubmitted", {
                when: formatInstant(
                  submittedVersion.data?.submitted_at ?? report.data.first_submitted_at,
                  timezone,
                ),
                version: submittedVersion.data?.version_no,
              })}
            </p>
          ) : null}
          {report.data?.first_submitted_at ? (
            <Link
              to={`/report/${periodId}/submitted`}
              className="link mt-1 block font-mono text-[11.5px]"
            >
              {t("report.reader.seeSubmitted")}
            </Link>
          ) : null}
          {/* A week can be submitted and still incomplete — a project joined or started after the
              package went in owes an entry the submission never covered. */}
          {report.data?.first_submitted_at && owed > 0 ? (
            <p className="mt-1 font-mono text-[11.5px] text-warn" data-testid="still-owed">
              {t("report.stillOwed", { count: owed })}
            </p>
          ) : null}
        </div>
      </header>

      <EntryTabs
        tabs={required.map((obligation) => ({
          projectId: obligation.project_id,
          title: titleOf(obligation.project_id),
          submitted: obligation.submitted,
          revisionRequested: requestsFor(obligation.project_id).length > 0,
        }))}
        active={active}
        onSelect={setActive}
      />

      {active && drafts[active] && (
        <div
          role="tabpanel"
          id={`entry-panel-${active}`}
          aria-labelledby={`entry-tab-${active}`}
          tabIndex={0}
        >
          <p className="stamp mt-3.5">
            Entry stage: {stageOf(active)} · one submission covers every required entry
          </p>
          {requestsFor(active).map((request) => (
            <p
              key={request.id}
              className="mt-3.5 border-l-[3px] border-l-warn-rule bg-muted px-3.5 py-2.5 text-[13px] text-warn"
              data-testid="revision-request"
            >
              {t("report.reader.revisionAsked", {
                when: formatInstant(request.created_at, timezone),
              })}{" "}
              {request.reason}
            </p>
          ))}
          <EntryForm
            entry={drafts[active]}
            onChange={(entry) => setDrafts({ ...drafts, [entry.project_id]: entry })}
          />
          {/* REP-04: evidence is attached per project entry, not per package. */}
          <EntryAttachments
            projectId={active}
            periodId={periodId}
            reading={Boolean(report.data?.first_submitted_at)}
          />
        </div>
      )}

      {badHours && (
        <p role="alert" className="mt-5 text-sm text-bad" data-testid="submit-blocked">
          {t("report.hoursBlocks", { project: titleOf(badHours.projectId) })}
        </p>
      )}
      {problem && (
        <p role="alert" className="mt-5 text-sm text-bad">
          {missing ? t("report.missingEntries", { projects: missing }) : problem.detail}
        </p>
      )}
      {submit.isSuccess && (
        <p className="mt-5 font-mono text-[12.5px] text-good">
          {t("report.submitted", { version: submit.data.version_no })}
        </p>
      )}

      <div className="mt-7 flex flex-wrap items-center justify-between gap-4 border-t border-border pt-5">
        <AutosaveIndicator state={autosave.state} savedAt={autosave.savedAt} timezone={timezone} />
        <button
          type="button"
          onClick={() => void onSubmit()}
          disabled={submitting || submit.isPending}
          className="btn-primary"
        >
          {t("report.submit")}
        </button>
      </div>
    </section>
  );
}

type TabDescriptor = {
  projectId: string;
  title: string;
  submitted: boolean;
  revisionRequested: boolean;
};

/**
 * The tab per required project (REP-02), as the ARIA tabs pattern rather than as its appearance.
 *
 * The strip used to be `role="tab"` buttons with no panel, no `aria-controls` and every tab in the
 * tab order: a screen reader announced "tab 1 of 3" and offered nowhere to go, and a keyboard
 * reader tabbed through all of them instead of arrowing between them. Selection follows focus,
 * which is the right variant here because switching tabs shows a form rather than loading
 * anything.
 *
 * Each tab also says whether its entry is in the submitted package. Without that the one project
 * a student still owes looked exactly like the three they had already written.
 */
function EntryTabs({
  tabs,
  active,
  onSelect,
}: {
  tabs: TabDescriptor[];
  active: string | null;
  onSelect: (projectId: string) => void;
}) {
  const { t } = useTranslation();
  const buttons = useRef(new Map<string, HTMLButtonElement>());

  function move(from: number, delta: number) {
    const next = tabs[(from + delta + tabs.length) % tabs.length];
    if (!next) return;
    onSelect(next.projectId);
    buttons.current.get(next.projectId)?.focus();
  }

  return (
    <div role="tablist" aria-label={t("report.tabs")} className="mt-5 flex flex-wrap gap-1.5">
      {tabs.map((tab, index) => {
        const selected = active === tab.projectId;
        return (
          <button
            key={tab.projectId}
            ref={(node) => {
              if (node) buttons.current.set(tab.projectId, node);
              else buttons.current.delete(tab.projectId);
            }}
            role="tab"
            type="button"
            id={`entry-tab-${tab.projectId}`}
            aria-selected={selected}
            aria-controls={`entry-panel-${tab.projectId}`}
            // Roving: one stop for the whole strip, and the arrow keys move within it.
            tabIndex={selected ? 0 : -1}
            onClick={() => onSelect(tab.projectId)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "ArrowDown") move(index, 1);
              else if (event.key === "ArrowLeft" || event.key === "ArrowUp") move(index, -1);
              else if (event.key === "Home") move(0, 0);
              else if (event.key === "End") move(tabs.length - 1, 0);
              else return;
              event.preventDefault();
            }}
            className={
              selected
                ? "rounded border border-foreground bg-muted px-3.5 py-2 text-[13px] font-medium"
                : "rounded border border-border bg-surface px-3.5 py-2 text-[13px] text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
            }
          >
            {tab.title}
            {/* A requested revision outranks "Submitted": the entry is in, and it is the one
                thing on this screen that still wants doing. */}
            <span
              className={
                tab.revisionRequested || !tab.submitted
                  ? "ml-2 font-mono text-[10px] uppercase tracking-[0.06em] text-warn"
                  : "ml-2 font-mono text-[10px] uppercase tracking-[0.06em] text-good"
              }
              data-testid={`tab-state-${tab.projectId}`}
            >
              {t(
                tab.revisionRequested
                  ? "report.state.revision_requested"
                  : tab.submitted
                    ? "report.obligation.submitted"
                    : "report.obligation.required",
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * The attachments already on this entry, read from the server rather than remembered in this tab.
 * Refetched after each one is attached, so the list is what the professor will also see.
 */
function EntryAttachments({
  projectId,
  periodId,
  reading,
}: {
  projectId: string;
  periodId: string;
  /** Submitting the week is what queues the reading, so that is when the badges start moving. */
  reading: boolean;
}) {
  const queryClient = useQueryClient();
  const artifacts = useArtifacts({ periodId, projectId }, reading);
  return (
    <Attachments
      projectId={projectId}
      periodId={periodId}
      attachments={artifacts.data ?? []}
      onAttached={() => void queryClient.invalidateQueries({ queryKey: ["artifacts"] })}
    />
  );
}
