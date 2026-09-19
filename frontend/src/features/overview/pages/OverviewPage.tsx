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
import { Failure } from "@/components/Failure";
import { useEnsureObligations, useOverview } from "@/features/overview/queries";
import type { WeekStudent, WeekWorkspace } from "@/features/overview/types";
import { useTimezone } from "@/features/calendar/queries";
import { formatInstant, formatLocalDate } from "@/lib/dates";

export function OverviewPage() {
  const { t } = useTranslation();
  const overview = useOverview();
  const timezone = useTimezone();

  if (overview.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (overview.isError)
    return <p className="text-sm text-muted-foreground">{t("overview.unavailable")}</p>;

  const raw = overview.data;
  const data = {
    ...raw,
    outstanding: { ...raw.outstanding, entries: raw.outstanding.entries ?? [] },
    week: raw.week ?? [],
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

      <WeekBoard week={data.week} timezone={timezone} />

      <div className="mt-8 grid gap-6 [grid-template-columns:repeat(auto-fit,minmax(320px,1fr))]">
        <Section
          title={t("overview.outstanding")}
          empty={t("overview.nothingOutstanding")}
          count={data.outstanding.count}
          testId="outstanding"
          note={`${data.outstanding.note} ${t("overview.asOf", {
            when: formatInstant(data.outstanding.as_of, timezone),
          })}`}
        >
          <li className="row">
            <DeriveObligations periodId={data.current_period?.period_id} />
          </li>
          {data.outstanding.entries.map((entry, index) => (
            <li
              key={`${String(entry.student_id)}:${String(entry.project_id)}:${index}`}
              className="row"
            >
              <Link to={`/students/${String(entry.student_id)}`} className="text-[13px]">
                {String(entry.student_name || "") || String(entry.student_id).slice(0, 8)}
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
  testId,
  children,
}: {
  title: string;
  empty: string;
  count: number;
  note?: string;
  testId?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h2 className="flex items-baseline gap-2.5">
        <span className="section-title">{title}</span>
        <span className={count === 0 ? "chip chip-neutral" : "chip chip-warn"}>{count}</span>
      </h2>
      <ul className="panel mt-2.5" data-testid={testId}>
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

/**
 * The last link in the chain that makes a report due: a membership on an active project produces
 * an obligation only once they are derived for the period. The nightly job does it too, so this
 * button exists to not wait a day while a workspace is being set up.
 */
function DeriveObligations({ periodId }: { periodId?: string }) {
  const { t } = useTranslation();
  const ensure = useEnsureObligations();
  if (!periodId) return null;

  return (
    <span className="flex w-full flex-wrap items-center justify-between gap-3">
      <button
        type="button"
        disabled={ensure.isPending}
        onClick={() => ensure.mutate(periodId)}
        className="btn-ghost"
        data-testid="derive-obligations"
      >
        {t("overview.deriveObligations")}
      </button>
      <span className="stamp">{t("overview.deriveNote")}</span>
      <Failure error={ensure.error} />
    </span>
  );
}

/**
 * The week itself: every report owed, by workspace, project and student (UI-01).
 *
 * `Outstanding` beside it is the same obligations read for one of their three states, and a list
 * of absences is not something a supervisor can plan from — a student who has reported does not
 * appear in it at all, and neither does a project where everyone has. This is the whole week,
 * which is also why the rows carry names rather than the eight characters of a uuid that the
 * outstanding list still shows.
 *
 * Grouped by workspace because a professor's reads span every workspace they belong to (ADR 0016)
 * and each keeps its own calendar, so the weeks do not line up and must not be run together.
 */
function WeekBoard({ week, timezone }: { week: WeekWorkspace[]; timezone: string }) {
  const { t } = useTranslation();

  return (
    <section className="mt-8" data-testid="week-board">
      <h2 className="flex items-baseline gap-2.5">
        <span className="section-title">{t("overview.week")}</span>
        {week.length > 0 ? (
          <span className="chip chip-neutral">
            {t("overview.weekCount", {
              submitted: week.reduce((total, one) => total + one.submitted, 0),
              total: week.reduce((total, one) => total + one.submitted + one.owed + one.excused, 0),
            })}
          </span>
        ) : null}
      </h2>

      {week.length === 0 ? (
        <p className="panel mt-2.5 px-4 py-2.5 text-sm text-muted-foreground">
          {t("overview.weekEmpty")}
        </p>
      ) : (
        week.map((workspace) => (
          <div key={workspace.workspace_id} className="mt-3.5">
            {/* Named even when there is one: a professor who joins a second workspace should not
                have to work out which week they are reading. */}
            <p className="eyebrow">
              {workspace.workspace_name} · {formatLocalDate(workspace.local_start)} –{" "}
              {formatLocalDate(workspace.local_end)}
            </p>
            <div className="panel mt-2">
              {(workspace.projects ?? []).map((project) => (
                <div key={project.project_id} className="border-b border-border last:border-b-0">
                  <Link
                    to={`/projects/${project.project_id}`}
                    className="link block px-4 pt-2.5 text-[13.5px] font-medium"
                  >
                    {project.project_title}
                  </Link>
                  <ul className="px-4 pb-2.5">
                    {(project.students ?? []).map((student) => (
                      <li
                        key={student.student_id}
                        className="flex flex-wrap items-baseline justify-between gap-3 py-1"
                      >
                        <Link
                          to={`/students/${student.student_id}`}
                          className="link text-[13px]"
                          data-testid="week-student"
                        >
                          {student.student_name}
                        </Link>
                        <WeekState student={student} timezone={timezone} />
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        ))
      )}
      <p className="stamp mt-2">{t("overview.weekNote")}</p>
    </section>
  );
}

/**
 * The three states a professor acts on differently (REP-06, REP-08), each saying what it means.
 *
 * An excused row carries its reason and an extended one its new deadline, because "owed" and
 * "owed until Thursday" call for different action and the colour alone cannot tell them apart.
 */
function WeekState({ student, timezone }: { student: WeekStudent; timezone: string }) {
  const { t } = useTranslation();

  if (student.state === "excused") {
    return (
      <span className="text-right font-mono text-[11.5px] text-faint">
        {t("report.obligation.excused")}
        {student.excuse_reason ? ` — ${student.excuse_reason}` : ""}
      </span>
    );
  }
  const submitted = student.state === "submitted";
  return (
    <span className="text-right">
      <span
        className={
          submitted
            ? "font-mono text-[11px] uppercase tracking-[0.06em] text-good"
            : "font-mono text-[11px] uppercase tracking-[0.06em] text-warn"
        }
      >
        {t(submitted ? "report.obligation.submitted" : "report.obligation.required")}
      </span>
      {!submitted && student.extension_until_utc ? (
        <span className="ml-2 font-mono text-[11px] text-muted-foreground">
          {t("overview.extendedUntil", {
            when: formatInstant(student.extension_until_utc, timezone),
          })}
        </span>
      ) : null}
    </span>
  );
}
