import { Navigate, Outlet, useLocation } from "react-router-dom";
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
  const location = useLocation();

  if (session.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (!session.data) return <Navigate to="/login" replace />;
  // To their own home, not a fixed one: a student-only page sending a professor to `/me` would
  // bounce them straight back here.
  //
  // `turnedAwayFrom` travels with the redirect so the home page can say what happened. Without it
  // a link into a page this role cannot open — the member names on /projects/:id point at
  // /students/:id, which is a professor's — silently swallowed the click and looked like the app
  // ignoring it.
  if (role && session.data.role !== role) {
    return (
      <Navigate
        to={homeFor(session.data.role)}
        replace
        state={{ turnedAwayFrom: location.pathname }}
      />
    );
  }
  return <Outlet />;
}
