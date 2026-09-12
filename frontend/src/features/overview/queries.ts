import { useQuery } from "@tanstack/react-query";

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
