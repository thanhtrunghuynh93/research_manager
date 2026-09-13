import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type {
  Decision,
  Milestone,
  Project,
  ProjectMember,
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
