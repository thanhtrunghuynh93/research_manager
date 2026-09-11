import { Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

export function AppShell() {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border">
        <div className="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between">
          <span className="font-semibold">{t("app.title")}</span>
          <nav className="text-sm text-muted-foreground">{/* navigation lands with identity */}</nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
