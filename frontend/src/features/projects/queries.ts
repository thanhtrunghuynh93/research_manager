import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import { putWithProgress, sha256, type Sending, type UploadGrant } from "@/lib/upload";
import type {
  JoinableProject,
  MembershipIn,
  Milestone,
  Project,
  ProjectIn,
  ProjectMember,
  ProjectPage,
  ProjectPatch,
} from "@/features/projects/types";

export const projectKey = (id: string) => ["project", id] as const;

export function useProject(id: string | undefined) {
  return useQuery({
    queryKey: projectKey(id ?? ""),
    queryFn: () => api.get<Project>(`/api/v1/projects/${id}`),
    enabled: Boolean(id),
  });
}

/**
 * Everyone who has been on the project, past members included (PROJ-02, UI-03).
 *
 * `include_past` defaults to false on the route and no caller passed it, so PROJ-02's kept row was
 * in the database and on no screen: a student who left vanished from the project they had worked
 * on. The list renders `joined – left` for a closed membership already; it had nothing to render.
 */
export function useMembers(id: string | undefined, wanted = true) {
  return useQuery({
    queryKey: [...projectKey(id ?? ""), "members"],
    queryFn: () => api.get<ProjectMember[]>(`/api/v1/projects/${id}/members?include_past=true`),
    enabled: Boolean(id) && wanted,
  });
}

export function useMilestones(id: string | undefined, wanted = true) {
  return useQuery({
    queryKey: [...projectKey(id ?? ""), "milestones"],
    queryFn: () => api.get<Milestone[]>(`/api/v1/projects/${id}/milestones`),
    enabled: Boolean(id) && wanted,
  });
}

/** One attachment as the artifacts API returns it. */
export type ProjectDocument = {
  artifact_id: string;
  owner_student_id: string;
  project_id: string | null;
  period_id: string | null;
  entry_id: string | null;
  filename: string;
  byte_size: number;
  extraction_state: string;
  created_at: string;
};

export const projectDocumentsKey = (id: string) => [...projectKey(id), "documents"] as const;

/**
 * The documents that belong to the project rather than to a week (ADR 0018).
 *
 * `GET /artifacts?project_id=` answers with everything the caller may see for that project, which
 * for a student includes their own report evidence on it. The two are told apart by what they are
 * not attached to, so the filter is here as well as in the policy: a week's file carries a period,
 * a project document carries none.
 */
export function useProjectDocuments(id: string | undefined, wanted = true) {
  return useQuery({
    queryKey: projectDocumentsKey(id ?? ""),
    queryFn: async () => {
      const rows = await api.get<ProjectDocument[]>(`/api/v1/artifacts?project_id=${id}`);
      return rows.filter((row) => !row.period_id && !row.entry_id);
    },
    enabled: Boolean(id) && wanted,
  });
}

/**
 * Attach one file to a project: hash, PUT straight to the store, confirm (ADR 0018).
 *
 * A function rather than a mutation because both callers are outside React Query's idea of a
 * mutation — the panel drives its own progress state, and the create form runs it in a loop after
 * the project exists, since a file cannot be uploaded before there is a project to attach it to.
 * `period_id` is deliberately absent: sending one would file this under a week and make it
 * private to its uploader.
 */
export async function attachProjectDocument(
  projectId: string,
  file: File,
  onSending?: (sending: Sending) => void,
): Promise<void> {
  onSending?.({ name: file.name, stage: "checking", fraction: null });
  const checksum = await sha256(file);
  const grant = await api.post<UploadGrant>("/api/v1/artifacts/uploads", {
    project_id: projectId,
    filename: file.name,
    byte_size: file.size,
    sha256: checksum,
  });
  onSending?.({ name: file.name, stage: "sending", fraction: 0 });
  await putWithProgress(grant.url, grant.headers, file, (fraction) =>
    onSending?.({ name: file.name, stage: "sending", fraction }),
  );
  onSending?.({ name: file.name, stage: "recording", fraction: null });
  await api.post(`/api/v1/artifacts/${grant.artifact_id}/confirm`);
}

export function useRefreshProjectDocuments(id: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: projectDocumentsKey(id) });
  };
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
    queryFn: () => api.get<ProjectPage>(`/api/v1/projects${status ? `?status=${status}` : ""}`),
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
 * The one that matters most for a professor's project: it is created `proposed`, and an obligation
 * only derives from a membership whose project is `active`. Until this is called nothing a student
 * is assigned to can ever come due. A student's own project is already active when it is created.
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

export const joinableKey = ["projects", "joinable"] as const;

/** PROJ-07: the projects a professor has opened, which is a narrower read than the project. */
export function useJoinableProjects(enabled: boolean) {
  return useQuery({
    queryKey: joinableKey,
    queryFn: () => api.get<JoinableProject[]>("/api/v1/projects/joinable"),
    enabled,
  });
}

export function useJoinProject() {
  return useProjectWrite((id: string) =>
    api.post<ProjectMember>(`/api/v1/projects/${id}/join`, {}),
  );
}

/**
 * Leaving stops future weeks being owed; it does not clear an obligation already derived for this
 * one, which is the professor's to excuse. `obligationsKey` is invalidated because the student's
 * home is where that shows.
 */
export function useLeaveProject(projectId: string) {
  const queryClient = useQueryClient();
  const write = useProjectWrite(
    (membershipId: string) =>
      api.post<ProjectMember>(`/api/v1/projects/${projectId}/members/${membershipId}/end`, {}),
    projectId,
  );
  return {
    ...write,
    mutate: (membershipId: string) =>
      write.mutate(membershipId, {
        // The prefix, not one period: leaving changes what is owed for every week still open.
        onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["obligations"] }),
      }),
  };
}
