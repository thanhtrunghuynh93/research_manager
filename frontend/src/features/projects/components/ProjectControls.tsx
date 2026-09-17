/**
 * The two writes that make a project able to produce work (PROJ-01, PROJ-02).
 *
 * They are on the project page rather than anywhere else because they are the two halves of one
 * decision — this project is real, and these people are on it — and because the chain that ends in
 * a student owing a report runs through both.
 *
 * The activation control is the load-bearing one. `POST /projects` creates a project `proposed`,
 * and an obligation only derives from a membership whose project is `active`. A professor who
 * creates a project and assigns a student has done everything that looks like the job and produced
 * nothing. So activation is its own button with its own sentence, rather than one value in a
 * status dropdown.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Failure } from "@/components/Failure";
import { useSession } from "@/features/auth/queries";
import { usePeople } from "@/features/people/queries";
import { useAddMember, useUpdateProject } from "@/features/projects/queries";
import { STATUSES, type Project, type ProjectStatus } from "@/features/projects/types";
import { todayLocal } from "@/lib/dates";

export function StatusControls({ project }: { project: Project }) {
  const { t } = useTranslation();
  const update = useUpdateProject(project.id);
  const proposed = project.status === "proposed";

  return (
    <div className="mt-4" data-testid="project-status-controls">
      <div className="flex flex-wrap items-end gap-4">
        {proposed ? (
          <button
            type="button"
            disabled={update.isPending}
            onClick={() => update.mutate({ status: "active" })}
            className="btn-primary"
            data-testid="activate-project"
          >
            {t("project.activate")}
          </button>
        ) : null}

        <label className="block">
          <span className="field-label">{t("project.setStatus")}</span>
          <select
            aria-label={t("project.setStatus")}
            value={project.status}
            onChange={(event) =>
              update.mutate({ status: event.target.value as ProjectStatus })
            }
            className="select"
            data-testid="project-status"
          >
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {t(`project.status.${value}`, { defaultValue: value })}
              </option>
            ))}
          </select>
        </label>
        <Failure error={update.error} />
      </div>

      {proposed ? <p className="stamp mt-2">{t("project.activateNote")}</p> : null}
    </div>
  );
}

/**
 * The picker is limited to students of the workspace this professor is *working in*.
 *
 * Not cosmetic. Since ADR 0016 the roll spans every workspace they belong to, but a membership row
 * is written with the anchor's workspace id against a composite foreign key — so assigning someone
 * from another workspace would fail in the database rather than be refused in words.
 */
export function AddMemberForm({ project }: { project: Project }) {
  const { t } = useTranslation();
  const session = useSession();
  const people = usePeople();
  const add = useAddMember(project.id);

  const [studentId, setStudentId] = useState("");
  const [responsibility, setResponsibility] = useState("");
  const [joinedOn, setJoinedOn] = useState(todayLocal());

  const candidates = (people.data?.users ?? []).filter(
    (person) =>
      person.role === "student" &&
      person.state !== "deactivated" &&
      person.workspace_id === session.data?.workspace_id,
  );

  if (people.isPending) return null;

  if (!candidates.length) {
    return (
      <p className="stamp mt-3" data-testid="no-students">
        {t("project.noStudents")} <Link to="/people" className="link">{t("people.title")}</Link>
      </p>
    );
  }

  return (
    <form
      className="mt-3 border-t border-border pt-3"
      data-testid="add-member"
      onSubmit={(event) => {
        event.preventDefault();
        add.mutate(
          { student_id: studentId, responsibility, joined_on: joinedOn },
          { onSuccess: () => { setStudentId(""); setResponsibility(""); } },
        );
      }}
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="block min-w-[12rem] flex-1">
          <span className="field-label">{t("project.student")}</span>
          <select
            aria-label={t("project.student")}
            required
            value={studentId}
            onChange={(event) => setStudentId(event.target.value)}
            className="select"
          >
            <option value="">{t("project.chooseStudent")}</option>
            {candidates.map((person) => (
              <option key={person.id} value={person.id}>
                {person.display_name || person.email}
              </option>
            ))}
          </select>
        </label>
        <label className="block min-w-[10rem] flex-1">
          <span className="field-label">{t("project.responsibility")}</span>
          <input
            type="text"
            value={responsibility}
            onChange={(event) => setResponsibility(event.target.value)}
            className="input"
          />
        </label>
        <label className="block">
          <span className="field-label">{t("project.joinedOn")}</span>
          <input
            type="date"
            required
            value={joinedOn}
            onChange={(event) => setJoinedOn(event.target.value)}
            className="input"
          />
        </label>
        <button type="submit" disabled={add.isPending} className="btn-secondary">
          {t("project.assign")}
        </button>
      </div>
      <p className="mt-2">
        <Failure error={add.error} />
      </p>
    </form>
  );
}
