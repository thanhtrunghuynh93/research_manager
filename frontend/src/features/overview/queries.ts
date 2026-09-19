import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Overview } from "@/features/overview/types";

export const overviewKey = ["overview"] as const;

export function useOverview() {
  return useQuery({
    queryKey: overviewKey,
    queryFn: () => api.get<Overview>("/api/v1/overview"),
    // The week moves slowly; a stale count on a dashboard is worse than one extra request.
    staleTime: 30_000,
  });
}

/**
 * Derive this week's obligations now, rather than waiting for the nightly job.
 *
 * `ensure_periods` runs at 00:15 and derives obligations for every open period, so this is a
 * convenience — but an important one while a workspace is being set up: a professor who has just
 * assigned a student should not have to wait until tomorrow to see the week become due.
 */
export function useEnsureObligations() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (periodId: string) =>
      api.post<unknown>(`/api/v1/periods/${periodId}/obligations/ensure`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: overviewKey }),
  });
}

/**
 * Re-run one analysis that stopped short (AC-13).
 *
 * The endpoint has existed since the pipeline did, and nothing called it: the overview showed the
 * reason a run stalled and then left the professor to a terminal. AC-13 asks for a retry to be an
 * informed decision, which means the decision has to be reachable from where the information is.
 *
 * The run is identified by its subject rather than by its run id, because that is what re-running
 * means here — assess this student, on this project, for this week — and the endpoint re-resolves
 * all three through the caller's own scope before it spends anything (AUTH-02).
 */
export function useRetryAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (subject: { student_id: string; project_id: string; period_id: string }) =>
      api.post<unknown>(
        `/api/v1/admin/assessments/retry?student_id=${subject.student_id}` +
          `&project_id=${subject.project_id}&period_id=${subject.period_id}`,
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: overviewKey }),
  });
}
