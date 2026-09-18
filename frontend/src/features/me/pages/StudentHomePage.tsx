import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import {
  currentPeriod,
  useObligations,
  usePeriods,
  useProjects,
  useReport,
} from "@/features/report/queries";
import { formatInstant, formatLocalDate, todayLocal } from "@/lib/dates";

/** UI-02: what is owed this week, when it is due, and one way into the weekly flow. */
export function StudentHomePage() {
  const { t } = useTranslation();
  const periods = usePeriods();
  const period = currentPeriod(periods.data);
  const obligations = useObligations(period?.id);
  const projects = useProjects();
  const report = useReport(period?.id);

  if (periods.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (!period) return <p className="text-sm text-muted-foreground">{t("me.noPeriod")}</p>;

  const titleOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.title ?? projectId;

  return (
    <section className="max-w-2xl animate-rise-in">
      <header>
        <p className="eyebrow mb-1.5">
          {formatLocalDate(period.local_start)} – {formatLocalDate(period.local_end)}
        </p>
        <h1 className="page-title">{t("me.title")}</h1>
      </header>

      {/* The deadline is the point of this screen, so it is set as a figure rather than a caption. */}
      <div className="panel mt-6 flex flex-wrap items-center justify-between gap-5 p-5">
        <div>
          <p className="eyebrow">{t("me.dueBy")}</p>
          <p
            className="mt-1.5 font-display text-[1.625rem] leading-none"
            data-testid="next-deadline"
          >
            {formatInstant(period.deadline_utc)}
          </p>
          <p className="mt-2 font-mono text-xs text-muted-foreground" data-testid="report-state">
            {t(`report.state.${report.data?.workflow_state ?? "not_started"}`)}
          </p>
        </div>
        <Link to={`/report/${period.id}`} className="btn-primary no-underline">
          {report.data ? t("me.openWeek") : t("me.startWeek")}
        </Link>
      </div>

      <h2 className="section-title mt-8">{t("me.obligations")}</h2>
      <ul className="panel mt-2.5">
        {obligations.data?.map((obligation) => (
          <li key={obligation.id} className="row">
            {/* The student's own way into UI-03: the project page is signed-in, not prof-only. */}
            <Link to={`/projects/${obligation.project_id}`} className="link">
              {titleOf(obligation.project_id)}
            </Link>
            <span
              className={
                obligation.state === "excused"
                  ? "font-mono text-[11.5px] text-faint"
                  : "font-mono text-[11px] uppercase tracking-[0.06em] text-warn"
              }
            >
              {t(`report.obligation.${obligation.state}`)}
              {obligation.excuse_reason ? ` — ${obligation.excuse_reason}` : ""}
            </span>
          </li>
        ))}
        {obligations.data?.length === 0 && (
          <li className="px-4 py-2.5 text-sm text-muted-foreground">{t("me.nothingOwed")}</li>
        )}
      </ul>

      {/* The only way into the released record since this screen stopped carrying it, and the
          only inbound link to /me/profile anywhere in the app. */}
      <p className="stamp mt-3">
        <Link to="/me/profile" className="link" data-testid="to-my-progress">
          {t("me.toProfile")}
        </Link>
      </p>

      <PastWeeks currentPeriodId={period.id} />
    </section>
  );
}

/**
 * Every week before this one. `usePeriods` is already loaded for the header, so the history costs
 * no request — and without it the student could only ever see the week they are in.
 */
function PastWeeks({ currentPeriodId }: { currentPeriodId: string }) {
  const { t } = useTranslation();
  const periods = usePeriods();
  const today = todayLocal();

  const past = (periods.data ?? [])
    .filter((one) => one.id !== currentPeriodId && one.local_end < today)
    .sort((a, b) => b.local_start.localeCompare(a.local_start))
    .slice(0, 8);

  if (!past.length) return null;

  return (
    <>
      <h2 className="section-title mt-8">{t("me.pastWeeks")}</h2>
      <ul className="panel mt-2.5" data-testid="past-weeks">
        {past.map((one) => (
          <li key={one.id} className="row">
            <Link to={`/report/${one.id}`} className="link">
              {formatLocalDate(one.local_start)} – {formatLocalDate(one.local_end)}
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
