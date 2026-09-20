/**
 * UI-02/UI-04: how the student is doing, over time and across projects.
 *
 * `architecture.md` §4.2 has named this screen — "permitted subset at `/me/profile`" — since the
 * route table was written, and it was never built. It is the counterpart to `/students/:id`: the
 * same trajectory and the same released assessments, restricted by the same policy, for the person
 * they are about.
 *
 * `/me` answers *what happened this week*. This answers *how am I doing*, and neither can carry the
 * other without becoming the professor's screen.
 */
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ConfidenceBadge, ConfidenceReasons, ProgressIndex } from "@/components/evidence/Badges";
import { Trajectory } from "@/features/assessments/components/Trajectory";
import { useAssessments } from "@/features/assessments/queries";
import { useSession } from "@/features/auth/queries";
import { useProjects } from "@/features/report/queries";
import { useTimezone } from "@/features/calendar/queries";
import { formatInstant } from "@/lib/dates";

export function MyProfilePage() {
  const { t } = useTranslation();
  const session = useSession();
  const timezone = useTimezone();
  const me = session.data?.id;
  const assessments = useAssessments({ studentId: me });
  const projects = useProjects();

  if (session.isPending || assessments.isPending)
    return <p className="stamp">{t("common.loading")}</p>;

  const released = assessments.data ?? [];
  const titleOf = (projectId: string) =>
    projects.data?.items.find((project) => project.id === projectId)?.title;

  // One trajectory per project the student has been assessed on. Ordered by first appearance so
  // the page is stable between renders.
  const projectIds = [...new Set(released.map((one) => String(one.project_id)))];

  return (
    <section className="max-w-2xl animate-rise-in">
      <header className="border-b border-border pb-5">
        <h1 className="page-title">{t("myProfile.title")}</h1>
      </header>

      {projectIds.map((projectId) => (
        <Trajectory
          key={projectId}
          studentId={me!}
          projectId={projectId}
          title={titleOf(projectId)}
        />
      ))}

      <h2 className="section-title mt-8 mb-2.5">{t("student.assessments")}</h2>
      <ul className="panel" data-testid="my-assessments">
        {released.map((one) => (
          <li key={one.id} className="row">
            <Link to={`/me/assessments/${one.id}`} className="link text-ui">
              {titleOf(String(one.project_id)) ?? String(one.project_id).slice(0, 8)}
            </Link>
            <span className="flex items-center gap-2.5 text-right">
              <ProgressIndex value={one.progress_index} />
              <ConfidenceBadge
                confidence={one.confidence}
                reasons={(one.confidence_reasons ?? []).map(String)}
              />
              <span className="font-mono text-meta text-muted-foreground">
                {one.published_at ? formatInstant(one.published_at, timezone) : ""}
              </span>
            </span>
            {/* The row wraps, so this takes its own line rather than crowding the badge. It used
                to be the badge's tooltip: unreachable by touch or keyboard, and "· 2" said
                nothing about what the two were. */}
            <ConfidenceReasons
              reasons={(one.confidence_reasons ?? []).map(String)}
              className="w-full"
            />
          </li>
        ))}
        {released.length === 0 && (
          <li className="px-4 py-2.5 text-sm text-muted-foreground">
            {t("student.noAssessments")}
          </li>
        )}
      </ul>
      {/* The empty state's explanation, not a permanent footnote: under a list of assessments it
          told the reader an assessment would appear once one had. */}
      {released.length === 0 ? <p className="stamp mt-2">{t("me.releasedNote")}</p> : null}
    </section>
  );
}
