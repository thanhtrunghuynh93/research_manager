import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { ReportFilters, ReportListPage } from "@/features/reports/types";

/** Every list of submitted reports hangs off this prefix, so one invalidation reaches them all. */
export const reportsKey = ["reports"] as const;

function reportsUrl(filters: ReportFilters, limit: number, cursor?: string | null): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (filters.periodId) params.set("period_id", filters.periodId);
  if (filters.studentId) params.set("student_id", filters.studentId);
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.state) params.set("state", filters.state);
  if (filters.needsReview) params.set("needs_review", "true");
  if (cursor) params.set("cursor", cursor);
  return `/api/v1/reports?${params.toString()}`;
}

/** Submitted reports a page at a time, newest week first, for the professor's list (UI-01). */
export function useReportPages(filters: ReportFilters) {
  return useInfiniteQuery({
    queryKey: [...reportsKey, "pages", filters],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => api.get<ReportListPage>(reportsUrl(filters, 50, pageParam)),
    getNextPageParam: (page) => page.next_cursor ?? null,
    select: (data) => ({ items: data.pages.flatMap((page) => page.items) }),
  });
}

/**
 * The newest submitted reports, one page, for a list of recent weeks.
 *
 * Twenty rather than eight: a report is one per student and week, but a week the calendar opened
 * ahead can carry one too, and those sort first — so eight could leave a recent week unmatched.
 */
export function useRecentReports(filters: ReportFilters, enabled = true) {
  return useQuery({
    queryKey: [...reportsKey, "recent", filters],
    queryFn: () => api.get<ReportListPage>(reportsUrl(filters, 20)),
    enabled,
  });
}
