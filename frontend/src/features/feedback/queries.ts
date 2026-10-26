import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Feedback, FeedbackDownload, FeedbackListPage } from "@/features/feedback/types";

export const feedbackKey = ["feedback"] as const;

/** The feedback the caller may read, newest first: a student's is only what was published to them. */
export function useFeedbackPages() {
  return useInfiniteQuery({
    queryKey: [...feedbackKey, "pages"],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "50" });
      if (pageParam) params.set("cursor", pageParam);
      return api.get<FeedbackListPage>(`/api/v1/feedback?${params.toString()}`);
    },
    getNextPageParam: (page) => page.next_cursor ?? null,
    select: (data) => ({ items: data.pages.flatMap((page) => page.items) }),
  });
}

export function useFeedback(id: string | undefined) {
  return useQuery({
    queryKey: [...feedbackKey, id],
    queryFn: () => api.get<Feedback>(`/api/v1/feedback/${id}`),
    enabled: Boolean(id),
    retry: false,
  });
}

/** Asks for a short-lived link, then sends the browser to it. The store forces a download. */
export function useDownloadAttachment() {
  return useMutation({
    mutationFn: (attachmentId: string) =>
      api.get<FeedbackDownload>(`/api/v1/feedback/attachments/${attachmentId}/download`),
    onSuccess: (download) => window.location.assign(download.url),
  });
}
