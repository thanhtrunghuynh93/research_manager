import { Navigate, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

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
  if (role && session.data.role !== role) return <Navigate to="/me" replace />;
  return <Outlet />;
}
