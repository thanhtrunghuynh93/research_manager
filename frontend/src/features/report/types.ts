/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type Period = components["schemas"]["PeriodOut"];
export type Obligation = components["schemas"]["ObligationOut"];
export type Report = components["schemas"]["ReportOut"];
export type Version = components["schemas"]["VersionOut"];
export type VersionSummary = components["schemas"]["VersionSummaryOut"];
export type RevisionRequest = components["schemas"]["RevisionRequestOut"];
export type EntryOut = components["schemas"]["EntryOut"];
export type Entry = components["schemas"]["EntryIn"];
export type Project = components["schemas"]["ProjectOut"];
export type Artifact = components["schemas"]["ArtifactOut"];
