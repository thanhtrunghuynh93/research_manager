/**
 * Every weekly report handed in, week by week (UI-01, UI-04, REP-05).
 *
 * The overview is this week; this is every week. A professor looking for last month's report from
 * one student had to go through that student's profile, one week at a time. Drafts are not here:
 * the API never lists them, because a draft is the student's working copy and not yet the record.
 *
 * The filters live in the address bar, so a view — "everything still waiting on me", "Bao's weeks
 * on the retrieval project" — can be bookmarked and sent.
 *
 * A student reaches the same page and sees only their own reports, because the API scopes the list.
 * What changes is what would be noise or a dead end for them: no name on every row, no student
 * filter (the roll is the professor's), no "needs review", and links to their own reader and
 * assessment pages rather than the professor's.
 */
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { Badge } from "@/components/evidence/Badges";
import { Failure } from "@/components/Failure";
import { ReportStateBadge } from "@/components/ReportStateBadge";
import { useSession } from "@/features/auth/queries";
import { useTimezone } from "@/features/calendar/queries";
import { usePeople } from "@/features/people/queries";
import { usePeriods, useProjects } from "@/features/report/queries";
import { useReportPages } from "@/features/reports/queries";
import { LISTED_STATES, type ReportFilters, type ReportListItem } from "@/features/reports/types";
import { formatInstant, formatLocalDate, todayLocal } from "@/lib/dates";

/** URL parameter names: short, because they are what a bookmarked view reads as. */
const PARAMS = {
  periodId: "week",
  studentId: "student",
  projectId: "project",
  state: "state",
  needsReview: "review",
} as const;

export function ReportsPage() {
  const { t } = useTranslation();
  const session = useSession();
  const isStudent = session.data?.role === "student";
  const [search, setSearch] = useSearchParams();
  const filters: ReportFilters = {
    periodId: search.get(PARAMS.periodId) ?? undefined,
    // A student's list is already only theirs; a stale bookmark must not narrow it to nothing.
    studentId: isStudent ? undefined : (search.get(PARAMS.studentId) ?? undefined),
    projectId: search.get(PARAMS.projectId) ?? undefined,
    state: search.get(PARAMS.state) ?? undefined,
    needsReview: !isStudent && search.get(PARAMS.needsReview) === "1",
  };
  const filtered = Object.values(filters).some(Boolean);
  const reports = useReportPages(filters);

  const update = (key: keyof typeof PARAMS, value: string) => {
    const next = new URLSearchParams(search);
    if (value) next.set(PARAMS[key], value);
    else next.delete(PARAMS[key]);
    // Replaced, not pushed: each change of a select is not a page the back button should visit.
    setSearch(next, { replace: true });
  };

  const items = reports.data?.items ?? [];

  return (
    <section className="animate-rise-in">
      <header className="border-b border-border pb-5">
        <p className="eyebrow mb-1.5">{t("reports.eyebrow")}</p>
        <h1 className="page-title">{t("reports.title")}</h1>
        <p className="mt-2 max-w-2xl text-prose text-muted-foreground">
          {isStudent ? t("reports.introStudent") : t("reports.intro")}
        </p>
      </header>

      <FilterBar
        isStudent={isStudent}
        filters={filters}
        onChange={update}
        onClear={filtered ? () => setSearch(new URLSearchParams(), { replace: true }) : undefined}
      />

      {reports.isPending ? <p className="stamp mt-4">{t("common.loading")}</p> : null}
      {reports.isError ? (
        <p className="mt-4">
          <Failure error={reports.error} />
        </p>
      ) : null}

      {reports.data && items.length === 0 ? (
        <p className="mt-6 text-sm text-muted-foreground" data-testid="reports-empty">
          {filtered
            ? t("reports.noMatch")
            : isStudent
              ? t("reports.noneYetStudent")
              : t("reports.noneYet")}
        </p>
      ) : null}

      {groupByWeek(items).map((week) => (
        <section key={week.periodId} className="mt-8" data-testid="report-week">
          <h2 className="section-title">
            {formatLocalDate(week.localStart)} – {formatLocalDate(week.localEnd)}
          </h2>
          <ul className="panel mt-2.5">
            {week.rows.map((row) => (
              <ReportRow key={row.report_id} row={row} isStudent={isStudent} />
            ))}
          </ul>
        </section>
      ))}

      {reports.hasNextPage ? (
        <button
          type="button"
          onClick={() => void reports.fetchNextPage()}
          disabled={reports.isFetchingNextPage}
          className="btn-ghost mt-6"
        >
          {reports.isFetchingNextPage ? t("common.loading") : t("reports.loadMore")}
        </button>
      ) : null}
    </section>
  );
}

type Week = { periodId: string; localStart: string; localEnd: string; rows: ReportListItem[] };

/** The API already sorts by week, so a week's rows are consecutive, across pages as well. */
function groupByWeek(items: ReportListItem[]): Week[] {
  const weeks: Week[] = [];
  for (const row of items) {
    const last = weeks[weeks.length - 1];
    if (last?.periodId === row.period_id) last.rows.push(row);
    else
      weeks.push({
        periodId: row.period_id,
        localStart: row.local_start,
        localEnd: row.local_end,
        rows: [row],
      });
  }
  return weeks;
}

