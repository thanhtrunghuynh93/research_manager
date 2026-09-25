/**
 * Workspaces: the one being worked in first, then the others this professor belongs to.
 *
 * Ordered by how often each part is used. The workspace in the header — its name and its weekly
 * schedule — is what a professor comes here to change; the list of other memberships is second;
 * creating a workspace is rare and sits folded at the bottom. Model spend is not on this screen:
 * with no ceiling set nothing is capped, and the setting read as a bill rather than a control.
 *
 * **Join** adds a membership, **Leave** takes it away, and a professor may hold several at once
 * (ADR 0015). Moving between them is the header's switcher, not a button here. Leaving is refused
 * when it would strand people in a workspace with no professor, and when it is the only membership
 * left; both refusals come back from the API in its own words rather than being guessed at here.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/evidence/Badges";
import { Failure } from "@/components/Failure";
import { CalendarPanel } from "@/features/calendar/components/CalendarPanel";
import { useSession } from "@/features/auth/queries";
import {
  useArchiveWorkspace,
  useCreateWorkspace,
  useJoinWorkspace,
  useLeaveWorkspace,
  useRenameWorkspace,
  useWorkspaces,
} from "@/features/workspaces/queries";
import type { Workspace } from "@/features/workspaces/types";

export function WorkspacesPage() {
  const { t } = useTranslation();
  const workspaces = useWorkspaces();
  const session = useSession();

  if (workspaces.isPending) return <p className="stamp">{t("common.loading")}</p>;

  const currentId = session.data?.workspace_id;
  const all = workspaces.data ?? [];
  const current = all.find((workspace) => workspace.id === currentId);

  return (
    <section className="animate-rise-in">
      <header className="border-b border-border pb-5">
        <p className="eyebrow mb-1.5">{t("workspaces.eyebrow")}</p>
        <h1 className="page-title">{t("workspaces.title")}</h1>
      </header>

      {current && (
        <ThisWorkspace workspace={current} canRename={current.owner_id === session.data?.id} />
      )}
      <CalendarPanel />

      <section className="mt-10">
        <h2 className="section-title">{t("workspaces.yours")}</h2>
        <ul className="panel mt-2.5" data-testid="workspace-list">
          {all.map((workspace) => (
            <WorkspaceRow
              key={workspace.id}
              workspace={workspace}
              here={workspace.id === currentId}
            />
          ))}
        </ul>
        <p className="stamp mt-2">{t("workspaces.note")}</p>
      </section>

      <CreateWorkspace />
    </section>
  );
}

/**
 * The name, and the way to change it. Renaming is the owner's (ADR 0012) and the API refuses anyone
 * else, so a colleague sees the name without an edit button that would only ever fail.
 */
function ThisWorkspace({ workspace, canRename }: { workspace: Workspace; canRename: boolean }) {
  const { t } = useTranslation();
  const rename = useRenameWorkspace(workspace.id);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(workspace.name);

  return (
    <section className="panel mt-6 p-4" data-testid="this-workspace">
      <p className="eyebrow">{t("workspaces.thisOne")}</p>
      {editing ? (
        <form
          className="mt-2 flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            rename.mutate({ name: name.trim() }, { onSuccess: () => setEditing(false) });
          }}
        >
          <label className="block min-w-[15rem] flex-1">
            <span className="field-label">{t("workspaces.name")}</span>
            <input
              type="text"
              required
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="input"
            />
          </label>
          <button type="submit" disabled={rename.isPending} className="btn-primary">
            {t("common.save")}
          </button>
          <button
            type="button"
            className="btn-quiet"
            onClick={() => {
              setName(workspace.name);
              setEditing(false);
            }}
          >
            {t("common.cancel")}
          </button>
        </form>
      ) : (
        <div className="mt-1 flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-title font-semibold" data-testid="workspace-name">
            {workspace.name}
          </h2>
          {canRename && (
            <button type="button" className="btn-quiet" onClick={() => setEditing(true)}>
              {t("workspaces.rename")}
            </button>
          )}
        </div>
      )}
      <p className="mt-1 font-mono text-meta text-faint">{workspace.timezone}</p>
      <p className="mt-2">
        <Failure error={rename.error} />
      </p>
    </section>
  );
}

/** Archiving is the end of a workspace, so it asks once more before it happens. */
function WorkspaceRow({ workspace, here }: { workspace: Workspace; here: boolean }) {
  const { t } = useTranslation();
  const join = useJoinWorkspace();
  const leave = useLeaveWorkspace();
  const archive = useArchiveWorkspace();
  const [confirming, setConfirming] = useState(false);
  const busy = join.isPending || leave.isPending;

  return (
    <li className="row flex-wrap gap-y-2">
      <span className="flex flex-wrap items-center gap-2.5">
        <span className="text-prose">{workspace.name}</span>
        {here && <Badge>{t("workspaces.here")}</Badge>}
        <span className="font-mono text-meta text-faint">{workspace.timezone}</span>
      </span>
      <span className="flex flex-wrap items-center gap-3">
        {confirming ? (
          <>
            <span className="text-ui">{t("workspaces.archiveConfirm")}</span>
            <button
              type="button"
              disabled={archive.isPending}
              onClick={() => archive.mutate(workspace.id)}
              className="btn-quiet"
            >
              {t("workspaces.archive")}
            </button>
            <button type="button" className="btn-quiet" onClick={() => setConfirming(false)}>
              {t("common.cancel")}
            </button>
          </>
        ) : (
          <>
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
              <button type="button" onClick={() => setConfirming(true)} className="btn-quiet">
                {t("workspaces.archive")}
              </button>
            )}
          </>
        )}
        {join.variables === workspace.id && <Failure error={join.error} />}
        {leave.variables === workspace.id && <Failure error={leave.error} />}
        {archive.variables === workspace.id && <Failure error={archive.error} />}
      </span>
    </li>
  );
}

/** Rare, so folded: a new workspace starts empty, you join it, and you keep the ones you had. */
function CreateWorkspace() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const create = useCreateWorkspace();

  if (!open)
    return (
      <p className="mt-6">
        <button type="button" className="btn-quiet" onClick={() => setOpen(true)}>
          {t("workspaces.create")}
        </button>
      </p>
    );

  return (
    <form
      className="panel mt-6 max-w-2xl p-4"
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
        <button type="button" className="btn-quiet" onClick={() => setOpen(false)}>
          {t("common.cancel")}
        </button>
      </div>
      <p className="stamp mt-3">{t("workspaces.createNote")}</p>
      <p className="mt-2">
        <Failure error={create.error} />
      </p>
    </form>
  );
}
