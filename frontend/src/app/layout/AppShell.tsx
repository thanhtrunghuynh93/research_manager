import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useLogout, useSession } from "@/features/auth/queries";
import { WorkspaceSwitcher } from "@/features/workspaces/components/WorkspaceSwitcher";
import { useTheme } from "@/hooks/useTheme";

/** The active item carries a rule, not a fill: this is a document, and the reader is on a page. */
const item = ({ isActive }: { isActive: boolean }) =>
  [
    "border-b-2 px-3 pb-2.5 pt-2 text-sm transition-colors",
    isActive
      ? "border-foreground text-foreground"
      : "border-transparent text-faint hover:text-foreground",
  ].join(" ");

export function AppShell() {
  const { t } = useTranslation();
  const session = useSession();
  const logout = useLogout();
  const { theme, toggle } = useTheme();

  const user = session.data;
  const isProf = user?.role === "prof";

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-7 py-3.5">
          <Link to="/" className="flex items-center gap-3 text-foreground no-underline">
            {/* The wordmark is the one place the product says its own name, so it is set apart
                from the page titles below it rather than matching them: Newsreader at its lightest
                with the letters opened up, which is the name's own idea. The negative tracking the
                titles use pulls words together, and this one wants the opposite. */}
            <span className="font-display text-display-sm font-light tracking-[0.06em]">
              {t("app.title")}
            </span>
          </Link>
          <div className="flex min-w-0 items-center gap-3">
            {/* Named, not just badged: the header is where you confirm whose workspace this is. */}
            {user && (
              <span
                className="whitespace-nowrap text-ui text-muted-foreground"
                data-testid="greeting"
              >
                {t("app.greeting", { name: user.display_name })}
              </span>
            )}
            {/* Every screen below is one workspace's, and a professor moves between them, so
                this is the one place that says which — and, since they may belong to several,
                the place to change it. The roll, the overview and the assistant all change
                underneath it. */}
            <WorkspaceSwitcher />
            <button
              type="button"
              onClick={toggle}
              aria-label={t(theme === "dark" ? "app.toLight" : "app.toDark")}
              title={t(theme === "dark" ? "app.toLight" : "app.toDark")}
              data-testid="theme-toggle"
              className="rounded border border-border bg-surface p-1.5 text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
            >
              {theme === "dark" ? (
                <Sun className="h-4 w-4" aria-hidden />
              ) : (
                <Moon className="h-4 w-4" aria-hidden />
              )}
            </button>
            {user && (
              <button
                type="button"
                onClick={() => logout.mutate()}
                className="whitespace-nowrap rounded border border-border bg-surface px-2.5 py-1.5 text-ui text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
              >
                {t("auth.signOut")}
              </button>
            )}
          </div>
        </div>
        <nav className="mx-auto flex max-w-6xl flex-wrap gap-1 px-7">
          {/* Navigation mirrors the role guard: a professor-only page is never offered to a
              student, because a link that always fails is worse than no link. */}
          {isProf && (
            <NavLink to="/overview" className={item}>
              {t("overview.title")}
            </NavLink>
          )}
          {isProf && (
            <NavLink to="/people" className={item}>
              {t("people.title")}
            </NavLink>
          )}
          {isProf && (
            <NavLink to="/projects" className={item}>
              {t("projects.title")}
            </NavLink>
          )}
          {isProf && (
            <NavLink to="/workspaces" className={item}>
              {t("workspaces.title")}
            </NavLink>
          )}
          {isProf && (
            <NavLink to="/assistant" className={item}>
              {t("assistant.title")}
            </NavLink>
          )}
          {user && !isProf && (
            <NavLink to="/me" className={item} end>
              {t("me.title")}
            </NavLink>
          )}
          {/* Listed per role rather than once for both: since PROJ-07 a student has something to
              do here too, but the two menus order it differently — a student's week comes before
              the projects it is about, and a professor's projects sit with the other records. */}
          {user && !isProf && (
            <NavLink to="/projects" className={item}>
              {t("projects.title")}
            </NavLink>
          )}
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-7 py-8">
        <TurnedAwayNotice />
        <Outlet />
      </main>
    </div>
  );
}

/**
 * Why you are looking at your own home rather than the page you clicked.
 *
 * Both the role guard and the catch-all *redirect* rather than refuse, which is the right
 * behaviour — a dead end is worse — but it left the click unexplained. One link inside the app
 * already does this: the member names on `/projects/:id` point at `/students/:id`, and either role
 * may open the page they are on.
 */
function TurnedAwayNotice() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const arriving = (location.state as { turnedAwayFrom?: string } | null)?.turnedAwayFrom;
  // Which path the message belongs to, so moving anywhere else clears it — and a snapshot, so
  // that consuming the history state below does not erase the message along with it.
  const [shown, setShown] = useState<{ at: string; from: string } | null>(null);

  useEffect(() => {
    if (arriving) {
      setShown({ at: location.pathname, from: arriving });
      // Consumed rather than kept. It lived in the history entry, so a reader who pressed reload
      // on their own home was told again about a link they had followed long before — and again
      // on every reload after that, because nothing ever cleared it.
      navigate(location.pathname, { replace: true, state: null });
    } else {
      setShown((current) => (current?.at === location.pathname ? current : null));
    }
  }, [arriving, location.pathname, navigate]);

  if (!shown) return null;
  return (
    <p className="panel mb-6 px-4 py-2.5 text-sm text-muted-foreground" role="status">
      {t("app.turnedAway", { path: shown.from })}
    </p>
  );
}
