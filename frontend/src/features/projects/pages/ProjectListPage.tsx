/**
 * The projects in this workspace, and the form that starts one (PROJ-01, UI-03).
 *
 * This screen exists as much for navigation as for its own content: `/projects/:id` implements
 * UI-03 in full and, until this list, nothing in the app linked to it. A professor could reach the
 * project workspace only by typing a UUID or by following an assistant citation that happened to
 * be a project path.
 *
 * `GET /projects` is signed-in rather than professor-only, so a student sees the projects they are
 * on. Since PROJ-07 the create form is not gated either: a student starts their own project, and
 * the panel below the list offers the ones a professor has opened to joining.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Badge } from "@/components/evidence/Badges";
import { Failure } from "@/components/Failure";
import { useSession } from "@/features/auth/queries";
import {
  useCreateProject,
  useJoinableProjects,
  useJoinProject,
  useProjectList,
} from "@/features/projects/queries";
import { STAGES, STATUSES, type ResearchStage } from "@/features/projects/types";
import { formatLocalDate } from "@/lib/dates";

export function ProjectListPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState("");
  const projects = useProjectList(status || undefined);
  const session = useSession();
  const isProf = session.data?.role === "prof";

  return (
    <section className="animate-rise-in">
      <header className="border-b border-border pb-5">
        <p className="eyebrow mb-1.5">{t("projects.eyebrow")}</p>
        <h1 className="page-title">{t("projects.title")}</h1>
        <p className="stamp mt-2">{t("projects.intro")}</p>
      </header>

      <CreateForm isProf={isProf} />

      <div className="mt-8 flex items-end gap-4">
        <label className="block">
          <span className="field-label">{t("projects.filter")}</span>
          <select
            aria-label={t("projects.filter")}
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="select"
          >
            <option value="">{t("projects.all")}</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {t(`project.status.${value}`, { defaultValue: value })}
              </option>
            ))}
          </select>
        </label>
      </div>

      {projects.isPending ? <p className="stamp mt-4">{t("common.loading")}</p> : null}
      {projects.isError ? (
        <p className="mt-4">
          <Failure error={projects.error} />
        </p>
      ) : null}

      {projects.data ? (
        projects.data.items.length ? (
          <ul className="panel mt-3" data-testid="project-list">
            {projects.data.items.map((project) => (
              <li key={project.id} className="row">
                <div className="min-w-0">
                  <Link to={`/projects/${project.id}`} className="link font-medium">
                    {project.title}
                  </Link>
                  <p className="stamp mt-0.5">
                    {t(`project.stage.${project.stage}`, { defaultValue: project.stage })}
                    {project.start_on ? ` · ${formatLocalDate(project.start_on)}` : ""}
                  </p>
                </div>
                <Badge tone={project.status === "active" ? "good" : "neutral"}>
                  {t(`project.status.${project.status}`, { defaultValue: project.status })}
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="stamp mt-4">{t("projects.none")}</p>
        )
      ) : null}

      {!isProf && session.data ? <JoinablePanel /> : null}
    </section>
  );
}

/**
 * The projects a professor has opened to joining (PROJ-07).
 *
 * Deliberately thin — title, stage, how many people are on it. A student who has not joined has no
 * claim on the research questions, and the endpoint behind this does not serve them. Hidden when
 * empty rather than shown as an empty state: in a workspace where the professor opens nothing, an
 * empty panel would advertise a feature that will never do anything here.
 */
function JoinablePanel() {
  const { t } = useTranslation();
  const joinable = useJoinableProjects(true);
  const join = useJoinProject();

  if (!joinable.data?.length) return null;

  return (
    <section className="mt-8" data-testid="joinable">
      <h2 className="section-title">{t("projects.joinable")}</h2>
      <p className="stamp mt-1">{t("projects.joinableNote")}</p>
      <ul className="panel mt-3">
        {joinable.data.map((project) => (
          <li key={project.id} className="row">
            <div className="min-w-0">
              <p className="font-medium">{project.title}</p>
              <p className="stamp mt-0.5">
                {t(`project.stage.${project.stage}`, { defaultValue: project.stage })}
                {" · "}
                {t("projects.memberCount", { count: project.member_count })}
              </p>
            </div>
            <button
              type="button"
              disabled={join.isPending}
              onClick={() => join.mutate(project.id)}
              className="btn-ghost"
              data-testid="join-project"
            >
              {t("projects.join")}
            </button>
          </li>
        ))}
      </ul>
      <Failure error={join.error} />
    </section>
  );
}

/**
 * A professor's new project is `proposed`, and nothing becomes due on a proposed project — the
 * obligation query requires `active`. That is the trap this form has to name, because everything
 * else about assigning a student looks like it worked. A student's own project is active from the
 * moment they create it and they are on it, so their note says the opposite thing.
 */
function CreateForm({ isProf }: { isProf: boolean }) {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [stage, setStage] = useState<ResearchStage>("implementation");
  const [description, setDescription] = useState("");
  const [questions, setQuestions] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const create = useCreateProject();

  return (
    <form
      className="panel mt-6 max-w-2xl p-4"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate(
          {
            title,
            stage,
            description,
            research_questions: questions
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean),
            repo_url: repoUrl.trim() || null,
          },
          {
            onSuccess: () => {
              setTitle("");
              setDescription("");
              setQuestions("");
              setRepoUrl("");
            },
          },
        );
      }}
    >
      <h2 className="section-title">{t("projects.create")}</h2>
      <div className="mt-3 flex flex-wrap gap-4">
        <label className="block min-w-[15rem] flex-1">
          <span className="field-label">{t("projects.titleField")}</span>
          <input
            type="text"
            required
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className="input"
          />
        </label>
        <label className="block">
          <span className="field-label">{t("projects.stage")}</span>
          <select
            aria-label={t("projects.stage")}
            value={stage}
            onChange={(event) => setStage(event.target.value as ResearchStage)}
            className="select"
          >
            {STAGES.map((value) => (
              <option key={value} value={value}>
                {t(`project.stage.${value}`, { defaultValue: value })}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="mt-4 block">
        <span className="field-label">{t("projects.description")}</span>
        <textarea
          rows={2}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          className="input"
        />
      </label>

      <label className="mt-4 block">
        <span className="field-label">{t("projects.repoUrl")}</span>
        <input
          type="url"
          value={repoUrl}
          onChange={(event) => setRepoUrl(event.target.value)}
          placeholder="https://github.com/..."
          className="input"
        />
        <span className="stamp mt-1 block">{t("projects.repoUrlHint")}</span>
      </label>

      <label className="mt-4 block">
        <span className="field-label">{t("projects.researchQuestions")}</span>
        <textarea
          rows={3}
          value={questions}
          onChange={(event) => setQuestions(event.target.value)}
          className="input"
        />
        <span className="stamp mt-1 block">{t("projects.researchQuestionsHint")}</span>
      </label>

      <div className="mt-4 flex items-center gap-4">
        <button type="submit" disabled={create.isPending} className="btn-primary">
          {t("projects.createAction")}
        </button>
        <Failure error={create.error} />
      </div>
      <p className="stamp mt-3">
        {isProf ? t("projects.createNote") : t("projects.createNoteStudent")}
      </p>
    </form>
  );
}
