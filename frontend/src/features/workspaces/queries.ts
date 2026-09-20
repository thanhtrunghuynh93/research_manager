import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import { useSession } from "@/features/auth/queries";
import type { components } from "@/api/generated/schema";
import type { Workspace } from "@/features/workspaces/types";

export const workspacesKey = ["workspaces"] as const;

/**
 * The workspaces this professor can move between, and the one they are in.
 *
 * Keyed off the account rather than anything session-shaped: joining moves the account, so the
 * workspace they came from has to stay on the list or there would be no way back to it.
 */
export function useWorkspaces({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: workspacesKey,
    queryFn: () => api.get<Workspace[]>("/api/v1/workspaces"),
    enabled,
  });
}

/**
 * The workspace every screen is currently showing.
 *
 * A professor moves between workspaces, so "whose people am I looking at" stopped being obvious
 * the moment joining landed. Only professors ask: `GET /workspaces` is professor-only, and a
 * student has one workspace and no way to leave it.
 */
export function useCurrentWorkspace() {
  const session = useSession();
  const isProf = session.data?.role === "prof";
  const workspaces = useWorkspaces({ enabled: isProf });
  return workspaces.data?.find((workspace) => workspace.id === session.data?.workspace_id);
}

/**
 * Joining and leaving both move the account, so everything the app holds is about to be a
 * different workspace's data. The whole cache is discarded rather than a few keys invalidated:
 * anything left would render the previous workspace's rows under this one's name.
 */
function useMove(path: (id: string) => string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Workspace>(path(id)),
    onSuccess: () => queryClient.resetQueries(),
  });
}

export const useJoinWorkspace = () => useMove((id) => `/api/v1/workspaces/${id}/join`);
export const useLeaveWorkspace = () => useMove((id) => `/api/v1/workspaces/${id}/leave`);

/** Creating joins it, which is a move, so this resets the cache for the same reason. */
export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; timezone?: string }) =>
      api.post<Workspace>("/api/v1/workspaces", payload),
    onSuccess: () => queryClient.resetQueries(),
  });
}

export function useRenameWorkspace(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string }) =>
      api.patch<Workspace>(`/api/v1/workspaces/${id}`, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: workspacesKey }),
  });
}

/**
 * Archiving is refused while any account is still in the workspace, and the API says how many.
 * People move too, so the roll is discarded alongside the list.
 */
export function useArchiveWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Workspace>(`/api/v1/workspaces/${id}/archive`),
    onSuccess: () => queryClient.resetQueries(),
  });
}

export const budgetsKey = ["ai-budgets"] as const;
export const usageKey = ["ai-usage"] as const;

type AiBudgets = components["schemas"]["AiBudgetsOut"];
type AiUsage = components["schemas"]["AiUsageOut"];

/**
 * The monthly ceiling on model spend (requirements §11).
 *
 * `spent_usd` here is the month's real spend whether or not a ceiling is set. It used to be taken
 * from `check_budget`, which only totals spend when there is a limit to compare it against — so
 * the professor's overview reported $0 precisely when nothing was capping the bill.
 */
export function useAiBudgets() {
  return useQuery({
    queryKey: budgetsKey,
    queryFn: () => api.get<AiBudgets>("/api/v1/admin/ai/budgets"),
  });
}

export function useAiUsage() {
  return useQuery({
    queryKey: usageKey,
    queryFn: () => api.get<AiUsage>("/api/v1/admin/ai/usage"),
  });
}

export function useSetAiBudget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      monthly_usd: string | null;
      project_monthly_usd: Record<string, string>;
    }) => api.put<AiBudgets>("/api/v1/admin/ai/budgets", payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: budgetsKey });
      // The overview prints the same numbers; a ceiling set here must not leave it stale.
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });
}
