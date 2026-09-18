/**
 * AUTH-01: the roll — everyone in every workspace this professor belongs to, grouped by workspace,
 * and the three acts they have over a student.
 *
 * Reads span membership (ADR 0016) and writes do not: suspend, restore and remove act through
 * `/users/{id}/…`, which is scoped to the workspace the caller is working in. So a section for a
 * workspace they are not in lists its people and offers no buttons, and says why.
 *
 * The page is shaped by ADR 0011. Professors are equal over students and have no authority over
 * each other, so a colleague's row carries no buttons at all and says why rather than offering
 * something the API will refuse. A role cannot be changed here because it cannot be changed
 * anywhere: it is fixed when the invitation is accepted.
 *
 * Removal and suspension are kept visibly apart. Removal ends every project membership and does
 * not come back; suspension only closes the login and `Restore access` undoes it. They are one
 * click apart, so the destructive one asks a second time and names what it will do.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Badge } from "@/components/evidence/Badges";
import { Failure } from "@/components/Failure";
import { useCurrentWorkspace, useWorkspaces } from "@/features/workspaces/queries";
import { useSession } from "@/features/auth/queries";
import {
  useInvite,
  usePeople,
  useMoveStudent,
  useRemoveStudent,
  useRestore,
  useSuspend,
} from "@/features/people/queries";
import type { Role, User } from "@/features/people/types";
import type { Workspace } from "@/features/workspaces/types";
import { formatInstant } from "@/lib/dates";

const STATE_TONE = {
  active: "good",
  invited: "neutral",
  deactivated: "bad",
} as const;

export function PeoplePage() {
  const { t } = useTranslation();
  const people = usePeople();
  const session = useSession();
  const workspaces = useWorkspaces();
  const current = useCurrentWorkspace();

  const users = people.data?.users ?? [];
  const all = workspaces.data ?? [];

  // Grouped rather than labelled row by row: the roll spans every workspace this professor belongs
  // to (ADR 0016), and a flat list of two cohorts reads as one. Workspaces come from the list
  // endpoint so the order is stable and an empty one still gets a heading — "nobody here yet" is
  // an answer, and a missing section is not.
  const groups = all.map((workspace) => ({
    workspace,
    people: users.filter((user) => user.workspace_id === workspace.id),
  }));
  const single = all.length <= 1;

  return (
    <section className="animate-rise-in">
      <header>
        <p className="eyebrow mb-1.5" data-testid="people-workspace">
          {single ? t("people.label") : t("people.acrossWorkspaces", { count: all.length })}
        </p>
        <h1 className="page-title">{t("people.title")}</h1>
        <p className="mt-2 max-w-2xl text-[13.5px] text-muted-foreground">{t("people.intro")}</p>
      </header>

      <InviteForm />

      {groups.map(({ workspace, people: members }) => (
        <section key={workspace.id} className="mt-8" data-testid={`workspace-${workspace.id}`}>
          {!single && (
            <h2 className="section-title flex items-baseline gap-2.5">
              {workspace.name}
              {workspace.id === current?.id && <Badge>{t("workspaces.here")}</Badge>}
            </h2>
          )}
          <Roll
            members={members}
            workspace={workspace}
            isCurrent={workspace.id === current?.id}
            meId={session.data?.id}
            workspaces={all}
            headings={single}
          />
        </section>
      ))}

      {people.hasNextPage && (
        <button
          type="button"
          onClick={() => void people.fetchNextPage()}
          disabled={people.isFetchingNextPage}
          className="btn-ghost mt-4"
        >
          {t("people.more")}
        </button>
      )}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <li className="px-4 py-2.5 text-sm text-muted-foreground">{children}</li>;
}

/**
 * One workspace's professors and students.
 *
 * `headings` is on only when there is a single workspace: with several, the workspace name is the
 * heading and repeating "Professors"/"Students" above every pair of short lists is noise. The two
 * groups stay visually apart either way, because ADR 0011 gives a professor no controls over a
 * colleague and mixing them would make that absence look arbitrary.
 */
