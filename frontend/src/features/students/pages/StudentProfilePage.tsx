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
import { Trajectory } from "@/features/assessments/components/Trajectory";
import type { Assessment } from "@/features/review/types";
import { openArtifact, useArtifacts } from "@/features/report/queries";

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
        <p className="eyebrow mb-1.5">{t("student.label", { id: id?.slice(0, 8) ?? "" })}</p>
        <h1 className="page-title">{t("student.title")}</h1>
      </header>

      {projectIds.map((projectId) => (
        <Trajectory key={projectId} studentId={id!} projectId={projectId} />
      ))}

      <Materials studentId={id!} />

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
