import { Navigate, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { homeFor } from "@/app/home";
import { useSession } from "@/features/auth/queries";
import type { Role } from "@/features/auth/types";

/**
 * Route guard. The API enforces every permission itself (AUTH-02); this only keeps the UI from
 * showing a page the caller cannot load.
 */
export function RequireAuth({ role }: { role?: Role }) {
  const { t } = useTranslation();
  const session = useSession();

  if (session.isPending) return <p className="text-muted-foreground">{t("common.loading")}</p>;
  if (!session.data) return <Navigate to="/login" replace />;
  // To their own home, not a fixed one: a student-only page sending a professor to `/me` would
  // bounce them straight back here.
  if (role && session.data.role !== role) {
    return <Navigate to={homeFor(session.data.role)} replace />;
  }
  return <Outlet />;
}
