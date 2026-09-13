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
import { Badge, ConfidenceBadge, ProgressIndex } from "@/components/evidence/Badges";
import type { Assessment } from "@/features/review/types";
import { formatInstant } from "@/lib/dates";

type TrendPoint = {
  period_id: string;
  assessment_id: string;
  progress_index: number | null;
  plan_completion: string | null;
  confidence: string;
  rubric_version_id: string | null;
  created_at: string;
};

export function StudentProfilePage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();

  const assessments = useQuery({
    queryKey: ["student", id, "assessments"],
    queryFn: () => api.get<Assessment[]>(`/api/v1/assessments?student_id=${id}`),
    enabled: Boolean(id),
  });

  const projectIds = Array.from(new Set((assessments.data ?? []).map((row) => row.project_id)));

  return (
    <section className="animate-rise-in">
      <header>
        <p className="eyebrow mb-1.5">Student {id?.slice(0, 8)}</p>
        <h1 className="page-title">{t("student.title")}</h1>
      </header>

      {projectIds.map((projectId) => (
        <Trajectory key={projectId} studentId={id!} projectId={projectId} />
      ))}

      <h2 className="section-title mt-8">{t("student.assessments")}</h2>
      <ul className="panel mt-2.5" data-testid="assessments">
        {assessments.data?.map((assessment) => (
          <li key={assessment.id} className="row">
            <Link to={`/review/${assessment.id}`} className="text-[13.5px]">
              {t("student.week", { period: assessment.period_id.slice(0, 8) })}
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

function Trajectory({ studentId, projectId }: { studentId: string; projectId: string }) {
  const { t } = useTranslation();
  const trend = useQuery({
    queryKey: ["trends", studentId, projectId],
    queryFn: () =>
      api.get<TrendPoint[]>(`/api/v1/trends?student_id=${studentId}&project_id=${projectId}`),
  });

  const points = trend.data ?? [];
  const rubricVersions = new Set(points.map((point) => point.rubric_version_id));

  return (
    <div className="mt-8">
      <h2 className="section-title">
        {t("student.trajectory", { project: projectId.slice(0, 8) })}
      </h2>
      {rubricVersions.size > 1 && (
        <p className="mt-1.5 text-[12.5px] text-warn" data-testid="rubric-break">
          {t("student.rubricBreak", { count: rubricVersions.size })}
        </p>
      )}
      {/* Cards, not a line: a line through a rubric change would assert a comparison the data
          does not support. The break is the point, so the cards that follow one carry an edge. */}
      <ol className="mt-3 flex flex-wrap gap-2.5" data-testid="trajectory">
        {points.map((point, index) => {
          const brokenHere =
            index > 0 && points[index - 1]!.rubric_version_id !== point.rubric_version_id;
          return (
            <li
              key={point.assessment_id}
              className={`card min-w-[8.5rem] ${brokenHere ? "border-l-[3px] border-l-warn-rule" : ""}`}
            >
              <ProgressIndex value={point.progress_index} />
              <p className="stamp mt-2">{formatInstant(point.created_at)}</p>
              <p className="stamp">
                {t("student.rubric", { id: (point.rubric_version_id ?? "").slice(0, 8) })}
              </p>
            </li>
          );
        })}
        {points.length === 0 && (
          <li className="text-sm text-muted-foreground">{t("student.noApproved")}</li>
        )}
      </ol>
    </div>
  );
}
