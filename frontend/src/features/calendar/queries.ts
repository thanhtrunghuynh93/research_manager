import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { CalendarConfig, CalendarConfigIn } from "@/features/calendar/types";
import { periodsKey } from "@/features/report/queries";
import { DEFAULT_TIMEZONE } from "@/lib/dates";

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
 * The timezone every instant on screen is rendered in — the workspace's, not the viewer's.
 *
 * REP-01 computes every deadline in the workspace's zone, so that is the zone a deadline has to be
 * read in: a student travelling does not get a different Friday. `lib/dates` has always taken the
 * zone as an argument and has always defaulted it to Asia/Ho_Chi_Minh, and no caller passed one,
 * so a workspace configured for anywhere else displayed every time in Vietnam's.
 *
 * The calendar is the right source and not a second one: it is what the deadlines were computed
 * from, and `GET /calendar` answers for a student as well as a professor because everyone needs to
 * know when their report is due. Until it arrives — and in a workspace with no calendar yet — the
 * default stands.
 */
export function useTimezone(): string {
  const calendar = useCalendar();
  return calendar.data?.timezone ?? DEFAULT_TIMEZONE;
}

/**
 * Saving writes a new version, opens the coming weeks, re-dates the ones not yet begun, and derives
 * this week's obligations (REP-01) — so the weeks and the overview both change underneath it.
 */
export function useConfigureCalendar() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CalendarConfigIn) => api.put<CalendarConfig>("/api/v1/calendar", payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: calendarKey });
      void queryClient.invalidateQueries({ queryKey: periodsKey });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });
}
