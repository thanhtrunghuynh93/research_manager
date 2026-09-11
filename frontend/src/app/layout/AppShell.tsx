import { useTranslation } from "react-i18next";
import { Link, Outlet } from "react-router-dom";

import { useLogout, useSession } from "@/features/auth/queries";
import { setLanguage } from "@/lib/i18n";

export function AppShell() {
  const { t, i18n } = useTranslation();
  const session = useSession();
  const logout = useLogout();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border">
        <div className="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between gap-4">
          <Link to="/" className="font-semibold">
            {t("app.title")}
          </Link>
          <nav className="flex items-center gap-4 text-sm text-muted-foreground">
            {session.data && <Link to="/me">{t("me.title")}</Link>}
            <button
              type="button"
              onClick={() => setLanguage(i18n.language === "vi" ? "en" : "vi")}
              className="uppercase"
            >
              {i18n.language === "vi" ? "en" : "vi"}
            </button>
            {session.data && (
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
