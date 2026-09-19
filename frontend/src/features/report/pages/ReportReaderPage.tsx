/**
 * A submitted weekly report, read back (REP-02..05, UI-04).
 *
 * This is the screen the product did not have. `docs/use_cases.md` §2.5 said it outright — "a
 * professor cannot read the text of a submitted report anywhere in the app" — and the student's
 * side was no better: the editor renders the autosaved draft, so the week you sent and the week
 * you are editing were never distinguishable, and earlier versions were unreachable by anyone.
 *
 * It is a separate page rather than a read-only mode on `ReportEditorPage`, for two reasons. The
 * editor is a seeded mutable state machine — draft state, autosave, idempotent submit — and a
 * professor rendering it would mount autosave against an endpoint that answers 422. More
 * decisively, the editor's tabs come from `obligations.filter(required)`, so an entry for a
 * project the student has left can never appear in it; those entries are carried into every new
 * version by `submit_report` and are on no other screen. This page iterates `version.entries`,
 * which is what makes them readable at all.
 *
 * It never renders `draft_content`, though `ReportOut` carries it and a professor is permitted to
 * read it. An unsubmitted draft is not a submission, and showing it would turn autosave into
 * surveillance.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Badge } from "@/components/evidence/Badges";
import { Failure } from "@/components/Failure";
import { useSession } from "@/features/auth/queries";
import { useTimezone } from "@/features/calendar/queries";
import { useUser } from "@/features/people/queries";
import { AttachmentList } from "@/features/report/components/AttachmentList";
import { EntryReadOnly } from "@/features/report/components/EntryReadOnly";
import { RevisionRequestForm } from "@/features/report/components/RevisionRequestForm";
import {
  useMarkReviewed,
  useObligations,
  usePeriods,
  useProjects,
  useReport,
  useReportVersions,
  useRevisionRequests,
  useVersion,
} from "@/features/report/queries";
import { formatInstant, formatLocalDate } from "@/lib/dates";

export function ReportReaderPage() {
  const { t } = useTranslation();
  const { periodId = "", studentId: fromRoute } = useParams<{
    periodId: string;
    studentId?: string;
  }>();
  const session = useSession();
  // The professor's route names the student; the student's route means themselves.
  const studentId = fromRoute ?? session.data?.id;
  const canReview = session.data?.role === "prof";
  const timezone = useTimezone();

  const periods = usePeriods();
  const projects = useProjects();
  const student = useUser(canReview ? studentId : undefined);
  const report = useReport(periodId, fromRoute);
  const versions = useReportVersions(report.data?.id);
  const revisions = useRevisionRequests(report.data?.id);
  const obligations = useObligations(periodId, fromRoute);

  const [selected, setSelected] = useState<string | null>(null);
  const shownVersionId = selected ?? report.data?.current_version_id ?? null;
  const version = useVersion(shownVersionId);

  const period = periods.data?.find((one) => one.id === periodId);
  const titleOf = (projectId: string) =>
    projects.data?.items.find((one) => one.id === projectId)?.title ?? projectId.slice(0, 8);

  if (report.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (report.isError)
    return (
      <p className="text-sm text-muted-foreground">
        <Failure error={report.error} />
      </p>
    );
  // Three distinct states, deliberately not collapsed: no report row at all, a report with no
  // submitted version, and a submitted week. Only the third has anything to read.
  if (report.data === null)
    return <p className="text-sm text-muted-foreground">{t("report.reader.notStarted")}</p>;
  if (!report.data.current_version_id)
    return <p className="text-sm text-muted-foreground">{t("report.reader.notSubmitted")}</p>;

  const required = new Set(
    (obligations.data ?? [])
      .filter((obligation) => obligation.state === "required")
      .map((obligation) => String(obligation.project_id)),
  );
  const open = (revisions.data ?? []).filter((request) => !request.resolved_in_version_id);

  return (
    <section className="max-w-3xl animate-rise-in">
      <header className="border-b border-border pb-5">
        <p className="eyebrow mb-1.5">
          {period
            ? `${formatLocalDate(period.local_start)} – ${formatLocalDate(period.local_end)}`
            : t("report.reader.title")}
        </p>
        <h1 className="page-title">
          {canReview
            ? (student.data?.display_name ?? t("report.reader.title"))
            : t("report.reader.yourWeek")}
        </h1>
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <Badge tone={report.data.workflow_state === "reviewed" ? "good" : "neutral"}>
            {t(`report.state.${report.data.workflow_state}`, {
              defaultValue: report.data.workflow_state,
            })}
          </Badge>
          {version.data ? (
            <Badge tone={version.data.timing_status === "on_time" ? "good" : "warn"}>
              {t(`report.reader.timing.${version.data.timing_status}`, {
                defaultValue: version.data.timing_status,
              })}
            </Badge>
          ) : null}
          {version.data ? (
            <span className="stamp" data-testid="submitted-at">
              {t("report.reader.submittedAt", {
                when: formatInstant(version.data.submitted_at, timezone),
              })}
            </span>
          ) : null}
        </div>
        {/* The one link back, and only while the week is still the student's to edit. */}
        {!canReview ? (
          <Link to={`/report/${periodId}`} className="link mt-3 inline-block text-[13px]">
            {t("report.reader.toEditor")}
          </Link>
        ) : null}
      </header>

      {/* Rendered even at one version, so "there is one version" reads as a fact rather than as a
          feature that is missing. */}
      <h2 className="section-title mt-7">{t("report.reader.versions")}</h2>
      <ul className="mt-2.5 flex flex-wrap gap-1.5" data-testid="versions">
        {(versions.data ?? []).map((one) => {
          const current = one.id === shownVersionId;
          return (
            <li key={one.id}>
              <button
                type="button"
                onClick={() => setSelected(one.id)}
                aria-current={current ? "true" : undefined}
                className={
                  current
                    ? "rounded border border-foreground bg-muted px-3 py-1.5 text-[12.5px]"
                    : "rounded border border-border bg-surface px-3 py-1.5 text-[12.5px] text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
                }
              >
                {t("report.reader.version", { n: one.version_no })}
                <span className="ml-2 font-mono text-[11px]">
                  {formatInstant(one.submitted_at, timezone)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {version.isPending ? <p className="stamp mt-5">{t("common.loading")}</p> : null}

      <div className="mt-6 grid gap-6">
        {(version.data?.entries ?? []).map((entry) => {
          const projectId = String(entry.project_id);
          const departed = required.size > 0 && !required.has(projectId);
          return (
            <article key={entry.id} className="panel p-5" data-testid={`entry-${projectId}`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="section-title">{titleOf(projectId)}</h3>
                {/* This is the only screen in the product where such an entry can appear at all:
                    it is carried forward into every version, and the editor's tabs come from the
                    obligations, which a departed project is no longer in. */}
                {departed ? (
                  <Badge tone="warn" data-testid="departed">
                    {t("report.reader.departedProject")}
                  </Badge>
                ) : null}
              </div>
              <EntryReadOnly entry={entry} />
              <AttachmentList
                periodId={periodId}
                projectId={projectId}
                studentId={studentId}
                className="mt-5"
              />
              {open
                .filter((request) => String(request.project_id) === projectId)
                .map((request) => (
                  <p
                    key={request.id}
                    className="mt-4 border-t border-border pt-3.5 text-[13px] text-warn"
                    data-testid="revision-reason"
                  >
                    {t("report.reader.revisionAsked", {
                      when: formatInstant(request.created_at, timezone),
                    })}{" "}
                    {request.reason}
                  </p>
                ))}
              {canReview && report.data ? (
                <RevisionRequestForm
                  reportId={report.data.id}
                  projectId={projectId}
                  periodId={periodId}
                  studentId={fromRoute}
                />
              ) : null}
            </article>
          );
        })}
      </div>

      {canReview && report.data ? (
        <MarkReviewed
          reportId={report.data.id}
          periodId={periodId}
          studentId={fromRoute}
          reviewed={report.data.workflow_state === "reviewed"}
        />
      ) : null}
    </section>
  );
}

function MarkReviewed({
  reportId,
  periodId,
  studentId,
  reviewed,
}: {
  reportId: string;
  periodId: string;
  studentId?: string;
  reviewed: boolean;
}) {
  const { t } = useTranslation();
  const mark = useMarkReviewed(reportId, { periodId, studentId });

  return (
    <div className="mt-7 flex flex-wrap items-center gap-4 border-t border-border pt-5">
      <button
        type="button"
        disabled={mark.isPending || reviewed}
        onClick={() => mark.mutate()}
        className="btn-ghost"
        data-testid="mark-reviewed"
      >
        {t(reviewed ? "report.reader.reviewed" : "report.reader.markReviewed")}
      </button>
      <Failure error={mark.error} />
    </div>
  );
}
