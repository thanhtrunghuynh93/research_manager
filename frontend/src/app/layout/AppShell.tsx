import { Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet } from "react-router-dom";

import { useLogout, useSession } from "@/features/auth/queries";
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
            <span className="font-display text-[1.55rem] font-medium tracking-[-0.01em]">
              {t("app.title")}
            </span>
            <span className="h-4 w-px bg-border" />
            <span className="eyebrow">{t("app.tagline")}</span>
          </Link>
          <div className="flex items-center gap-3">
            {/* Named, not just badged: the header is where you confirm whose workspace this is. */}
            {user && (
              <span className="text-[13px] text-muted-foreground" data-testid="greeting">
                {t("app.greeting", { name: user.display_name })}
              </span>
            )}
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
                className="rounded border border-border bg-surface px-2.5 py-1.5 text-[13px] text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
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
            <NavLink to="/assistant" className={item}>
              {t("assistant.title")}
            </NavLink>
          )}
          {user && !isProf && (
            <NavLink to="/me" className={item}>
              {t("me.title")}
            </NavLink>
          )}
          {user && (
            <NavLink to="/notifications" className={item}>
              {t("notifications.title")}
            </NavLink>
          )}
          {user && (
            <NavLink to="/exports" className={item}>
              {t("exports.title")}
            </NavLink>
          )}
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-7 py-8">
        <Outlet />
      </main>
    </div>
  );
}
