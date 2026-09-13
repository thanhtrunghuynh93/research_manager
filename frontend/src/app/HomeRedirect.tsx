import { Navigate } from "react-router-dom";

import { homeFor } from "@/app/home";
import { useSession } from "@/features/auth/queries";

/** Lands "/" and any unknown path on the home that belongs to this account's role. */
export function HomeRedirect() {
  const session = useSession();
  if (!session.data) return <Navigate to="/login" replace />;
  return <Navigate to={homeFor(session.data.role)} replace />;
}
