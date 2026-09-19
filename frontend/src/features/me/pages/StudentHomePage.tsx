import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import {
  currentPeriod,
  useObligations,
  usePeriods,
  useProjects,
  useReport,
} from "@/features/report/queries";
import type { Obligation } from "@/features/report/types";
import { useTimezone } from "@/features/calendar/queries";
import { formatInstant, formatLocalDate, todayLocal } from "@/lib/dates";

/** UI-02: what is owed this week, when it is due, and one way into the weekly flow. */
export function StudentHomePage() {
  const { t } = useTranslation();
  const timezone = useTimezone();
  const periods = usePeriods();
  const period = currentPeriod(periods.data, new Date(), timezone);
  const obligations = useObligations(period?.id);
  const projects = useProjects();
  const report = useReport(period?.id);

  if (periods.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (!period) return <p className="text-sm text-muted-foreground">{t("me.noPeriod")}</p>;

  const titleOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.title ?? projectId;

  // The headline state is about the *package*, not about the report row. "Submitted" says only
  // that something was handed in, so a week submitted on Monday still read "Submitted" after
  // Wednesday's new project added an entry nobody has written — and gave the student no reason to
  // reopen the week. REP-08 calls that obligation unfulfilled, and so does this screen now.
  //
  // Only over the two states that mean "something is in". A draft with nothing submitted is a
  // draft, and "Revision requested" is the professor waiting on something specific, which a count
  // of projects would bury.
  const owed = (obligations.data ?? []).filter(
    (obligation) => obligation.state === "required" && !obligation.submitted,
  ).length;
  const workflowState = report.data?.workflow_state ?? "not_started";
  const partly = owed > 0 && (workflowState === "submitted" || workflowState === "resubmitted");
  const state = report.isPending
    ? null
    : partly
      ? t("me.partlySubmitted", { count: owed })
      : t(`report.state.${workflowState}`);

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
            {formatInstant(period.deadline_utc, timezone)}
          </p>
          {/* Held back until the report has answered. Defaulting to `not_started` meant a
              submitted week painted briefly as an untouched one, under a deadline that was
              already correct — so the panel looked settled while it was still wrong. */}
          <p
            className={
              partly
                ? "mt-2 font-mono text-xs text-warn"
                : "mt-2 font-mono text-xs text-muted-foreground"
            }
            data-testid="report-state"
          >
            {/* A non-breaking space, so the panel keeps its height while the state is unknown. */}
            {state ?? <>&nbsp;</>}
          </p>
        </div>
        {/* "Open" while the answer is outstanding: it is true either way, where "Start this
            week" on a week already submitted is not. */}
        <Link to={`/report/${period.id}`} className="btn-primary no-underline">
          {report.isPending || report.data ? t("me.openWeek") : t("me.startWeek")}
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
            <ObligationState obligation={obligation} />
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

      <PastWeeks currentPeriodId={period.id} timezone={timezone} />
    </section>
  );
}

/**
 * Whether this project is still owed, in the three states a student can actually be in.
 *
 * `state` is `required` or `excused` and says whether the project has to be in the package — it
 * never changes on submission, so rendering it alone left a finished week reading REQUIRED in the
 * warning colour however many times it had been submitted. `submitted` (REP-08) is the other half,
 * and it is computed from the report's current version, so this agrees with the professor's
 * outstanding list by construction.
 */
function ObligationState({ obligation }: { obligation: Obligation }) {
  const { t } = useTranslation();
  if (obligation.state === "excused") {
    return (
      <span className="font-mono text-[11.5px] text-faint">
        {t("report.obligation.excused")}
        {obligation.excuse_reason ? ` — ${obligation.excuse_reason}` : ""}
      </span>
    );
  }
  return (
    <span
      className={
        obligation.submitted
          ? "font-mono text-[11px] uppercase tracking-[0.06em] text-good"
          : "font-mono text-[11px] uppercase tracking-[0.06em] text-warn"
      }
    >
      {t(obligation.submitted ? "report.obligation.submitted" : "report.obligation.required")}
    </span>
  );
}

/**
 * Every week before this one. `usePeriods` is already loaded for the header, so the history costs
 * no request — and without it the student could only ever see the week they are in.
 */
function PastWeeks({ currentPeriodId, timezone }: { currentPeriodId: string; timezone: string }) {
  const { t } = useTranslation();
  const periods = usePeriods();
  const today = todayLocal(new Date(), timezone);

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
