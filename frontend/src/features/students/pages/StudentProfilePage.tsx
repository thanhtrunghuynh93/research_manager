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
    <section className="space-y-8">
      <header>
        <h1 className="text-xl font-semibold">{t("student.title")}</h1>
        <p className="text-sm text-muted-foreground">{id?.slice(0, 8)}</p>
      </header>

      {projectIds.map((projectId) => (
        <Trajectory key={projectId} studentId={id!} projectId={projectId} />
      ))}

      <div className="space-y-2">
        <h2 className="text-sm font-medium">{t("student.assessments")}</h2>
        <ul
          className="divide-y divide-border rounded-lg border border-border"
          data-testid="assessments"
        >
          {assessments.data?.map((assessment) => (
            <li
              key={assessment.id}
              className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm"
            >
              <Link to={`/review/${assessment.id}`} className="underline">
                {t("student.week", { period: assessment.period_id.slice(0, 8) })}
              </Link>
              <span className="flex items-center gap-2">
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
            <li className="px-4 py-2 text-sm text-muted-foreground">
              {t("student.noAssessments")}
            </li>
          )}
        </ul>
      </div>
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
    <div className="space-y-2">
      <h2 className="text-sm font-medium">
        {t("student.trajectory", { project: projectId.slice(0, 8) })}
      </h2>
      {rubricVersions.size > 1 && (
        <p className="text-xs text-amber-700 dark:text-amber-300" data-testid="rubric-break">
          {t("student.rubricBreak", { count: rubricVersions.size })}
        </p>
      )}
      <ol className="flex flex-wrap gap-2" data-testid="trajectory">
        {points.map((point) => (
          <li key={point.assessment_id} className="rounded-md border border-border px-3 py-2">
            <ProgressIndex value={point.progress_index} />
            <p className="text-xs text-muted-foreground">{formatInstant(point.created_at)}</p>
            <p className="text-xs text-muted-foreground">
              {t("student.rubric", { id: (point.rubric_version_id ?? "").slice(0, 8) })}
            </p>
          </li>
        ))}
        {points.length === 0 && (
          <li className="text-sm text-muted-foreground">{t("student.noApproved")}</li>
        )}
      </ol>
    </div>
  );
}
