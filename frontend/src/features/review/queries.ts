import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { api, newIdempotencyKey } from "@/api/client";
import { overviewKey } from "@/features/overview/queries";
import type { Assessment, Review, SnapshotItem } from "@/features/review/types";

export const assessmentKey = (id: string) => ["assessment", id] as const;
export const evidenceKey = (id: string) => ["assessment", id, "evidence"] as const;

export function useAssessment(id: string | undefined) {
  return useQuery({
    queryKey: assessmentKey(id ?? ""),
    queryFn: () => api.get<Assessment>(`/api/v1/assessments/${id}`),
    enabled: Boolean(id),
  });
}

export function useAssessmentEvidence(id: string | undefined) {
  return useQuery({
    queryKey: evidenceKey(id ?? ""),
    queryFn: () => api.get<SnapshotItem[]>(`/api/v1/assessments/${id}/evidence`),
    enabled: Boolean(id),
  });
}

/**
 * ASSESS-08: an override requires a recorded reason, and the API refuses one without it. The form
 * enforces the same rule so the professor learns it before losing their edit, not after.
 */
export function useApprove(id: string) {
  const queryClient = useQueryClient();
  // Minted per attempt rather than per call, so a retry is the same approval. Inside mutationFn
  // each retry carried a new key, which is exactly what the header exists to prevent.
  const key = useRef(newIdempotencyKey());
  return useMutation({
    mutationFn: (payload: { override?: Record<string, unknown> | null; rationale?: string }) =>
      api.post<Review>(`/api/v1/assessments/${id}/approve`, payload, {
        idempotencyKey: key.current,
      }),
    onSuccess: () => {
      key.current = newIdempotencyKey();
      void queryClient.invalidateQueries({ queryKey: assessmentKey(id) });
      void queryClient.invalidateQueries({ queryKey: overviewKey });
    },
  });
}
