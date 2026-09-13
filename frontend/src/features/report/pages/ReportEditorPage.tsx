import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { Attachments } from "@/features/report/components/Attachments";
import { AutosaveIndicator } from "@/features/report/components/AutosaveIndicator";
import { EntryForm } from "@/features/report/components/EntryForm";
import { emptyEntry, type EntryDraft } from "@/features/report/entry";
import {
  useArtifacts,
  useObligations,
  usePeriods,
  useProjects,
  useReport,
  useSaveDraft,
  useSubmitReport,
} from "@/features/report/queries";
import { useAutosave } from "@/hooks/useAutosave";
import { formatInstant, formatLocalDate } from "@/lib/dates";

type Drafts = Record<string, EntryDraft>;

/**
 * REP-02: one weekly package with a tab per required project entry. The student submits once;
 * the assessments that follow are separate per project (AC-01).
 */
export function ReportEditorPage() {
  const { t } = useTranslation();
  const { periodId = "" } = useParams();
  const periods = usePeriods();
  const obligations = useObligations(periodId);
  const projects = useProjects();
  const report = useReport(periodId);
  const saveDraft = useSaveDraft(periodId);
  const submit = useSubmitReport(periodId);

  const [drafts, setDrafts] = useState<Drafts | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [active, setActive] = useState<string | null>(null);

  const period = periods.data?.find((candidate) => candidate.id === periodId);
  const required = (obligations.data ?? []).filter((item) => item.state === "required");
  const titleOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.title ?? projectId;
  const stageOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.stage ?? "implementation";

  // Recover the saved draft once the obligations, the report *and* the projects have arrived.
  // Projects are in the guard because `stageOf` falls back to "implementation" without them, and
  // drafts are seeded once: a slow /projects response would otherwise submit every entry under
  // the wrong stage, with nothing on screen to show it (the stage is not an editable field).
  if (drafts === null && obligations.data && report.isFetched && projects.data) {
    const saved = (report.data?.draft_content as { entries?: Drafts } | undefined)?.entries ?? {};
    const initial: Drafts = {};
    for (const obligation of required) {
      initial[obligation.project_id] =
        saved[obligation.project_id] ??
        emptyEntry(obligation.project_id, stageOf(obligation.project_id));
    }
    setDrafts(initial);
    setActive(required[0]?.project_id ?? null);
  }

  // `drafts`, not `drafts ?? {}`: an empty object would be taken as the loaded draft, and merely
  // opening the editor would PATCH it 1.5 s later — creating a DRAFT report and flipping the
  // student off "not started" without them typing anything.
  const autosave = useAutosave(drafts, (value) => saveDraft.mutateAsync({ entries: value }));

  if (periods.isPending || obligations.isPending || projects.isPending || drafts === null) {
    return <p className="stamp">{t("common.loading")}</p>;
  }
  if (!period) return <p className="text-sm text-muted-foreground">{t("me.noPeriod")}</p>;

  const problem = submit.error instanceof ApiError ? submit.error.problem.detail : null;

  async function onSubmit() {
    // The flush is a full round-trip, and `submit.isPending` is false throughout it — so without
    // this the button stayed enabled and a second click started a second submission (REP-05).
    if (submitting) return;
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
        next_plan: draft.next_plan_text ? { outcomes: [draft.next_plan_text] } : {},
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
        <p className="font-mono text-[12.5px] text-muted-foreground" data-testid="deadline">
          {t("me.dueBy")} {formatInstant(period.deadline_utc)}
        </p>
      </header>

      <div role="tablist" aria-label={t("report.tabs")} className="mt-5 flex flex-wrap gap-1.5">
        {required.map((obligation) => (
          <button
            key={obligation.id}
            role="tab"
            type="button"
            aria-selected={active === obligation.project_id}
            onClick={() => setActive(obligation.project_id)}
            className={
              active === obligation.project_id
                ? "rounded border border-foreground bg-muted px-3.5 py-2 text-[13px] font-medium"
                : "rounded border border-border bg-surface px-3.5 py-2 text-[13px] text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
            }
          >
            {titleOf(obligation.project_id)}
          </button>
        ))}
      </div>

      {active && drafts[active] && (
        <>
          <p className="stamp mt-3.5">
            Entry stage: {stageOf(active)} · one submission covers every required entry
          </p>
          <EntryForm
            entry={drafts[active]}
            onChange={(entry) => setDrafts({ ...drafts, [entry.project_id]: entry })}
          />
          {/* REP-04: evidence is attached per project entry, not per package. */}
          <EntryAttachments projectId={active} periodId={periodId} />
        </>
      )}

      {problem && (
        <p role="alert" className="mt-5 text-sm text-bad">
          {problem}
        </p>
      )}
      {submit.isSuccess && (
        <p className="mt-5 font-mono text-[12.5px] text-good">
          {t("report.submitted", { version: submit.data.version_no })}
        </p>
      )}

      <div className="mt-7 flex flex-wrap items-center justify-between gap-4 border-t border-border pt-5">
        <AutosaveIndicator state={autosave.state} savedAt={autosave.savedAt} />
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

/**
 * The attachments already on this entry, read from the server rather than remembered in this tab.
 * Refetched after each one is attached, so the list is what the professor will also see.
 */
function EntryAttachments({ projectId, periodId }: { projectId: string; periodId: string }) {
  const queryClient = useQueryClient();
  const artifacts = useArtifacts({ periodId, projectId });
  return (
    <Attachments
      projectId={projectId}
      periodId={periodId}
      attachments={artifacts.data ?? []}
      onAttached={() => void queryClient.invalidateQueries({ queryKey: ["artifacts"] })}
    />
  );
}
