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

  if (overview.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (overview.isError)
    return <p className="text-sm text-muted-foreground">{t("overview.unavailable")}</p>;

  const raw = overview.data;
  const data = {
    ...raw,
    outstanding: { ...raw.outstanding, entries: raw.outstanding.entries ?? [] },
    review_queue: raw.review_queue ?? [],
    sync_issues: raw.sync_issues ?? [],
    stalled_analyses: raw.stalled_analyses ?? [],
    // Absent means "this deployment predates the mail section", not "mail is broken". The whole
    // screen is the professor's week; it must not go blank over a field it did not get.
    mail: raw.mail ?? {
      warning: false,
      reason: "",
      failed_notifications: 0,
      failed_token_emails: 0,
    },
  };
  const period = data.current_period;

  return (
    <section className="animate-rise-in">
      <header className="flex flex-wrap items-end justify-between gap-5 border-b border-border pb-5">
        <div>
          <p className="eyebrow mb-1.5">{t("overview.currentPeriod")}</p>
          <h1 className="page-title">{t("overview.title")}</h1>
          {period ? (
            <p className="mt-2 font-mono text-[13px] text-muted-foreground">
              {formatLocalDate(period.local_start)} – {formatLocalDate(period.local_end)}
            </p>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">{t("me.noPeriod")}</p>
          )}
        </div>
      </header>

      {data.ai_budget.analysis_delayed && (
        <p className="notice-warn mt-6 flex gap-3" data-testid="budget-warning">
          <span className="font-mono text-[10px] uppercase leading-relaxed tracking-[0.12em]">
            budget
          </span>
          <span>{data.ai_budget.reason}</span>
        </p>
      )}

      {/* An invitation that never sent is an enrolment that did not happen, and nothing else on
          this screen would ever mention the person it was for: they have no session, no in-app
          message, and no other way into an invitation-only system. */}
      {data.mail.warning && (
        <p className="notice-warn mt-6 flex gap-3" data-testid="mail-warning">
          <span className="font-mono text-[10px] uppercase leading-relaxed tracking-[0.12em]">
            mail
          </span>
          <span>{data.mail.reason}</span>
        </p>
      )}

      <div className="mt-8 grid gap-6 [grid-template-columns:repeat(auto-fit,minmax(320px,1fr))]">
        <Section
          title={t("overview.outstanding")}
          empty={t("overview.nothingOutstanding")}
          count={data.outstanding.count}
          note={`${data.outstanding.note} ${t("overview.asOf", {
            when: formatInstant(data.outstanding.as_of),
          })}`}
        >
          {data.outstanding.entries.map((entry, index) => (
            <li
              key={`${String(entry.student_id)}:${String(entry.project_id)}:${index}`}
              className="row"
            >
              <Link to={`/students/${String(entry.student_id)}`} className="font-mono text-[13px]">
                {String(entry.student_id).slice(0, 8)}
              </Link>
              <span className="text-right text-[13px] text-muted-foreground">
                {String(entry.project_title ?? "")}
              </span>
            </li>
          ))}
        </Section>

        <Section
          title={t("overview.reviewQueue")}
          empty={t("overview.nothingToReview")}
          count={data.review_queue.length}
        >
          {data.review_queue.map((draft, index) => (
            <li key={`${String(draft.assessment_id)}:${index}`} className="row">
              <Link to={`/review/${String(draft.assessment_id)}`} className="text-[13px]">
                {t("overview.draftFor", { student: String(draft.student_id).slice(0, 8) })}
              </Link>
              <Badge tone={draft.confidence === "high" ? "good" : "warn"}>
                {t(`assessment.confidence.${String(draft.confidence)}`, {
                  defaultValue: String(draft.confidence),
                })}
              </Badge>
            </li>
          ))}
        </Section>

        <Section
          title={t("overview.syncIssues")}
          empty={t("overview.syncHealthy")}
          count={data.sync_issues.length}
          note={t("overview.syncNote")}
        >
          {data.sync_issues.map((issue, index) => (
            <li key={`${String(issue.repository_id)}:${index}`} className="row">
              <span className="font-mono text-[12.5px]">{String(issue.full_name)}</span>
              <FreshnessBadge
                state={String(issue.state)}
                lastFinishedAt={issue.last_finished_at as string | null}
              />
            </li>
          ))}
        </Section>

        <Section
          title={t("overview.stalled")}
          empty={t("overview.nothingStalled")}
          count={data.stalled_analyses.length}
          note={t("overview.stalledNote")}
        >
          {data.stalled_analyses.map((run, index) => (
            <li key={`${String(run.run_id)}:${index}`} className="px-4 py-2.5 text-[13px]">
              <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-warn">
                {String(run.state)}
              </span>
              <span className="text-muted-foreground"> — {String(run.reason || "")}</span>
            </li>
          ))}
        </Section>
      </div>
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
    <div>
      <h2 className="flex items-baseline gap-2.5">
        <span className="section-title">{title}</span>
        <span className={count === 0 ? "chip chip-neutral" : "chip chip-warn"}>{count}</span>
      </h2>
      <ul className="panel mt-2.5">
        {count === 0 ? (
          <li className="px-4 py-2.5 text-sm text-muted-foreground">{empty}</li>
        ) : (
          children
        )}
      </ul>
      {note ? <p className="stamp mt-2">{note}</p> : null}
    </div>
  );
}
