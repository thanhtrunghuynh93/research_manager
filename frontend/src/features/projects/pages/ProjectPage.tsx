/**
 * UI-03: the project workspace — goals, members and milestones.
 *
 * Membership history is shown rather than hidden: a project's record includes who worked on it
 * and when, and deleting that would make the supervision history unreadable (PROJ-02).
 *
 * Two panels UI-03 names are deliberately absent, and both for the same reason — nothing in the
 * product writes what they would show. **Milestone completion** was milestone weights against
 * `accepted_completion`, a column only `PATCH /milestones/{id}` sets and no screen calls, so it
 * read 0% for every project in the deployment and read it as a fact. **Research decisions** is
 * professor-only to record and likewise has no screen, so the panel said "No decisions recorded"
 * about projects whose decisions had simply never had anywhere to go. `GET /{id}/progress` and
 * `GET /{id}/decisions` still answer, and both panels are a screen's worth of work away the day
 * the authoring side exists.
 */
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Badge } from "@/components/evidence/Badges";
import { ProjectDocuments } from "@/features/projects/components/ProjectDocuments";
import { useSession } from "@/features/auth/queries";
import {
  AddMemberForm,
  EndMembershipButton,
  ProjectFieldsForm,
  StatusControls,
} from "@/features/projects/components/ProjectControls";
import { useMembers, useMilestones, useProject } from "@/features/projects/queries";
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
  const session = useSession();
  // The route is signed-in, not professor-only: a student member can open their own project.
  const isProf = session.data?.role === "prof";
  // A student who has left keeps the record — their reports and assessments still refer to it —
  // but not what the project is doing now: `_in_scope` still gates the milestones and the member
  // list. Those queries therefore answer empty rather than forbidden, and an empty list rendered
  // as "No milestones yet" would state something this reader cannot actually know. So the page
  // shows what it has and says plainly what it is not showing.
  const left = !isProf && project.data?.viewer_left_on ? project.data.viewer_left_on : null;
  // And asks for none of it: a request answered and then discarded is the shape of a screen that
  // decided what to show after deciding what to fetch. They wait for the project rather than
  // merely stopping once it arrives: a request already in flight cannot be recalled, and
  // `viewer_left_on` is the field that decides.
  const wanted = Boolean(project.data) && !left;
  const members = useMembers(id, wanted);
  const milestones = useMilestones(id, wanted && session.data?.role === "prof");

  if (project.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (project.isError)
    return <p className="text-sm text-muted-foreground">{t("project.unavailable")}</p>;

  const data = project.data;
  // AUTH-07: whoever started the project may keep its description right, for as long as it
  // exists. Its standing — status, who may join, the AI restriction — stays the professor's.
  const isCreator = Boolean(session.data && data.created_by === session.data.id);
  // Attaching a document needs a current membership rather than authorship: the people working on
  // a project are the people who have documents for it (ADR 0018).
  const isMember = Boolean(
    session.data &&
    members.data?.some((member) => member.student_id === session.data?.id && !member.left_on),
  );

  return (
    <section className="animate-rise-in">
      <header className="border-b border-border pb-5">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="page-title">{data.title}</h1>
          {isProf && (
            <Badge>{t(`project.stage.${data.stage}`, { defaultValue: data.stage })}</Badge>
          )}
          <Badge tone={data.status === "active" ? "good" : "neutral"}>
            {t(`project.status.${data.status}`, { defaultValue: data.status })}
          </Badge>
          {data.ai_restricted && <Badge tone="warn">{t("project.aiRestricted")}</Badge>}
        </div>
        {data.description && (
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink2">{data.description}</p>
        )}
        {data.repo_url && (
          <p className="mt-2 text-sm">
            <a
              href={data.repo_url}
              target="_blank"
              rel="noreferrer noopener"
              className="link"
              data-testid="project-repo"
            >
              {data.repo_url}
            </a>
          </p>
        )}
        {isProf ? <StatusControls project={data} /> : null}
        {isProf || isCreator ? <ProjectFieldsForm project={data} canSetStage={isProf} /> : null}
        {left ? (
          <>
            <p className="notice-warn mt-4 max-w-2xl" role="status" data-testid="left-notice">
              {t("project.leftNotice", { when: formatLocalDate(left) })}
            </p>
            {/* Everything below the header is withheld from this reader, so without a way onward
                the page is a dead end — and they arrived here from a link on their own week. */}
            <p className="stamp mt-3">
              <Link to="/projects" className="link">
                {t("project.backToProjects")}
              </Link>
            </p>
          </>
        ) : null}
      </header>

      <div className="mt-7 grid gap-7 [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]">
        {data.research_questions.length > 0 && (
          <div>
            <h2 className="section-title mb-2">{t("project.researchQuestions")}</h2>
            <ol className="list-decimal space-y-1.5 pl-5 text-prose leading-relaxed">
              {data.research_questions.map((question, index) => (
                <li key={index}>{question}</li>
              ))}
            </ol>
          </div>
        )}
      </div>

      {left ? null : (
        <div className="mt-8 grid gap-7 [grid-template-columns:repeat(auto-fit,minmax(320px,1fr))]">
          <div>
            <h2 className="section-title mb-2.5">{t("project.members")}</h2>
            <ul className="panel">
              {members.data?.map((member) => (
                <li key={member.id} className="row">
                  <Link to={`/students/${member.student_id}`} className="text-ui">
                    {member.student_name || member.student_id.slice(0, 8)}
                  </Link>
                  <span className="flex items-center gap-3">
                    <span className="text-right font-mono text-meta text-muted-foreground">
                      {member.responsibility || t("project.noResponsibility")} ·{" "}
                      {formatLocalDate(member.joined_on)}
                      {member.left_on ? ` – ${formatLocalDate(member.left_on)}` : ""}
                    </span>
                    {isProf && !member.left_on && (
                      <EndMembershipButton
                        project={data}
                        membershipId={member.id}
                        name={member.student_name || member.student_id.slice(0, 8)}
                      />
                    )}
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

          {isProf && (
            <div>
              <h2 className="section-title mb-2.5">{t("project.milestones")}</h2>
              <ul className="panel">
                {milestones.data?.map((milestone) => (
                  <li key={milestone.id} className="row">
                    <span>
                      {milestone.title}
                      {milestone.target_on ? (
                        <span className="ml-2 font-mono text-meta text-faint">
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
          )}

          {/* A member may attach; a professor may attach and read; a student who has left this
              project never reaches here, because the whole block is withheld from them. */}
          <ProjectDocuments projectId={data.id} canAttach={isProf || isMember} />
        </div>
      )}
    </section>
  );
}
