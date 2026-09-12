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
function milestoneTone(status: Milestone["status"]): "good" | "warn" | "neutral" {
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

  if (project.isPending) return <p className="text-muted-foreground">{t("common.loading")}</p>;
  if (project.isError) return <p className="text-muted-foreground">{t("project.unavailable")}</p>;

  const data = project.data;

  return (
    <section className="space-y-8">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">{data.title}</h1>
          <Badge>{t(`project.stage.${data.stage}`, { defaultValue: data.stage })}</Badge>
          <Badge tone={data.status === "active" ? "good" : "neutral"}>
            {t(`project.status.${data.status}`, { defaultValue: data.status })}
          </Badge>
          {data.ai_restricted && <Badge tone="warn">{t("project.aiRestricted")}</Badge>}
        </div>
        {data.description && <p className="text-sm text-muted-foreground">{data.description}</p>}
      </header>

      {data.research_questions.length > 0 && (
        <div className="space-y-1">
          <h2 className="text-sm font-medium">{t("project.researchQuestions")}</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {data.research_questions.map((question, index) => (
              <li key={index}>{question}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-1">
        <h2 className="text-sm font-medium">{t("project.progress")}</h2>
        <p className="text-sm" data-testid="project-progress">
          {progress.data?.weighted_completion === null ||
          progress.data?.weighted_completion === undefined
            ? t("project.noWeights")
            : `${progress.data.weighted_completion}%`}
        </p>
        <p className="text-xs text-muted-foreground">
          {t("project.milestoneCounts", {
            done: progress.data?.completed_milestones ?? 0,
            total: progress.data?.milestone_count ?? 0,
            overdue: progress.data?.overdue_milestones ?? 0,
          })}
        </p>
        <p className="text-xs text-muted-foreground">{t("project.progressNote")}</p>
      </div>

      <div className="space-y-2">
        <h2 className="text-sm font-medium">{t("project.members")}</h2>
        <ul className="divide-y divide-border rounded-lg border border-border">
          {members.data?.map((member) => (
            <li key={member.id} className="flex items-center justify-between px-4 py-2 text-sm">
              <Link to={`/students/${member.student_id}`} className="underline">
                {member.student_id.slice(0, 8)}
              </Link>
              <span className="text-muted-foreground">
                {member.responsibility || t("project.noResponsibility")} ·{" "}
                {formatLocalDate(member.joined_on)}
                {member.left_on ? ` – ${formatLocalDate(member.left_on)}` : ""}
              </span>
            </li>
          ))}
          {members.data?.length === 0 && (
            <li className="px-4 py-2 text-sm text-muted-foreground">{t("project.noMembers")}</li>
          )}
        </ul>
      </div>

      <div className="space-y-2">
        <h2 className="text-sm font-medium">{t("project.milestones")}</h2>
        <ul className="divide-y divide-border rounded-lg border border-border">
          {milestones.data?.map((milestone) => (
            <li key={milestone.id} className="flex items-center justify-between px-4 py-2 text-sm">
              <span>{milestone.title}</span>
              <span className="flex items-center gap-2 text-muted-foreground">
                {milestone.target_on ? formatLocalDate(milestone.target_on) : ""}
                <Badge tone={milestoneTone(milestone.status)}>
                  {t(`project.milestoneStatus.${milestone.status}`, {
                    defaultValue: milestone.status,
                  })}
                </Badge>
              </span>
            </li>
          ))}
          {milestones.data?.length === 0 && (
            <li className="px-4 py-2 text-sm text-muted-foreground">{t("project.noMilestones")}</li>
          )}
        </ul>
      </div>

      <div className="space-y-2">
        <h2 className="text-sm font-medium">{t("project.decisions")}</h2>
        <ul className="space-y-2" data-testid="decisions">
          {decisions.data?.map((decision) => (
            <li key={decision.id} className="rounded-md border border-border p-3 text-sm">
              <p className="font-medium">{decision.decision}</p>
              <p className="text-muted-foreground">{decision.rationale}</p>
              <p className="text-xs text-muted-foreground">
                {formatLocalDate(decision.decided_on)}
              </p>
            </li>
          ))}
          {decisions.data?.length === 0 && (
            <li className="text-sm text-muted-foreground">{t("project.noDecisions")}</li>
          )}
        </ul>
      </div>
    </section>
  );
}
