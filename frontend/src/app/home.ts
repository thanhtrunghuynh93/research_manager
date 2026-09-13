import type { Role } from "@/features/auth/types";

/**
 * Where an account belongs when no particular page was asked for.
 *
 * `/overview` is the professor overview (UI-01) and `/me` the student one (UI-02), so "home"
 * depends on the role. Sending everyone to `/me` put the professor on a student's screen: the
 * obligations list there is the whole workspace's — the endpoint answers "who owes a report this
 * period" — so it read as the professor's own backlog, one row per student with nothing but a
 * project title to tell them apart, above a "start this week" button the API answers 422.
 */
export function homeFor(role: Role): string {
  return role === "prof" ? "/overview" : "/me";
}
