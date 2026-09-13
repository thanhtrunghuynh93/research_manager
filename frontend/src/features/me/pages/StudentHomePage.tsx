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

  if (periods.isPending) return <p className="text-muted-foreground">{t("common.loading")}</p>;
  if (!period) return <p className="text-muted-foreground">{t("me.noPeriod")}</p>;

  const titleOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.title ?? projectId;

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{t("me.title")}</h1>
        <p className="text-sm text-muted-foreground">
          {formatLocalDate(period.local_start)} – {formatLocalDate(period.local_end)}
        </p>
        <p className="text-sm" data-testid="next-deadline">
          {t("me.dueBy")} {formatInstant(period.deadline_utc)}
        </p>
      </header>

      <div className="flex items-center gap-3">
        <span className="text-sm" data-testid="report-state">
          {t(`report.state.${report.data?.workflow_state ?? "not_started"}`)}
        </span>
        <Link
          to={`/report/${period.id}`}
          className="rounded-md border border-border px-3 py-1.5 text-sm font-medium"
        >
          {report.data ? t("me.openWeek") : t("me.startWeek")}
        </Link>
      </div>

      <div className="space-y-2">
        <h2 className="text-sm font-medium">{t("me.obligations")}</h2>
        <ul className="divide-y divide-border rounded-lg border border-border">
          {obligations.data?.map((obligation) => (
            <li key={obligation.id} className="flex items-center justify-between px-4 py-2 text-sm">
              <span>{titleOf(obligation.project_id)}</span>
              <span className={obligation.state === "excused" ? "text-muted-foreground" : ""}>
                {t(`report.obligation.${obligation.state}`)}
                {obligation.excuse_reason ? ` — ${obligation.excuse_reason}` : ""}
              </span>
            </li>
          ))}
          {obligations.data?.length === 0 && (
            <li className="px-4 py-2 text-sm text-muted-foreground">{t("me.nothingOwed")}</li>
          )}
        </ul>
      </div>
    </section>
  );
}
