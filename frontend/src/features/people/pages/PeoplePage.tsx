/**
 * AUTH-01: the roll — who is in this workspace, and the three acts a professor has over them.
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

import { ApiError } from "@/api/client";
import { Badge } from "@/components/evidence/Badges";
import { useSession } from "@/features/auth/queries";
import {
  useInvite,
  usePeople,
  useRemoveStudent,
  useRestore,
  useSuspend,
} from "@/features/people/queries";
import type { Role, User } from "@/features/people/types";
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

  const users = people.data?.users ?? [];
  const professors = users.filter((user) => user.role === "prof");
  const students = users.filter((user) => user.role === "student");

  return (
    <section className="animate-rise-in">
      <header>
        <p className="eyebrow mb-1.5">{t("people.label")}</p>
        <h1 className="page-title">{t("people.title")}</h1>
        <p className="mt-2 max-w-2xl text-[13.5px] text-muted-foreground">{t("people.intro")}</p>
      </header>

      <InviteForm />

      <h2 className="section-title mt-8">{t("people.professors")}</h2>
      <ul className="panel mt-2.5" data-testid="professors">
        {professors.map((user) => (
          <li key={user.id} className="row">
            <Person user={user} isYou={user.id === session.data?.id} />
          </li>
        ))}
        {professors.length === 0 && <Empty>{t("people.noProfessors")}</Empty>}
      </ul>

      <h2 className="section-title mt-8">{t("people.students")}</h2>
      <ul className="panel mt-2.5" data-testid="students">
        {students.map((user) => (
          <li key={user.id} className="row items-start">
            <Person user={user} linkTo={`/students/${user.id}`} />
            <StudentActions user={user} />
          </li>
        ))}
        {students.length === 0 && <Empty>{t("people.noStudents")}</Empty>}
      </ul>

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
 */
function StudentActions({ user }: { user: User }) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const remove = useRemoveStudent();
  const suspend = useSuspend();
  const restore = useRestore();

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
        <span className="flex gap-2.5">
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

function Failure({ error }: { error: unknown }) {
  if (!error) return null;
  const detail = error instanceof ApiError ? error.problem.detail || error.problem.title : null;
  return detail ? (
    <span role="alert" className="text-[12.5px] text-bad">
      {detail}
    </span>
  ) : null;
}

/**
 * AUTH-01: enrolment is by invitation, and the token never reaches this screen — it goes to the
 * invited mailbox. So the confirmation names the address rather than offering a link to copy.
 */
function InviteForm() {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<Role>("student");
  const invite = useInvite();

  return (
    <form
      className="panel mt-6 max-w-2xl p-4"
      onSubmit={(event) => {
        event.preventDefault();
        invite.mutate(
          { email, display_name: displayName || undefined, role },
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
