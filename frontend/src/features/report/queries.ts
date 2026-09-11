import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, newIdempotencyKey } from "@/api/client";
import type { Entry, Obligation, Period, Project, Report, Version } from "@/features/report/types";

export const periodsKey = ["periods"] as const;
export const obligationsKey = (periodId: string) => ["obligations", periodId] as const;
export const reportKey = (periodId: string) => ["report", periodId] as const;
export const projectsKey = ["projects"] as const;

export function usePeriods() {
  return useQuery({ queryKey: periodsKey, queryFn: () => api.get<Period[]>("/api/v1/periods") });
}

export function useObligations(periodId: string | undefined) {
  return useQuery({
    queryKey: obligationsKey(periodId ?? ""),
    queryFn: () => api.get<Obligation[]>(`/api/v1/periods/${periodId}/obligations`),
    enabled: Boolean(periodId),
  });
}

export function useProjects() {
  return useQuery({
    queryKey: projectsKey,
    queryFn: () => api.get<{ items: Project[] }>("/api/v1/projects"),
  });
}

/** A student with no report yet gets a 404; that is "not started", not a failure. */
export function useReport(periodId: string | undefined) {
  return useQuery({
    queryKey: reportKey(periodId ?? ""),
    queryFn: async (): Promise<Report | null> => {
      try {
        return await api.get<Report>(`/api/v1/periods/${periodId}/report`);
      } catch (error) {
        if (error instanceof ApiError && error.problem.status === 404) return null;
        throw error;
      }
    },
    enabled: Boolean(periodId),
    retry: false,
  });
}

export function useSaveDraft(periodId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (content: Record<string, unknown>) =>
      api.patch<Report>(`/api/v1/periods/${periodId}/report/draft`, { content }),
    onSuccess: (report) => queryClient.setQueryData(reportKey(periodId), report),
  });
}

export function useSubmitReport(periodId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entries: Entry[]) =>
      api.post<Version>(
        `/api/v1/periods/${periodId}/report/submit`,
        { entries },
        // REP-05: a double click must not create a second version.
        { idempotencyKey: newIdempotencyKey() },
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: reportKey(periodId) }),
  });
}

/** The period covering today, or else the next one to open. */
export function currentPeriod(
  periods: Period[] | undefined,
  today = new Date(),
): Period | undefined {
  if (!periods?.length) return undefined;
  const iso = today.toISOString().slice(0, 10);
  return (
    periods.find((period) => period.local_start <= iso && iso <= period.local_end) ??
    periods.find((period) => period.local_start > iso) ??
    periods[periods.length - 1]
  );
}
