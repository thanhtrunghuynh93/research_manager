/**
 * The API's own words for why a write was refused.
 *
 * Rendered rather than replaced with a generic message: the refusals a professor meets here are
 * specific and actionable — how many accounts still have to leave before a workspace can be
 * archived, or that an address already belongs to someone. A generic "something went wrong" would
 * throw away the only part worth reading.
 */
import { ApiError } from "@/api/client";

export function Failure({ error }: { error: unknown }) {
  if (!error) return null;
  const detail = error instanceof ApiError ? error.problem.detail || error.problem.title : null;
  return detail ? (
    <span role="alert" className="text-[12.5px] text-bad">
      {detail}
    </span>
  ) : null;
}
