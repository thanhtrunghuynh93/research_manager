import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { email: string; password: string }) =>
      api.post<User>("/api/v1/auth/login", credentials),
    onSuccess: (user) => {
      queryClient.setQueryData(sessionKey, user);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/api/v1/auth/logout"),
    onSuccess: () => {
      queryClient.setQueryData(sessionKey, null);
      void queryClient.invalidateQueries();
    },
  });
}
