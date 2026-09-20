/**
 * UI-04: one student's research profile — projects, weekly trajectory, and assessments.
 *
 * The trajectory is the part that needs care. Points produced under different rubric versions are
 * not one series, so they are grouped by rubric and the break is stated rather than drawn through
 * (AC-10). An assessment with no index shows "Not rated" rather than a gap in a chart, which a
 * reader would otherwise fill in as a zero.
 */
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/client";
import {
  Badge,
  ConfidenceBadge,
  ConfidenceReasons,
  ProgressIndex,
} from "@/components/evidence/Badges";
import { Trajectory } from "@/features/assessments/components/Trajectory";
import { useUser } from "@/features/people/queries";
import type { Assessment } from "@/features/review/types";
import { openArtifact, useArtifacts, useAllPeriods, useProjects } from "@/features/report/queries";
import { formatLocalDate } from "@/lib/dates";

export function StudentProfilePage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();

  const assessments = useQuery({
    queryKey: ["student", id, "assessments"],
    queryFn: () => api.get<Assessment[]>(`/api/v1/assessments?student_id=${id}`),
    enabled: Boolean(id),
  });
  // This page is about a person, and it used to name them — and their projects, and their weeks —
  // with eight characters of a uuid. These being UUIDv7, the eight characters were identical on
  // every row, so three assessments all read "Week 01a0ad80". The ids stay as the fallback, for
  // the record a professor cannot read and the project list that paged past the end.
  const student = useUser(id);
  const projects = useProjects();
  const periods = useAllPeriods();

  const titleOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.title ??
    projectId.slice(0, 8);
  const weekOf = (periodId: string) => {
    const period = periods.data?.find((one) => one.id === periodId);
    return period
      ? `${formatLocalDate(period.local_start)} – ${formatLocalDate(period.local_end)}`
      : t("student.week", { period: periodId.slice(0, 8) });
  };

  const projectIds = Array.from(new Set((assessments.data ?? []).map((row) => row.project_id)));

  return (
    <section className="animate-rise-in">
      <header>
        <p className="eyebrow mb-1.5">{t("student.label")}</p>
        <h1 className="page-title">{student.data?.display_name ?? t("student.title")}</h1>
      </header>

      {projectIds.map((projectId) => (
        <Trajectory
          key={projectId}
          studentId={id!}
          projectId={projectId}
          title={titleOf(projectId)}
        />
      ))}

      {/* Every week this student could have reported, each a click from its text. The reader
          itself says "nothing was started" for a week with nothing in it, so no probing is
          needed here — and a professor with no list had no way into a report at all. */}
      <h2 className="section-title mt-8">{t("report.reader.weekly")}</h2>
      <ul className="panel mt-2.5" data-testid="weekly-reports">
        {(periods.data ?? [])
          .slice()
          .reverse()
          .slice(0, 8)
          .map((period) => (
            <li key={period.id} className="row">
              <Link to={`/students/${id}/reports/${period.id}`} className="link text-[13.5px]">
                {formatLocalDate(period.local_start)} – {formatLocalDate(period.local_end)}
              </Link>
              <span className="font-mono text-[11.5px] text-muted-foreground">
                {t("report.reader.openWeek")}
              </span>
            </li>
          ))}
      </ul>

      <Materials studentId={id!} />

      <h2 className="section-title mt-8">{t("student.assessments")}</h2>
      <ul className="panel mt-2.5" data-testid="assessments">
        {assessments.data?.map((assessment) => (
          <li key={assessment.id} className="row">
            <Link to={`/review/${assessment.id}`} className="text-[13.5px]">
              {weekOf(assessment.period_id)}
              <span className="ml-2 text-muted-foreground">{titleOf(assessment.project_id)}</span>
            </Link>
            <span className="flex flex-wrap items-center gap-2.5">
              <ProgressIndex value={assessment.progress_index} />
              <ConfidenceBadge
                confidence={assessment.confidence}
                reasons={(assessment.confidence_reasons ?? []).map(String)}
              />
              <Badge tone={assessment.review_state === "approved" ? "good" : "neutral"}>
                {t(`review.state.${assessment.review_state ?? "draft"}`, {
                  defaultValue: assessment.review_state ?? "draft",
                })}
              </Badge>
            </span>
            <ConfidenceReasons
              reasons={(assessment.confidence_reasons ?? []).map(String)}
              className="w-full"
            />
          </li>
        ))}
        {assessments.data?.length === 0 && (
          <li className="px-4 py-2.5 text-sm text-muted-foreground">
            {t("student.noAssessments")}
          </li>
        )}
      </ul>
    </section>
  );
}

/**
 * UI-04: what this student actually handed in.
 *
 * The assessments above are about the work; this is the work. A professor reading a week needs the
 * deck or the document itself, not only the sentence someone wrote about it — and until there was
 * a way to list attachments, the only place an artifact id ever appeared was the response to the
 * upload that created it, so there was no route back to the file at all (REP-04, AC-02).
 */
function Materials({ studentId }: { studentId: string }) {
  const { t } = useTranslation();
  const artifacts = useArtifacts({ studentId });

  return (
    <>
      <h2 className="section-title mt-8">{t("student.materials")}</h2>
      <ul className="panel mt-2.5" data-testid="materials">
        {artifacts.data?.map((artifact) => (
          <li key={artifact.artifact_id} className="row items-start">
            <span className="min-w-0">
              <span className="font-mono text-[12.5px]">{artifact.filename}</span>
              {artifact.supported_claim ? (
                <span className="mt-1 block text-[13px] text-muted-foreground">
                  {artifact.supported_claim}
                </span>
              ) : null}
            </span>
            <span className="flex shrink-0 items-center gap-2.5">
              <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-faint">
                {t(`report.attachments.state.${artifact.extraction_state}`, {
                  defaultValue: artifact.extraction_state,
                })}
              </span>
              <button
                type="button"
                onClick={() => void openArtifact(artifact.artifact_id)}
                className="btn-quiet"
              >
                {t("report.attachments.download")}
              </button>
            </span>
          </li>
        ))}
        {artifacts.data?.length === 0 && (
          <li className="px-4 py-2.5 text-sm text-muted-foreground">{t("student.noMaterials")}</li>
        )}
      </ul>
      <p className="stamp mt-2">{t("student.materialsNote")}</p>
    </>
  );
}
