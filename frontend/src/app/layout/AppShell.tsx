import { useTranslation } from "react-i18next";
import { Link, Outlet } from "react-router-dom";

import { useLogout, useSession } from "@/features/auth/queries";
import { setLanguage } from "@/lib/i18n";

export function AppShell() {
  const { t, i18n } = useTranslation();
  const session = useSession();
  const logout = useLogout();

  const user = session.data;
  const isProf = user?.role === "prof";

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border">
        <div className="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between gap-4">
          <Link to="/" className="font-semibold">
            {t("app.title")}
          </Link>
          <nav className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
            {/* Navigation mirrors the role guard: a professor-only page is never offered to a
                student, because a link that always fails is worse than no link. */}
            {isProf && <Link to="/overview">{t("overview.title")}</Link>}
            {isProf && <Link to="/assistant">{t("assistant.title")}</Link>}
            {user && !isProf && <Link to="/me">{t("me.title")}</Link>}
            {user && <Link to="/notifications">{t("notifications.title")}</Link>}
            {user && <Link to="/exports">{t("exports.title")}</Link>}
            <button
              type="button"
              onClick={() => setLanguage(i18n.language === "vi" ? "en" : "vi")}
              className="uppercase"
            >
              {i18n.language === "vi" ? "en" : "vi"}
            </button>
            {user && (
              <button type="button" onClick={() => logout.mutate()}>
                {t("auth.signOut")}
              </button>
            )}
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
