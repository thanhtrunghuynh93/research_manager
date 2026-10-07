import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Assessment, TrendPoint } from "@/features/assessments/types";

export const assessmentKey = (id: string) => ["assessment", id] as const;
export const assessmentsKey = (filters: Record<string, string | undefined>) =>
  ["assessments", filters] as const;
export const trendKey = (studentId: string, projectId: string) =>
  ["trends", studentId, projectId] as const;

/**
 * The assessments the caller may see.
 *
 * For a student the policy already restricts this to their own, and only once a review has
 * approved them (ASSESS-08) — so a draft cannot appear here and the screen does not have to
 * filter. That is deliberate: a client-side filter would be a second place for the rule to live.
 */
export function useAssessments(filters: {
  studentId?: string;
  projectId?: string;
  periodId?: string;
}) {
  const query = new URLSearchParams();
  if (filters.studentId) query.set("student_id", filters.studentId);
  if (filters.projectId) query.set("project_id", filters.projectId);
  if (filters.periodId) query.set("period_id", filters.periodId);
  const suffix = query.toString();

  return useQuery({
    queryKey: assessmentsKey({
      student: filters.studentId,
      project: filters.projectId,
      period: filters.periodId,
    }),
    queryFn: () => api.get<Assessment[]>(`/api/v1/assessments${suffix ? `?${suffix}` : ""}`),
    enabled: Boolean(filters.studentId),
  });
}

export function useAssessment(id: string | undefined) {
  return useQuery({
    queryKey: assessmentKey(id ?? ""),
    queryFn: () => api.get<Assessment>(`/api/v1/assessments/${id}`),
    enabled: Boolean(id),
  });
}

export function useTrend(studentId: string | undefined, projectId: string | undefined) {
  return useQuery({
    queryKey: trendKey(studentId ?? "", projectId ?? ""),
    queryFn: () =>
      api.get<TrendPoint[]>(`/api/v1/trends?student_id=${studentId}&project_id=${projectId}`),
    enabled: Boolean(studentId && projectId),
  });
}
