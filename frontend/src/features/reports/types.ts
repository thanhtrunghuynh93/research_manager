/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type ReportListItem = components["schemas"]["ReportListItemOut"];
export type ReportListPage = components["schemas"]["Page_ReportListItemOut_"];
export type ReportState = components["schemas"]["ReportState"];

/** The states a submitted report can be in; a draft is never listed. */
export const LISTED_STATES: ReportState[] = [
  "submitted",
  "resubmitted",
  "revision_requested",
  "reviewed",
];

export type ReportFilters = {
  periodId?: string;
  studentId?: string;
  projectId?: string;
  state?: string;
  needsReview?: boolean;
};
