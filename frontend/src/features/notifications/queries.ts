import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Notification, Preference } from "@/features/notifications/types";

export const notificationsKey = ["notifications"] as const;
export const preferencesKey = ["notifications", "preferences"] as const;

export function useNotifications(unreadOnly = false) {
  return useQuery({
    queryKey: [...notificationsKey, unreadOnly],
    queryFn: () =>
      api.get<Notification[]>(`/api/v1/notifications?unread_only=${String(unreadOnly)}`),
  });
}

export function usePreferences() {
  return useQuery({
    queryKey: preferencesKey,
    queryFn: () => api.get<Preference[]>("/api/v1/notifications/preferences"),
  });
}

export function useMarkRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Notification>(`/api/v1/notifications/${id}/read`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: notificationsKey }),
  });
}

/**
 * UI-07: the critical categories cannot be muted, and the API refuses. The UI hides the control
 * for those rather than offering a button that fails.
 */
export function useMute() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ kind, muted }: { kind: string; muted: boolean }) => {
      if (muted) {
        await api.post<Preference>("/api/v1/notifications/preferences/mute", { kind });
      } else {
        await api.post<void>("/api/v1/notifications/preferences/unmute", { kind });
      }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: preferencesKey }),
  });
}
