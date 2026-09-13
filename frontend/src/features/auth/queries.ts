import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "@/api/client";
import type { User } from "@/features/auth/types";

export const sessionKey = ["session"] as const;

/**
 * The signed-in user, or null when there is no session.
 * A 401 is the normal answer for an anonymous visitor, not an error to retry.
 */
export function useSession() {
  return useQuery({
    queryKey: sessionKey,
    queryFn: async (): Promise<User | null> => {
      try {
        return await api.get<User>("/api/v1/auth/me");
      } catch (error) {
        if (error instanceof ApiError && error.problem.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

/**
 * Hand the app to a different user: drop everything the previous one could read, and publish who
 * is here now.
 *
 * Removed, not invalidated: invalidation marks cached data stale but leaves it readable, so on a
 * shared machine the next person to sign in saw the previous user's overview, projects and
 * notifications until each refetch landed (AUTH-03).
 *
 * The session query is exempted from that sweep rather than removed and written back. Removing a
 * query that components are already observing orphans one of those observers — it is dropped from
 * the cache entry and never rebinds to the one `setQueryData` builds next, so it keeps rendering
 * the old value until the page is reloaded. AppShell and RequireAuth both observe this query, and
 * AppShell subscribes first: signing in left the header with nothing but the title and the
 * language toggle, and signing out left the guarded page on screen.
 */
function handOver(queryClient: QueryClient, user: User | null): void {
  queryClient.setQueryData(sessionKey, user);
  queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== sessionKey[0] });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { email: string; password: string }) =>
      api.post<User>("/api/v1/auth/login", credentials),
    onSuccess: (user) => handOver(queryClient, user),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/api/v1/auth/logout"),
    onSuccess: () => handOver(queryClient, null),
  });
}
