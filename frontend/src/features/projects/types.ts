/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type Project = components["schemas"]["ProjectOut"];
export type ProjectMember = components["schemas"]["MembershipOut"];
export type Decision = components["schemas"]["ResearchDecisionOut"];
export type ProjectIn = components["schemas"]["ProjectIn"];
export type ProjectPatch = components["schemas"]["ProjectPatch"];
export type MembershipIn = components["schemas"]["MembershipIn"];
export type JoinableProject = components["schemas"]["JoinableProjectOut"];
export type ProjectPage = components["schemas"]["Page_ProjectOut_"];
export type ResearchStage = components["schemas"]["ResearchStage"];
export type ProjectStatus = components["schemas"]["ProjectStatus"];

/** The stages a new project can be started in, in the order the research moves through them. */
export const STAGES: ResearchStage[] = [
  "literature_review",
  "theory",
  "data_preparation",
  "implementation",
  "experimentation",
  "analysis",
  "writing",
];

export const STATUSES: ProjectStatus[] = ["proposed", "active", "paused", "completed", "archived"];
