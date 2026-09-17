import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Invitation, Role, User, UserPage } from "@/features/people/types";

export const peopleKey = ["people"] as const;

/**
 * AUTH-01: the directory, a page at a time.
 *
 * The roll spans every workspace the professor belongs to, with no flag to ask for it: reads follow
 * membership (ADR 0016), so one predicate answers it. Each row carries its own `workspace_id`,
 * which is what the screen groups by.
 *
 * The cursor is followed rather than ignored. A roll longer than one page is ordinary — the API
 * caps a page at 200 — and a directory that silently stops at the first page is one where a
 * professor cannot find the student they came to remove.
 */
export function usePeople() {
  return useInfiniteQuery({
    queryKey: peopleKey,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api.get<UserPage>(
        `/api/v1/users?limit=100${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    getNextPageParam: (page) => page.next_cursor ?? null,
    select: (data) => ({
      users: data.pages.flatMap((page) => page.items),
    }),
  });
}

export function useInvite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      email: string;
      display_name?: string;
      role: Role;
      workspace_id?: string;
    }) => api.post<Invitation>("/api/v1/users/invitations", payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: peopleKey }),
  });
}

/**
 * Three acts on one account, kept apart because they mean different things (ADR 0011).
 *
 * `remove` ends every project membership and closes the account; it is what takes a student off
 * the roll, and it does not come back. `deactivate` only suspends the login, and `reactivate`
 * undoes it. Collapsing them into one "disable" button would hide that difference at exactly the
 * moment the professor is deciding between them.
 */
function useAccountAction(action: "remove" | "deactivate" | "reactivate") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => api.post<User>(`/api/v1/users/${userId}/${action}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: peopleKey }),
  });
}

export const useRemoveStudent = () => useAccountAction("remove");
export const useSuspend = () => useAccountAction("deactivate");
export const useRestore = () => useAccountAction("reactivate");

/**
 * Move a student to another workspace, which only works before they have done any work: their
 * project memberships and reports are pinned to the workspace they were written in, and the API
 * refuses rather than dragging them along. The whole cache is reset because the roll, and whatever
 * else the moved student appears in, are now different workspaces' data.
 */
export function useMoveStudent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, workspaceId }: { userId: string; workspaceId: string }) =>
      api.post<User>(`/api/v1/users/${userId}/workspace`, { workspace_id: workspaceId }),
    onSuccess: () => queryClient.resetQueries(),
  });
}