function ReportRow({ row, isStudent }: { row: ReportListItem; isStudent: boolean }) {
  const { t } = useTranslation();
  const timezone = useTimezone();
  const projects = row.projects ?? [];

  return (
    <li className="row items-start" data-testid="report-row">
      <div className="min-w-0 flex-1 basis-60">
        {isStudent ? null : (
          <Link to={`/students/${row.student_id}`} className="link font-medium">
            {row.student_name}
          </Link>
        )}
        <ul className={`${isStudent ? "" : "mt-1 "}flex flex-wrap items-center gap-x-3 gap-y-1.5`}>
          {projects.map((project) => (
            <li key={project.project_id} className="flex items-center gap-1.5 text-ui">
              <span className="text-muted-foreground">{project.title}</span>
              {/* One per project: an assessment is of one student, project and week. */}
              {project.assessment ? (
                <Link
                  to={
                    isStudent
                      ? `/me/assessments/${project.assessment.assessment_id}`
                      : `/review/${project.assessment.assessment_id}`
                  }
                  className="no-underline hover:no-underline"
                  data-testid="assessment-link"
                >
                  <Badge tone={project.assessment.status === "approved" ? "good" : "neutral"}>
                    {t("reports.assessment", {
                      state: t(`review.state.${project.assessment.status}`, {
                        defaultValue: project.assessment.status,
                      }),
                    })}
                  </Badge>
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="stamp">
          {t("reports.submitted", { when: formatInstant(row.first_submitted_at, timezone) })}
        </span>
        {row.late ? (
          <Badge tone="warn" data-testid="late-chip">
            {t("reports.late")}
          </Badge>
        ) : null}
        {row.version_count > 1 ? (
          <span
            className="stamp"
            title={t("reports.latest", { when: formatInstant(row.last_submitted_at, timezone) })}
          >
            {t("reports.versions", { count: row.version_count })}
          </span>
        ) : null}
        <ReportStateBadge state={row.workflow_state} />
        <Link
          to={
            isStudent
              ? `/report/${row.period_id}/submitted`
              : `/students/${row.student_id}/reports/${row.period_id}`
          }
          className="btn-quiet"
          data-testid="open-report"
        >
          {t("reports.read")}
        </Link>
      </div>
    </li>
  );
}

function FilterBar({
  isStudent,
  filters,
  onChange,
  onClear,
}: {
  isStudent: boolean;
  filters: ReportFilters;
  onChange: (key: keyof typeof PARAMS, value: string) => void;
  onClear?: () => void;
}) {
  const { t } = useTranslation();
  const timezone = useTimezone();
  const periods = usePeriods();
  const projects = useProjects();

  // Weeks that have begun: the calendar opens weeks ahead, and none of those can hold a report.
  const today = todayLocal(new Date(), timezone);
  const weeks = (periods.data ?? [])
    .filter((period) => period.local_start <= today)
    .sort((a, b) => b.local_start.localeCompare(a.local_start));

  return (
    <div className="mt-6 flex flex-wrap items-end gap-4" data-testid="report-filters">
      <label className="block">
        <span className="field-label">{t("reports.filter.week")}</span>
        <select
          aria-label={t("reports.filter.week")}
          value={filters.periodId ?? ""}
          onChange={(event) => onChange("periodId", event.target.value)}
          className="select mt-1 max-w-full"
        >
          <option value="">{t("reports.filter.allWeeks")}</option>
          {weeks.map((period) => (
            <option key={period.id} value={period.id}>
              {formatLocalDate(period.local_start)} – {formatLocalDate(period.local_end)}
            </option>
          ))}
        </select>
      </label>
      {isStudent ? null : (
        <StudentFilter value={filters.studentId} onChange={(id) => onChange("studentId", id)} />
      )}
      <label className="block">
        <span className="field-label">{t("reports.filter.project")}</span>
        <select
          aria-label={t("reports.filter.project")}
          value={filters.projectId ?? ""}
          onChange={(event) => onChange("projectId", event.target.value)}
          className="select mt-1 max-w-full"
        >
          <option value="">{t("reports.filter.allProjects")}</option>
          {(projects.data?.items ?? []).map((project) => (
            <option key={project.id} value={project.id}>
              {project.title}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className="field-label">{t("reports.filter.state")}</span>
        <select
          aria-label={t("reports.filter.state")}
          value={filters.state ?? ""}
          onChange={(event) => onChange("state", event.target.value)}
          className="select mt-1 max-w-full"
        >
          <option value="">{t("reports.filter.allStates")}</option>
          {LISTED_STATES.map((state) => (
            <option key={state} value={state}>
              {t(`report.state.${state}`)}
            </option>
          ))}
        </select>
      </label>
      {isStudent ? null : (
        <label className="flex items-center gap-2 pb-1 text-sm">
          <input
            type="checkbox"
            checked={Boolean(filters.needsReview)}
            onChange={(event) => onChange("needsReview", event.target.checked ? "1" : "")}
          />
          {t("reports.filter.needsReview")}
        </label>
      )}
      {onClear ? (
        <button type="button" onClick={onClear} className="btn-quiet pb-1.5">
          {t("reports.filter.clear")}
        </button>
      ) : null}
    </div>
  );
}

/** Its own component so the roll is only asked for where it is shown: it is the professor's. */
function StudentFilter({
  value,
  onChange,
}: {
  value: string | undefined;
  onChange: (id: string) => void;
}) {
  const { t } = useTranslation();
  const people = usePeople();
  const students = (people.data?.users ?? []).filter((user) => user.role === "student");

  return (
    <label className="block">
      <span className="field-label">{t("reports.filter.student")}</span>
      <select
        aria-label={t("reports.filter.student")}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
        className="select mt-1 max-w-full"
      >
        <option value="">{t("reports.filter.allStudents")}</option>
        {students.map((user) => (
          <option key={user.id} value={user.id}>
            {user.display_name}
          </option>
        ))}
      </select>
    </label>
  );
}
