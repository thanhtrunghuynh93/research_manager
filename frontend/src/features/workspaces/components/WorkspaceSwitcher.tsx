/**
 * Which workspace every screen below is showing, and the way to another one.
 *
 * Switching *is* joining a workspace you already belong to (ADR 0015): the membership is already
 * there, so the call moves the anchor and nothing else. It sits in the header rather than on
 * `/workspaces` because it is not an administrative act — it is the frame every other screen is
 * read in, and having to leave the roll you were reading in order to change whose roll it is made
 * the frame feel like a setting. `/workspaces` keeps what is genuinely administration: creating,
 * leaving, archiving, the calendar and the budget.
 *
 * A professor with one membership gets the name and no menu, because one choice is not a choice.
 */
import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { Failure } from "@/components/Failure";
import { useSession } from "@/features/auth/queries";
import {
  useCurrentWorkspace,
  useJoinWorkspace,
  useWorkspaces,
} from "@/features/workspaces/queries";
import type { Workspace } from "@/features/workspaces/types";

/**
 * The name, faded at the cap rather than cut against the border. Not `truncate`: the ellipsis is
 * computed from a frozen width and misfires in screenshot and PDF renderers, clipping names that
 * fit.
 *
 * The `pr-3.5` is what the fade eats when the name is short — without it the gradient takes the
 * last characters of every name, and "QA Lab Three" arrived half-transparent.
 */
function Name({ children }: { children: string }) {
  return (
    <span
      className="min-w-0 overflow-hidden whitespace-nowrap pr-3.5"
      style={{
        maskImage: "linear-gradient(to right, #000 calc(100% - 14px), transparent)",
        WebkitMaskImage: "linear-gradient(to right, #000 calc(100% - 14px), transparent)",
      }}
    >
      {children}
    </span>
  );
}

const shell =
  "inline-flex min-w-0 max-w-48 items-center gap-1.5 rounded-md border border-border-strong " +
  "bg-raised py-[5px] pl-2.5 pr-2 text-xs font-semibold text-foreground";

export function WorkspaceSwitcher() {
  const { t } = useTranslation();
  const session = useSession();
  const isProf = session.data?.role === "prof";
  const workspaces = useWorkspaces({ enabled: isProf });
  const current = useCurrentWorkspace();
  const join = useJoinWorkspace();
  const navigate = useNavigate();

  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  // Closing on an outside press rather than on blur: blur fires before the click lands on an
  // item, which closed the menu and swallowed the choice.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  if (!current) return null;

  // The one being worked in always belongs to you, whatever the list says about it.
  const mine = (workspaces.data ?? []).filter(
    (workspace) => workspace.joined || workspace.id === current.id,
  );

  if (mine.length < 2) {
    return (
      <span className={shell} data-testid="current-workspace" title={current.name}>
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
        <Name>{current.name}</Name>
      </span>
    );
  }

  const choose = (workspace: Workspace) => {
    if (workspace.id === current.id) {
      setOpen(false);
      return;
    }
    // The cache is reset by the mutation, so every screen below re-reads under the new workspace.
    // Then the overview, rather than wherever you were: a record page names a record of the
    // workspace you just left — `/projects/:id`, `/students/:id`, `/review/:id` — and staying put
    // would turn a switch into a redirect and a message about a page your account cannot open.
    // The overview is the one screen that is true of whichever workspace you land in.
    join.mutate(workspace.id, {
      onSuccess: () => {
        setOpen(false);
        navigate("/overview");
      },
    });
  };

  /** Roving focus, so the menu is usable without a pointer. */
  const onMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const items = Array.from(
      container.current?.querySelectorAll<HTMLElement>("[data-menu-item]") ?? [],
    );
    const at = items.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "ArrowDown" ? at + 1 : at - 1;
    items[(next + items.length) % items.length]?.focus();
  };

  return (
    <div
      className="relative"
      ref={container}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          setOpen(false);
          trigger.current?.focus();
        }
      }}
    >
      <button
        type="button"
        ref={trigger}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={t("workspaces.switch")}
        title={current.name}
        data-testid="current-workspace"
        onClick={() => setOpen((was) => !was)}
        className={`${shell} transition-colors hover:border-foreground`}
      >
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
        <Name>{current.name}</Name>
        <ChevronDown className="-ml-2 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={t("workspaces.switch")}
          data-testid="workspace-switcher-menu"
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 z-20 mt-1.5 w-64 rounded-md border border-border-strong bg-surface py-1 shadow-lg"
        >
          {mine.map((workspace) => {
            const here = workspace.id === current.id;
            return (
              <button
                key={workspace.id}
                type="button"
                role="menuitemradio"
                aria-checked={here}
                data-menu-item
                disabled={join.isPending}
                title={workspace.name}
                onClick={() => choose(workspace)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-ui text-foreground transition-colors hover:bg-raised disabled:opacity-60"
              >
                <Check
                  className={`h-3.5 w-3.5 shrink-0 ${here ? "text-primary" : "invisible"}`}
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate">{workspace.name}</span>
                <span className="shrink-0 font-mono text-meta text-faint">
                  {workspace.timezone}
                </span>
              </button>
            );
          })}
          {join.isError && (
            <div className="px-3 py-1.5">
              <Failure error={join.error} />
            </div>
          )}
          <div className="mt-1 border-t border-border pt-1">
            <Link
              to="/workspaces"
              role="menuitem"
              data-menu-item
              onClick={() => setOpen(false)}
              className="block px-3 py-2 text-ui text-muted-foreground no-underline transition-colors hover:bg-raised hover:text-foreground"
            >
              {t("workspaces.manage")}
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
