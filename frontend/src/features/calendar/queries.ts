import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { CalendarConfig, CalendarConfigIn } from "@/features/calendar/types";
import { periodsKey } from "@/features/report/queries";
import type { Period } from "@/features/report/types";

export const calendarKey = ["calendar"] as const;

/**
 * The calendar version in force, or `null` when none has been configured.
 *
 * The null matters: without it the only signal is an empty period list, which stops being true the
 * moment a calendar is replaced after periods already exist.
 */
export function useCalendar() {
  return useQuery({
    queryKey: calendarKey,
    queryFn: () => api.get<CalendarConfig | null>("/api/v1/calendar"),
  });
}

/**
 * Configuring writes a *new version*; periods already open keep the deadline they were created
 * with (REP-01). Both keys are invalidated because the next `ensure` will use the new version.
 */
export function useConfigureCalendar() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CalendarConfigIn) =>
      api.put<CalendarConfig>("/api/v1/calendar", payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: calendarKey });
      void queryClient.invalidateQueries({ queryKey: periodsKey });
    },
  });
}

/**
 * Materialise the weeks up to a date. The nightly job does this too, so this is a "do it now"
 * button rather than the only path — a professor setting a workspace up should not have to wait
 * until tomorrow to see the first week open.
 */
export function useEnsurePeriods() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (through: string) =>
      api.post<Period[]>(`/api/v1/periods/ensure?through=${through}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: periodsKey }),
  });
}