function Roll({
  members,
  workspace,
  isCurrent,
  meId,
  workspaces,
  headings,
}: {
  members: User[];
  workspace: Workspace;
  isCurrent: boolean;
  meId?: string;
  workspaces: Workspace[];
  headings: boolean;
}) {
  const { t } = useTranslation();
  const professors = members.filter((user) => user.role === "prof");
  const students = members.filter((user) => user.role === "student");

  return (
    <>
      {headings && <h2 className="section-title">{t("people.professors")}</h2>}
      <ul className="panel mt-2.5" data-testid={`professors-${workspace.id}`}>
        {professors.map((user) => (
          <li key={user.id} className="row">
            <Person user={user} isYou={user.id === meId} />
          </li>
        ))}
        {professors.length === 0 && <Empty>{t("people.noProfessors")}</Empty>}
      </ul>

      {headings && <h2 className="section-title mt-8">{t("people.students")}</h2>}
      <ul className="panel mt-2.5" data-testid={`students-${workspace.id}`}>
        {students.map((user) => (
          <li key={user.id} className="row items-start">
            <Person user={user} linkTo={`/students/${user.id}`} />
            <StudentActions user={user} inCurrent={isCurrent} workspaces={workspaces} />
          </li>
        ))}
        {students.length === 0 && <Empty>{t("people.noStudents")}</Empty>}
      </ul>
    </>
  );
}

function Person({ user, isYou, linkTo }: { user: User; isYou?: boolean; linkTo?: string }) {
  const { t } = useTranslation();
  return (
    <span className="min-w-0">
      <span className="flex flex-wrap items-center gap-2.5">
        {linkTo ? (
          <Link to={linkTo} className="text-[13.5px]">
            {user.display_name}
          </Link>
        ) : (
          <span className="text-[13.5px]">{user.display_name}</span>
        )}
        {isYou && <span className="eyebrow">{t("people.you")}</span>}
        <Badge tone={STATE_TONE[user.state]}>
          {t(`people.state.${user.state}`, { defaultValue: user.state })}
        </Badge>
      </span>
      <span className="mt-1 block font-mono text-[12px] text-faint">{user.email}</span>
      {user.state === "deactivated" && user.deactivated_at && (
        <span className="stamp mt-0.5 block">
          {t("people.closedOn", { when: formatInstant(user.deactivated_at) })}
        </span>
      )}
    </span>
  );
}

/**
 * A student's row. Removal asks twice: the first click only arms the confirmation, which states
 * the consequence in a sentence rather than trusting the verb on a button to carry it.
 *
 * `inCurrent` is what stops this offering a control that cannot work. The roll spans workspaces,
 * but suspend, restore and remove all act through `/users/{id}/…`, which is scoped to the
 * workspace the caller is in — on a student from another one the API answers 404. Join that
 * workspace to act on its people.
 */
function StudentActions({
  user,
  inCurrent,
  workspaces,
}: {
  user: User;
  inCurrent: boolean;
  workspaces: Workspace[];
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const remove = useRemoveStudent();
  const suspend = useSuspend();
  const restore = useRestore();

  // Moving is offered wherever the student is, because unlike the three acts below it names the
  // workspace explicitly instead of taking it from the caller's. It is refused for a student who
  // has started work, and the API says so in words this renders.
  const move = (
    <MoveStudent user={user} workspaces={workspaces.filter((w) => w.archived_at == null)} />
  );

  if (!inCurrent) {
    return (
      <span className="flex shrink-0 flex-col items-end gap-1.5">
        {move}
        <span className="stamp">{t("people.elsewhere")}</span>
      </span>
    );
  }

  const pending = remove.isPending || suspend.isPending || restore.isPending;
  const failure = remove.error ?? suspend.error ?? restore.error;

  if (user.state === "deactivated") {
    return (
      <span className="flex shrink-0 flex-col items-end gap-1.5">
        <button
          type="button"
          onClick={() => restore.mutate(user.id)}
          disabled={pending}
          className="btn-ghost"
        >
          {t("people.restore")}
        </button>
        <Failure error={failure} />
      </span>
    );
  }

  return (
    <span className="flex shrink-0 flex-col items-end gap-1.5">
      {confirming ? (
        <span className="notice-warn max-w-sm" data-testid={`confirm-${user.id}`}>
          <span className="block">{t("people.removeWarning", { name: user.display_name })}</span>
          <span className="mt-2.5 flex gap-2.5">
            <button
              type="button"
              onClick={() => remove.mutate(user.id, { onSuccess: () => setConfirming(false) })}
              disabled={pending}
              className="btn-primary py-1.5 text-[13px]"
            >
              {t("people.removeConfirm")}
            </button>
            <button type="button" onClick={() => setConfirming(false)} className="btn-ghost py-1.5">
              {t("common.cancel")}
            </button>
          </span>
        </span>
      ) : (
        <span className="flex flex-wrap items-center justify-end gap-2.5">
          {move}
          <button
            type="button"
            onClick={() => suspend.mutate(user.id)}
            disabled={pending}
            className="btn-ghost"
          >
            {t("people.suspend")}
          </button>
          <button type="button" onClick={() => setConfirming(true)} className="btn-ghost">
            {t("people.remove")}
          </button>
        </span>
      )}
      <Failure error={failure} />
    </span>
  );
}

/**
 * Moving a student is a select rather than a button because it needs a destination, and it is the
 * only control here that names a workspace instead of assuming the caller's.
 *
 * It is offered on every student the professor administers, including ones in another workspace,
 * and it fails for anybody who has started work — their project memberships and reports are pinned
 * to the workspace they were written in. The refusal is the API's own sentence.
 */
function MoveStudent({ user, workspaces }: { user: User; workspaces: Workspace[] }) {
  const { t } = useTranslation();
  const move = useMoveStudent();
  const elsewhere = workspaces.filter((workspace) => workspace.id !== user.workspace_id);

  if (elsewhere.length === 0) return null;

  return (
    <span className="flex items-center gap-1.5">
      <label className="sr-only" htmlFor={`move-${user.id}`}>
        {t("people.moveTo")}
      </label>
      <select
        id={`move-${user.id}`}
        className="select py-1 text-[13px]"
        value=""
        disabled={move.isPending}
        onChange={(event) =>
          event.target.value && move.mutate({ userId: user.id, workspaceId: event.target.value })
        }
      >
        <option value="">{t("people.moveTo")}</option>
        {elsewhere.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.name}
          </option>
        ))}
      </select>
      {move.variables?.userId === user.id && <Failure error={move.error} />}
    </span>
  );
}

