import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type {
  Decision,
  MembershipIn,
  Milestone,
  Project,
  ProjectIn,
  ProjectMember,
  ProjectPage,
  ProjectPatch,
  ProjectProgress,
} from "@/features/projects/types";

export const projectKey = (id: string) => ["project", id] as const;

export function useProject(id: string | undefined) {
  return useQuery({
    queryKey: projectKey(id ?? ""),
    queryFn: () => api.get<Project>(`/api/v1/projects/${id}`),
    enabled: Boolean(id),
  });
}

export function useMembers(id: string | undefined) {
  return useQuery({
    queryKey: [...projectKey(id ?? ""), "members"],
    queryFn: () => api.get<ProjectMember[]>(`/api/v1/projects/${id}/members`),
    enabled: Boolean(id),
  });
}

export function useMilestones(id: string | undefined) {
  return useQuery({
    queryKey: [...projectKey(id ?? ""), "milestones"],
    queryFn: () => api.get<Milestone[]>(`/api/v1/projects/${id}/milestones`),
    enabled: Boolean(id),
  });
}

export function useDecisions(id: string | undefined) {
  return useQuery({
    queryKey: [...projectKey(id ?? ""), "decisions"],
    queryFn: () => api.get<Decision[]>(`/api/v1/projects/${id}/decisions`),
    enabled: Boolean(id),
  });
}

export function useProgress(id: string | undefined) {
  return useQuery({
    queryKey: [...projectKey(id ?? ""), "progress"],
    queryFn: () => api.get<ProjectProgress>(`/api/v1/projects/${id}/progress`),
    enabled: Boolean(id),
  });
}

export const projectsListKey = (status?: string) => ["projects", "list", status ?? "all"] as const;

/**
 * The project list, which is what finally gives `/projects/:id` a way in: until it existed the
 * screen was reachable only by typing a UUID or following an assistant citation.
 *
 * `GET /projects` is signed-in rather than professor-only, so a student sees the projects they are
 * on. The create form on the page is what is gated, not the list.
 */
export function useProjectList(status?: string) {
  return useQuery({
    queryKey: projectsListKey(status),
    queryFn: () =>
      api.get<ProjectPage>(`/api/v1/projects${status ? `?status=${status}` : ""}`),
  });
}

/**
 * Every project write invalidates the `["projects"]` prefix rather than a single key, because the
 * same records are read under three of them: this feature's list and detail, and `report/queries`'
 * own `projectsKey`, which the weekly editor uses to title its tabs.
 */
function useProjectWrite<TArgs, TResult>(
  mutationFn: (args: TArgs) => Promise<TResult>,
  projectId?: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      if (projectId) void queryClient.invalidateQueries({ queryKey: projectKey(projectId) });
    },
  });
}

export function useCreateProject() {
  return useProjectWrite((payload: ProjectIn) => api.post<Project>("/api/v1/projects", payload));
}

/**
 * The one that matters most: a project is created `proposed`, and an obligation only derives from
 * a membership whose project is `active`. Until this is called nothing a student is assigned to
 * can ever come due.
 */
export function useUpdateProject(id: string) {
  return useProjectWrite(
    (payload: ProjectPatch) => api.patch<Project>(`/api/v1/projects/${id}`, payload),
    id,
  );
}

export function useAddMember(id: string) {
  return useProjectWrite(
    (payload: MembershipIn) => api.post<ProjectMember>(`/api/v1/projects/${id}/members`, payload),
    id,
  );
}
