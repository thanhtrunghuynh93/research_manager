/**
 * Workspaces: the ones this professor belongs to, and the one they are working in.
 *
 * **Join** adds a membership, **Leave** takes it away, and a professor may hold several at once
 * (ADR 0015). What is singular is which one they are *working in* — every other screen shows that
 * one's data — and moving between them is the switcher in the header, not a button here: it is
 * the frame the other screens are read in rather than an administrative act.
 *
 * Leaving is refused when it would strand people in a workspace with no professor, and when it is
 * the only membership left, because an account has to be in one. Both refusals come back from the
 * API in its own words rather than being guessed at here.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/evidence/Badges";
import { Failure } from "@/components/Failure";
import { CalendarPanel } from "@/features/calendar/components/CalendarPanel";
import { AiBudgetPanel } from "@/features/workspaces/components/AiBudgetPanel";
import { useSession } from "@/features/auth/queries";
import {
  useArchiveWorkspace,
  useCreateWorkspace,
  useJoinWorkspace,
  useLeaveWorkspace,
  useWorkspaces,
} from "@/features/workspaces/queries";
import type { Workspace } from "@/features/workspaces/types";

export function WorkspacesPage() {
  const { t } = useTranslation();
  const workspaces = useWorkspaces();
  const session = useSession();

  if (workspaces.isPending) return <p className="stamp">{t("common.loading")}</p>;

  const current = session.data?.workspace_id;

  return (
    <section className="animate-rise-in">
      <header className="border-b border-border pb-5">
        <p className="eyebrow mb-1.5">{t("workspaces.eyebrow")}</p>
        <h1 className="page-title">{t("workspaces.title")}</h1>
      </header>

      <ul className="panel mt-6" data-testid="workspace-list">
        {workspaces.data?.map((workspace) => (
          <WorkspaceRow key={workspace.id} workspace={workspace} here={workspace.id === current} />
        ))}
      </ul>
      <p className="stamp mt-2">{t("workspaces.note")}</p>

      <CreateForm />
      <CalendarPanel />
      <AiBudgetPanel />
    </section>
  );
}

/** Archiving is the end of a workspace, so the list never carries an archived one to render. */
function WorkspaceRow({ workspace, here }: { workspace: Workspace; here: boolean }) {
  const { t } = useTranslation();
  const join = useJoinWorkspace();
  const leave = useLeaveWorkspace();
  const archive = useArchiveWorkspace();
  const busy = join.isPending || leave.isPending;

  return (
    <li className="row flex-wrap gap-y-2">
      <span className="flex flex-wrap items-center gap-2.5">
        <span className="text-prose">{workspace.name}</span>
        {here && <Badge>{t("workspaces.here")}</Badge>}
        <span className="font-mono text-meta text-faint">{workspace.timezone}</span>
      </span>
      <span className="flex flex-wrap items-center gap-3">
        {/* Going to a workspace you already belong to is the switcher's job now, and it lives in
            the header where every screen can reach it. What is left here is what changes the set
            you can switch between: join one, or stop belonging to one. */}
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            workspace.joined ? leave.mutate(workspace.id) : join.mutate(workspace.id)
          }
          className="btn-quiet"
        >
          {workspace.joined ? t("workspaces.leave") : t("workspaces.join")}
        </button>
        {/* Archiving needs the workspace empty, so it is never offered for one you belong to:
            you are an account standing in the way. Leave first, then archive. */}
        {!workspace.joined && (
          <button
            type="button"
            disabled={archive.isPending}
            onClick={() => archive.mutate(workspace.id)}
            className="btn-quiet"
          >
            {t("workspaces.archive")}
          </button>
        )}
        {join.variables === workspace.id && <Failure error={join.error} />}
        {leave.variables === workspace.id && <Failure error={leave.error} />}
        {archive.variables === workspace.id && <Failure error={archive.error} />}
      </span>
    </li>
  );
}

/** A new workspace starts empty, you join it, and you keep every workspace you were already in. */
function CreateForm() {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const create = useCreateWorkspace();

  return (
    <form
      className="panel mt-8 max-w-2xl p-4"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate({ name }, { onSuccess: () => setName("") });
      }}
    >
      <h2 className="section-title">{t("workspaces.create")}</h2>
      <div className="mt-3 flex flex-wrap items-end gap-4">
        <label className="block min-w-[15rem] flex-1">
          <span className="field-label">{t("workspaces.name")}</span>
          <input
            type="text"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="input"
          />
        </label>
        <button type="submit" disabled={create.isPending} className="btn-primary">
          {t("workspaces.createAction")}
        </button>
      </div>
      <p className="stamp mt-3">{t("workspaces.createNote")}</p>
      <p className="mt-2">
        <Failure error={create.error} />
      </p>
    </form>
  );
}
