/**
 * UI-01: the professor's current week — what is missing, what is waiting, what is in the way.
 *
 * The design rule for this page is that nothing appears as a bare number. An outstanding count
 * carries the instant it was true; a quiet repository is labelled as a sync problem rather than
 * shown as a week with no work (AC-04); and analysis that did not run says whether the model
 * failed or the budget ran out, because those need different responses.
 */
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Badge, FreshnessBadge } from "@/components/evidence/Badges";
import { useOverview } from "@/features/overview/queries";
import { formatInstant, formatLocalDate } from "@/lib/dates";

export function OverviewPage() {
  const { t } = useTranslation();
  const overview = useOverview();

  if (overview.isPending) return <p className="text-muted-foreground">{t("common.loading")}</p>;
  if (overview.isError) return <p className="text-muted-foreground">{t("overview.unavailable")}</p>;

  const raw = overview.data;
  const data = {
    ...raw,
    outstanding: { ...raw.outstanding, entries: raw.outstanding.entries ?? [] },
    review_queue: raw.review_queue ?? [],
    sync_issues: raw.sync_issues ?? [],
    stalled_analyses: raw.stalled_analyses ?? [],
  };
  const period = data.current_period;

  return (
    <section className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{t("overview.title")}</h1>
        {period ? (
          <>
            <p className="text-sm text-muted-foreground">
              {formatLocalDate(period.local_start)} – {formatLocalDate(period.local_end)}
            </p>
            <p className="text-sm" data-testid="deadline">
              {t("me.dueBy")} {formatInstant(period.deadline_utc)}
            </p>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{t("me.noPeriod")}</p>
        )}
      </header>

      {data.ai_budget.analysis_delayed && (
        <p
          className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm dark:bg-amber-950"
          data-testid="budget-warning"
        >
          {data.ai_budget.reason}
        </p>
      )}

      <Section
        title={t("overview.outstanding")}
        empty={t("overview.nothingOutstanding")}
        count={data.outstanding.count}
        note={`${data.outstanding.note} ${t("overview.asOf", {
          when: formatInstant(data.outstanding.as_of),
        })}`}
      >
        <ul className="divide-y divide-border">
          {data.outstanding.entries.map((entry, index) => (
            <li
              key={`${String(entry.student_id)}:${String(entry.project_id)}:${index}`}
              className="flex items-center justify-between px-4 py-2 text-sm"
            >
              <Link to={`/students/${String(entry.student_id)}`} className="underline">
                {String(entry.student_id).slice(0, 8)}
              </Link>
              <span className="text-muted-foreground">{String(entry.project_title ?? "")}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        title={t("overview.reviewQueue")}
        empty={t("overview.nothingToReview")}
        count={data.review_queue.length}
      >
        <ul className="divide-y divide-border">
          {data.review_queue.map((draft, index) => (
            <li
              key={`${String(draft.assessment_id)}:${index}`}
              className="flex items-center justify-between gap-3 px-4 py-2 text-sm"
            >
              <Link to={`/review/${String(draft.assessment_id)}`} className="underline">
                {t("overview.draftFor", { student: String(draft.student_id).slice(0, 8) })}
              </Link>
              <Badge tone={draft.confidence === "high" ? "good" : "warn"}>
                {t(`assessment.confidence.${String(draft.confidence)}`, {
                  defaultValue: String(draft.confidence),
                })}
              </Badge>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        title={t("overview.syncIssues")}
        empty={t("overview.syncHealthy")}
        count={data.sync_issues.length}
        note={t("overview.syncNote")}
      >
        <ul className="divide-y divide-border">
          {data.sync_issues.map((issue, index) => (
            <li
              key={`${String(issue.repository_id)}:${index}`}
              className="flex items-center justify-between px-4 py-2 text-sm"
            >
              <span>{String(issue.full_name)}</span>
              <FreshnessBadge
                state={String(issue.state)}
                lastFinishedAt={issue.last_finished_at as string | null}
              />
            </li>
          ))}
        </ul>
      </Section>

      <Section
        title={t("overview.stalled")}
        empty={t("overview.nothingStalled")}
        count={data.stalled_analyses.length}
        note={t("overview.stalledNote")}
      >
        <ul className="divide-y divide-border">
          {data.stalled_analyses.map((run, index) => (
            <li key={`${String(run.run_id)}:${index}`} className="px-4 py-2 text-sm">
              <span className="font-medium">{String(run.state)}</span>
              <span className="text-muted-foreground"> — {String(run.reason || "")}</span>
            </li>
          ))}
        </ul>
      </Section>
    </section>
  );
}

/** Always rendered, even at zero: a missing section reads as a broken screen. */
function Section({
  title,
  empty,
  count,
  note,
  children,
}: {
  title: string;
  empty: string;
  count: number;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <h2 className="flex items-center gap-2 text-sm font-medium">
        {title}
        <Badge tone={count === 0 ? "neutral" : "warn"}>{count}</Badge>
      </h2>
      <div className="rounded-lg border border-border">
        {count === 0 ? (
          <p className="px-4 py-2 text-sm text-muted-foreground">{empty}</p>
        ) : (
          children
        )}
      </div>
      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </div>
  );
}
