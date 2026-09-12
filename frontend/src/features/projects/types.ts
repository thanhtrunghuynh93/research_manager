/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type Project = components["schemas"]["ProjectOut"];
export type ProjectMember = components["schemas"]["MembershipOut"];
export type Milestone = components["schemas"]["MilestoneOut"];
export type Decision = components["schemas"]["ResearchDecisionOut"];
export type ProjectProgress = components["schemas"]["ProjectProgressOut"];
