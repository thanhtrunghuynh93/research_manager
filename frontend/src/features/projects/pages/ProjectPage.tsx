/**
 * UI-03: the project workspace — goals, members, milestones, and dated decisions.
 *
 * The completion figure here is milestone weights and accepted fractions, never an average of
 * student scores (PROJ-06). Membership history is shown rather than hidden: a project's record
 * includes who worked on it and when, and deleting that would make the supervision history
 * unreadable (PROJ-02).
 */
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Badge } from "@/components/evidence/Badges";
import { useSession } from "@/features/auth/queries";
import {
  AddMemberForm,
  MembershipControls,
  ProjectFieldsForm,
  StatusControls,
} from "@/features/projects/components/ProjectControls";
import {
  useDecisions,
  useMembers,
  useMilestones,
  useProgress,
  useProject,
} from "@/features/projects/queries";
import type { Milestone } from "@/features/projects/types";
import { formatLocalDate } from "@/lib/dates";

/** A milestone at risk or cancelled is not the same as one merely planned, and reads differently. */
function milestoneTone(status: Milestone["status"]): "good" | "warn" | "neutral" | "bad" {
  if (status === "completed") return "good";
  if (status === "at_risk") return "warn";
  return "neutral";
}

export function ProjectPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const project = useProject(id);
  const members = useMembers(id);
  const milestones = useMilestones(id);
  const decisions = useDecisions(id);
  const progress = useProgress(id);
  const session = useSession();
  // The route is signed-in, not professor-only: a student member can open their own project.
  const isProf = session.data?.role === "prof";

  if (project.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (project.isError)
    return <p className="text-sm text-muted-foreground">{t("project.unavailable")}</p>;

  const data = project.data;
  // AUTH-07: whoever started the project may keep its description right, for as long as it
  // exists. Its standing — status, who may join, the AI restriction — stays the professor's.
  const isCreator = Boolean(session.data && data.created_by === session.data.id);
  // PROJ-06 reports a 0–1 fraction (`accepted_completion` is Numeric(3, 2)), and Decimal crosses
  // the wire as a string — so 87.5% complete arrives as "0.8750". Scale it once, here: read as a
  // percentage it showed "0.875%", and a meter driven by it would sit almost empty.
  const fraction = progress.data?.weighted_completion;
  const completion = fraction == null ? null : Math.round(Number(fraction) * 1000) / 10;

  return (
    <section className="animate-rise-in">
      <header className="border-b border-border pb-5">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="page-title">{data.title}</h1>
          <Badge>{t(`project.stage.${data.stage}`, { defaultValue: data.stage })}</Badge>
          <Badge tone={data.status === "active" ? "good" : "neutral"}>
            {t(`project.status.${data.status}`, { defaultValue: data.status })}
          </Badge>
          {data.ai_restricted && <Badge tone="warn">{t("project.aiRestricted")}</Badge>}
        </div>
        {data.description && (
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink2">{data.description}</p>
        )}
        {isProf ? <StatusControls project={data} /> : null}
        {isProf || isCreator ? <ProjectFieldsForm project={data} /> : null}
        {!isProf ? <MembershipControls project={data} /> : null}
      </header>

      <div className="mt-7 grid gap-7 [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]">
        {data.research_questions.length > 0 && (
          <div>
            <h2 className="section-title mb-2">{t("project.researchQuestions")}</h2>
            <ol className="list-decimal space-y-1.5 pl-5 text-[13.5px] leading-relaxed">
              {data.research_questions.map((question, index) => (
                <li key={index}>{question}</li>
              ))}
            </ol>
          </div>
        )}

        <div>
          <h2 className="section-title mb-2">{t("project.progress")}</h2>
          {completion === null || completion === undefined ? (
            <p className="text-sm text-muted-foreground" data-testid="project-progress">
              {t("project.noWeights")}
            </p>
          ) : (
            <>
              <p className="figure" data-testid="project-progress">
                {completion}
                <span className="figure-unit">%</span>
              </p>
              <span className="meter mt-2.5">
                <span
                  className="meter-fill"
                  style={{ width: `${Math.max(0, Math.min(100, completion))}%` }}
                />
              </span>
            </>
          )}
          <p className="stamp mt-2">
            {t("project.milestoneCounts", {
              done: progress.data?.completed_milestones ?? 0,
              total: progress.data?.milestone_count ?? 0,
              overdue: progress.data?.overdue_milestones ?? 0,
            })}
          </p>
          <p className="stamp">{t("project.progressNote")}</p>
        </div>
      </div>

      <div className="mt-8 grid gap-7 [grid-template-columns:repeat(auto-fit,minmax(320px,1fr))]">
        <div>
          <h2 className="section-title mb-2.5">{t("project.members")}</h2>
          <ul className="panel">
            {members.data?.map((member) => (
              <li key={member.id} className="row">
                <Link to={`/students/${member.student_id}`} className="text-[13px]">
                  {member.student_name || member.student_id.slice(0, 8)}
                </Link>
                <span className="text-right font-mono text-[11.5px] text-muted-foreground">
                  {member.responsibility || t("project.noResponsibility")} ·{" "}
                  {formatLocalDate(member.joined_on)}
                  {member.left_on ? ` – ${formatLocalDate(member.left_on)}` : ""}
                </span>
              </li>
            ))}
            {members.data?.length === 0 && (
              <li className="px-4 py-2.5 text-sm text-muted-foreground">
                {t("project.noMembers")}
              </li>
            )}
          </ul>
          {isProf ? <AddMemberForm project={data} /> : null}
        </div>

        <div>
          <h2 className="section-title mb-2.5">{t("project.milestones")}</h2>
          <ul className="panel">
            {milestones.data?.map((milestone) => (
              <li key={milestone.id} className="row">
                <span>
                  {milestone.title}
                  {milestone.target_on ? (
                    <span className="ml-2 font-mono text-[11px] text-faint">
                      {formatLocalDate(milestone.target_on)}
                    </span>
                  ) : null}
                </span>
                <Badge tone={milestoneTone(milestone.status)}>
                  {t(`project.milestoneStatus.${milestone.status}`, {
                    defaultValue: milestone.status,
                  })}
                </Badge>
              </li>
            ))}
            {milestones.data?.length === 0 && (
              <li className="px-4 py-2.5 text-sm text-muted-foreground">
                {t("project.noMilestones")}
              </li>
            )}
          </ul>
        </div>
      </div>

      <h2 className="section-title mt-8">{t("project.decisions")}</h2>
      <ul
        className="mt-2.5 grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]"
        data-testid="decisions"
      >
        {decisions.data?.map((decision) => (
          <li key={decision.id} className="card">
            <p className="text-[13.5px] font-medium">{decision.decision}</p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
              {decision.rationale}
            </p>
            <p className="stamp mt-2">{formatLocalDate(decision.decided_on)}</p>
          </li>
        ))}
        {decisions.data?.length === 0 && (
          <li className="text-sm text-muted-foreground">{t("project.noDecisions")}</li>
        )}
      </ul>
    </section>
  );
}