/**
 * AUTH-01: enrolment is by invitation, and the token never reaches this screen — it goes to the
 * invited mailbox. So the confirmation names the address rather than offering a link to copy.
 *
 * The invitation names the workspace it enrols into, which is what gives every student one from
 * the moment they are invited. It is also the only moment: an enrolled account cannot change
 * workspace afterwards (ADR 0012), so this field is the decision, not a default to revisit.
 */
function InviteForm() {
  const { t } = useTranslation();
  const session = useSession();
  const workspaces = useWorkspaces();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<Role>("student");
  const [workspaceId, setWorkspaceId] = useState("");
  const invite = useInvite();

  // Only the ones that can still take an account: archived workspaces refuse invitations.
  const open = (workspaces.data ?? []).filter((workspace) => workspace.archived_at == null);
  const target = workspaceId || session.data?.workspace_id || "";

  return (
    <form
      className="panel mt-6 max-w-2xl p-4"
      onSubmit={(event) => {
        event.preventDefault();
        invite.mutate(
          { email, display_name: displayName || undefined, role, workspace_id: target },
          {
            onSuccess: () => {
              setEmail("");
              setDisplayName("");
            },
          },
        );
      }}
    >
      <h2 className="section-title">{t("people.invite")}</h2>
      <div className="mt-3 flex flex-wrap gap-4">
        <label className="block min-w-[15rem] flex-1">
          <span className="field-label">{t("people.email")}</span>
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="input font-mono"
          />
        </label>
        <label className="block min-w-[11rem] flex-1">
          <span className="field-label">{t("people.name")}</span>
          <input
            type="text"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            className="input"
          />
        </label>
        <label className="block">
          <span className="field-label">{t("people.role")}</span>
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
            className="select"
          >
            <option value="student">{t("people.roleStudent")}</option>
            <option value="prof">{t("people.roleProf")}</option>
          </select>
        </label>
        {open.length > 1 && (
          <label className="block">
            <span className="field-label">{t("people.workspace")}</span>
            <select
              value={target}
              onChange={(event) => setWorkspaceId(event.target.value)}
              className="select"
              data-testid="invite-workspace"
            >
              {open.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <p className="stamp mt-3">{t("people.roleNote")}</p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="submit" disabled={invite.isPending} className="btn-primary">
          {t("people.send")}
        </button>
        {invite.isSuccess && (
          <span role="status" className="text-[13px] text-muted-foreground">
            {t("people.sent", { email: invite.data.email })}
          </span>
        )}
        <Failure error={invite.error} />
      </div>
    </form>
  );
}
