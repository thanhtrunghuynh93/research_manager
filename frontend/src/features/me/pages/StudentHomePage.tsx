import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import {
  currentPeriod,
  useObligations,
  usePeriods,
  useProjects,
  useReport,
} from "@/features/report/queries";
import { formatInstant, formatLocalDate } from "@/lib/dates";

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
            <span>{titleOf(obligation.project_id)}</span>
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
    </section>
  );
}
