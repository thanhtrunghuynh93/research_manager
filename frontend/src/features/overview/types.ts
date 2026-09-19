/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type Overview = components["schemas"]["OverviewOut"];
export type Outstanding = components["schemas"]["Outstanding"];
/** UI-01: this week in one workspace — its period, and every report owed in it. */
export type WeekWorkspace = components["schemas"]["WeekWorkspace"];
export type WeekProject = components["schemas"]["WeekProject"];
export type WeekStudent = components["schemas"]["WeekStudent"];
