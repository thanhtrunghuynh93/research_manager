/**
 * ASSESS-10 / AC-10: a student's approved points on one project, each labelled with the rubric
 * that produced it.
 *
 * Lifted out of the professor's profile screen so the student can be shown the same thing. The
 * rubric break matters as much to the person being assessed as to the person assessing: a change
 * of rubric is a change of the measure, and a trend read across one is not a trend.
 */
import { useTranslation } from "react-i18next";

import { ProgressIndex } from "@/components/evidence/Badges";
import { useTrend } from "@/features/assessments/queries";
import { useTimezone } from "@/features/calendar/queries";
import { formatInstant } from "@/lib/dates";

export function Trajectory({
  studentId,
  projectId,
  title,
}: {
  studentId: string;
  projectId: string;
  title?: string;
}) {
  const { t } = useTranslation();
  const trend = useTrend(studentId, projectId);
  const timezone = useTimezone();

  const points = trend.data ?? [];
  const rubricVersions = new Set(points.map((point) => point.rubric_version_id));
  // Rubrics are named by their order of appearance in this series — A, then B — rather than by
  // eight characters of their UUID. The label exists so a reader can see which points share a
  // measure, and a hex fragment answers that only for someone willing to compare hex fragments.
  const rubricLabels = new Map(
    [...rubricVersions].map((id, index) => [id, String.fromCharCode(65 + index)]),
  );

  return (
    <div className="mt-8">
      <h2 className="section-title">
        {t("student.trajectory", { project: title ?? projectId.slice(0, 8) })}
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
              <p className="stamp mt-2">{formatInstant(point.created_at, timezone)}</p>
              <p className="stamp">
                {t("student.rubric", {
                  label: rubricLabels.get(point.rubric_version_id) ?? "?",
                })}
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
