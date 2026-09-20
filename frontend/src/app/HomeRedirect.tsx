import { Navigate, useLocation } from "react-router-dom";

import { homeFor } from "@/app/home";
import { useSession } from "@/features/auth/queries";

/** Lands "/" and any unknown path on the home that belongs to this account's role. */
export function HomeRedirect() {
  const session = useSession();
  const location = useLocation();
  if (!session.data) return <Navigate to="/login" replace />;
  // "/" is where the logo points, so arriving there is not being turned away from anything; any
  // other path is, and the shell says so rather than leaving the click unexplained.
  const turnedAwayFrom = location.pathname === "/" ? undefined : location.pathname;
  return <Navigate to={homeFor(session.data.role)} replace state={{ turnedAwayFrom }} />;
}
