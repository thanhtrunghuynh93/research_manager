import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { AutosaveIndicator } from "@/features/report/components/AutosaveIndicator";
import { EntryForm } from "@/features/report/components/EntryForm";
import { emptyEntry, type EntryDraft } from "@/features/report/entry";
import {
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
  const [active, setActive] = useState<string | null>(null);

  const period = periods.data?.find((candidate) => candidate.id === periodId);
  const required = (obligations.data ?? []).filter((item) => item.state === "required");
  const titleOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.title ?? projectId;
  const stageOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.stage ?? "implementation";

  // Recover the saved draft once both the obligations and the report have arrived.
  if (drafts === null && obligations.data && report.isFetched) {
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

  const autosave = useAutosave(drafts ?? {}, (value) => saveDraft.mutateAsync({ entries: value }));

  if (periods.isPending || obligations.isPending || drafts === null) {
    return <p className="text-muted-foreground">{t("common.loading")}</p>;
  }
  if (!period) return <p className="text-muted-foreground">{t("me.noPeriod")}</p>;

  const problem = submit.error instanceof ApiError ? submit.error.problem.detail : null;

  async function onSubmit() {
    await autosave.flush();
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
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{t("report.title")}</h1>
        <p className="text-sm text-muted-foreground">
          {formatLocalDate(period.local_start)} – {formatLocalDate(period.local_end)}
        </p>
        <p className="text-sm" data-testid="deadline">
          {t("me.dueBy")} {formatInstant(period.deadline_utc)}
        </p>
      </header>

      <div role="tablist" aria-label={t("report.tabs")} className="flex flex-wrap gap-2">
        {required.map((obligation) => (
          <button
            key={obligation.id}
            role="tab"
            type="button"
            aria-selected={active === obligation.project_id}
            onClick={() => setActive(obligation.project_id)}
            className={
              active === obligation.project_id
                ? "rounded-md border border-border bg-muted px-3 py-1.5 text-sm font-medium"
                : "rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground"
            }
          >
            {titleOf(obligation.project_id)}
          </button>
        ))}
      </div>

      {active && drafts[active] && (
        <EntryForm
          entry={drafts[active]}
          onChange={(entry) => setDrafts({ ...drafts, [entry.project_id]: entry })}
        />
      )}

      {problem && (
        <p role="alert" className="text-sm text-red-600">
          {problem}
        </p>
      )}
      {submit.isSuccess && (
        <p className="text-sm text-green-700">
          {t("report.submitted", { version: submit.data.version_no })}
        </p>
      )}

      <div className="flex items-center justify-between border-t border-border pt-4">
        <AutosaveIndicator state={autosave.state} savedAt={autosave.savedAt} />
        <button
          type="button"
          onClick={() => void onSubmit()}
          disabled={submit.isPending}
          className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background disabled:opacity-60"
        >
          {t("report.submit")}
        </button>
      </div>
    </section>
  );
}
