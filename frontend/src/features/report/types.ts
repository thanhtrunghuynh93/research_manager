/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type Period = components["schemas"]["PeriodOut"];
export type Obligation = components["schemas"]["ObligationOut"];
export type Report = components["schemas"]["ReportOut"];
export type Version = components["schemas"]["VersionOut"];
export type Entry = components["schemas"]["EntryIn"];
export type Project = components["schemas"]["ProjectOut"];
