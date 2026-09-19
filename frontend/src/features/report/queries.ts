import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { api, ApiError, newIdempotencyKey } from "@/api/client";
import type {
  Artifact,
  Entry,
  Obligation,
  Period,
  Project,
  Report,
  Version,
} from "@/features/report/types";
import { todayLocal } from "@/lib/dates";

export const periodsKey = ["periods"] as const;
export const obligationsKey = (periodId: string) => ["obligations", periodId] as const;
export const reportKey = (periodId: string) => ["report", periodId] as const;
export const projectsKey = ["projects"] as const;
export const artifactsKey = (scope: Record<string, string | undefined>) =>
  ["artifacts", scope] as const;

export function usePeriods() {
  return useQuery({ queryKey: periodsKey, queryFn: () => api.get<Period[]>("/api/v1/periods") });
}

export function useObligations(periodId: string | undefined) {
  return useQuery({
    queryKey: obligationsKey(periodId ?? ""),
    queryFn: () => api.get<Obligation[]>(`/api/v1/periods/${periodId}/obligations`),
    enabled: Boolean(periodId),
  });
}

export function useProjects() {
  return useQuery({
    queryKey: projectsKey,
    queryFn: () => api.get<{ items: Project[] }>("/api/v1/projects"),
  });
}

/** A student with no report yet gets a 404; that is "not started", not a failure. */
export function useReport(periodId: string | undefined) {
  return useQuery({
    queryKey: reportKey(periodId ?? ""),
    queryFn: async (): Promise<Report | null> => {
      try {
        return await api.get<Report>(`/api/v1/periods/${periodId}/report`);
      } catch (error) {
        if (error instanceof ApiError && error.problem.status === 404) return null;
        throw error;
      }
    },
    enabled: Boolean(periodId),
    retry: false,
  });
}

/**
 * One submitted version, so the editor can show what was sent rather than an empty form.
 *
 * A report carries a `draft_content` and a `current_version_id`, and the two can disagree: a
 * submission made without an autosaved draft — the seed does this — leaves the draft empty over a
 * version with content. Reading only the draft meant reopening such a week showed blank boxes, and
 * submitting them wrote that blankness over the record.
 */
export function useVersion(versionId: string | null | undefined) {
  return useQuery({
    queryKey: ["report-version", versionId ?? ""] as const,
    queryFn: () => api.get<Version>(`/api/v1/report-versions/${versionId}`),
    enabled: Boolean(versionId),
    // Versions are immutable, so there is never a reason to ask twice.
    staleTime: Infinity,
    // The editor waits for this before seeding its fields; a version it cannot read should not
    // hold the form shut while a retry runs. Failing once falls back to the draft.
    retry: false,
  });
}

export function useSaveDraft(periodId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (content: Record<string, unknown>) =>
      api.patch<Report>(`/api/v1/periods/${periodId}/report/draft`, { content }),
    onSuccess: (report) => queryClient.setQueryData(reportKey(periodId), report),
  });
}

export function useSubmitReport(periodId: string) {
  const queryClient = useQueryClient();
  // REP-05: a double click, or a retry of a request whose response was lost, must not create a
  // second version. The key therefore identifies the *attempt*, so it has to be minted outside
  // mutationFn — inside it, every retry got a fresh key and the server saw a new submission.
  // Lazily: `useRef(newIdempotencyKey())` would mint a key on every render and throw the
  // rest away — and it is what turned an unavailable crypto API into a render-time crash.
  const key = useRef<string>();
  key.current ??= newIdempotencyKey();
  return useMutation({
    mutationFn: (entries: Entry[]) =>
      api.post<Version>(
        `/api/v1/periods/${periodId}/report/submit`,
        { entries },
        { idempotencyKey: key.current },
      ),
    onSuccess: () => {
      // The next submission is a new version on purpose, so it needs a key of its own.
      key.current = newIdempotencyKey();
      void queryClient.invalidateQueries({ queryKey: reportKey(periodId) });
    },
  });
}

/** The period covering today, or else the next one to open. */
export function currentPeriod(
  periods: Period[] | undefined,
  today = new Date(),
  timeZone?: string,
): Period | undefined {
  if (!periods?.length) return undefined;
  // The workspace's date, not UTC's: `local_start`/`local_end` are workspace-local calendar
  // dates, so comparing them against `toISOString()` showed last week as "this week" for the
  // first seven hours of every day in a UTC+7 workspace — including a "Start this week" link
  // pointing at the previous period.
  const iso = todayLocal(today, timeZone);
  return (
    periods.find((period) => period.local_start <= iso && iso <= period.local_end) ??
    periods.find((period) => period.local_start > iso) ??
    periods[periods.length - 1]
  );
}

/**
 * The attachments on one entry, read back from the server (REP-04).
 *
 * They used to live in component state, which meant they existed only for as long as the tab did:
 * a reload showed an empty list over files that were sitting in the bucket, and the professor —
 * who never did the upload — had no way to see them at all.
 */
export function useArtifacts(
  filters: { periodId?: string; projectId?: string; studentId?: string },
  /**
   * Whether anything is reading these files right now — true once the week has been submitted.
   *
   * The text is read when the report is submitted, not as each file arrives, so before that a
   * `pending` version stays pending however long anyone watches it. Polling was unconditional and
   * therefore never stopped: a student who attached a file and left the tab open asked the server
   * for the same unchanged list every three seconds until they closed it.
   */
  reading = false,
) {
  const params = new URLSearchParams();
  if (filters.periodId) params.set("period_id", filters.periodId);
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.studentId) params.set("student_id", filters.studentId);
  const query = params.toString();
  return useQuery({
    queryKey: artifactsKey({ ...filters }),
    queryFn: () => api.get<Artifact[]>(`/api/v1/artifacts?${query}`),
    enabled: Boolean(query),
    // Submission queues the reading, so from then on a pending version does become `ok` a few
    // seconds later and the badge has a reason to change.
    refetchInterval: (query) =>
      reading && (query.state.data ?? []).some((one) => one.extraction_state === "pending")
        ? 3000
        : false,
  });
}

/**
 * Open one attachment.
 *
 * The download endpoint answers with a short-lived URL, not with the file, so a plain link to it
 * navigated the reader to a page of JSON. The grant is fetched first and then followed.
 */
export async function openArtifact(artifactId: string): Promise<void> {
  const grant = await api.get<{ url: string }>(`/api/v1/artifacts/${artifactId}/download`);
  window.location.assign(grant.url);
}
