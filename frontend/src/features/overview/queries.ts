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
