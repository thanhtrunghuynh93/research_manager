import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Answer, Conversation } from "@/features/assistant/types";

export const conversationsKey = ["assistant", "conversations"] as const;

export function useConversations() {
  return useQuery({
    queryKey: conversationsKey,
    queryFn: () => api.get<Conversation[]>("/api/v1/assistant/conversations"),
  });
}

export function useAsk() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      question: string;
      conversation_id?: string | null;
      student_id?: string | null;
      project_id?: string | null;
      as_of?: string | null;
    }) => api.post<Answer>("/api/v1/assistant/ask", payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationsKey }),
  });
}
