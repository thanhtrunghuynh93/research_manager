/**
 * The reporting calendar, and the weeks it opens (REP-01).
 *
 * This is the first thing a workspace needs and the only genuinely manual step in the chain that
 * makes a report due: periods and obligations derive from it nightly. It lives on `/workspaces`
 * rather than on a route of its own because a calendar is a workspace setting — its timezone
 * default is the workspace's — and because one more screen for one more form is how a professor
 * ends up with six places to look.
 *
 * Configuring writes a *new version*. Periods already open keep the deadline they were created
 * with, which is the one thing about this form that surprises people, so the panel says it rather
 * than leaving it to be discovered.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Failure } from "@/components/Failure";
import { useCalendar, useConfigureCalendar, useEnsurePeriods } from "@/features/calendar/queries";
import { usePeriods } from "@/features/report/queries";
import { useCurrentWorkspace } from "@/features/workspaces/queries";
import { formatLocalDate, todayLocal } from "@/lib/dates";

const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6] as const;

export function CalendarPanel() {
  const { t } = useTranslation();
  const calendar = useCalendar();
  const workspace = useCurrentWorkspace();

  if (calendar.isPending) return null;
  if (calendar.isError)
    return (
      <section className="panel mt-8 max-w-2xl p-4">
        <h2 className="section-title">{t("calendar.title")}</h2>
        <p className="mt-2">
          <Failure error={calendar.error} />
        </p>
      </section>
    );

  return (
    <section className="panel mt-8 max-w-2xl p-4" data-testid="calendar-panel">
      <h2 className="section-title">{t("calendar.title")}</h2>
      <p className="stamp mt-1">{t("calendar.intro")}</p>

      <p className="mt-3 text-sm" data-testid="calendar-state">
        {calendar.data
          ? t("calendar.configured", {
              timezone: calendar.data.timezone,
              meeting: t(`calendar.weekday.${calendar.data.meeting_weekday}`),
              start: t(`calendar.weekday.${calendar.data.week_start_weekday}`),
              version: calendar.data.version,
            })
          : t("calendar.none")}
      </p>

      <CalendarForm defaultTimezone={workspace?.timezone ?? "Asia/Ho_Chi_Minh"} />
      <Periods configured={Boolean(calendar.data)} />
    </section>
  );
}

function CalendarForm({ defaultTimezone }: { defaultTimezone: string }) {
  const { t } = useTranslation();
  const calendar = useCalendar();
  const configure = useConfigureCalendar();
  const current = calendar.data;

  const [timezone, setTimezone] = useState(current?.timezone ?? defaultTimezone);
  const [meetingWeekday, setMeetingWeekday] = useState(current?.meeting_weekday ?? 0);
  const [weekStart, setWeekStart] = useState(current?.week_start_weekday ?? 0);
  const [grace, setGrace] = useState(current?.grace_minutes ?? 0);
  const [effectiveFrom, setEffectiveFrom] = useState(todayLocal());

  return (
    <form
      className="mt-4 border-t border-border pt-4"
      onSubmit={(event) => {
        event.preventDefault();
        configure.mutate({
          timezone,
          meeting_weekday: meetingWeekday,
          week_start_weekday: weekStart,
          grace_minutes: grace,
          effective_from: effectiveFrom,
        });
      }}
    >
      <div className="flex flex-wrap items-end gap-4">
        <label className="block min-w-[12rem] flex-1">
          <span className="field-label">{t("calendar.timezone")}</span>
          <input
            type="text"
            required
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
            className="input"
          />
        </label>
        <label className="block">
          <span className="field-label">{t("calendar.meetingWeekday")}</span>
          <select
            aria-label={t("calendar.meetingWeekday")}
            value={meetingWeekday}
            onChange={(event) => setMeetingWeekday(Number(event.target.value))}
            className="input"
          >
            {WEEKDAYS.map((day) => (
              <option key={day} value={day}>
                {t(`calendar.weekday.${day}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="field-label">{t("calendar.weekStart")}</span>
          <select
            aria-label={t("calendar.weekStart")}
            value={weekStart}
            onChange={(event) => setWeekStart(Number(event.target.value))}
            className="input"
          >
            {WEEKDAYS.map((day) => (
              <option key={day} value={day}>
                {t(`calendar.weekday.${day}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="field-label">{t("calendar.grace")}</span>
          <input
            type="number"
            min={0}
            max={1440}
            value={grace}
            onChange={(event) => setGrace(Number(event.target.value))}
            className="input w-28"
          />
        </label>
        <label className="block">
          <span className="field-label">{t("calendar.effectiveFrom")}</span>
          <input
            type="date"
            required
            value={effectiveFrom}
            onChange={(event) => setEffectiveFrom(event.target.value)}
            className="input"
          />
        </label>
        <button type="submit" disabled={configure.isPending} className="btn-primary">
          {t("calendar.save")}
        </button>
      </div>

      <p className="stamp mt-3">{t("calendar.versionNote")}</p>
      {configure.isSuccess ? (
        <p className="stamp mt-1" role="status">
          {t("calendar.saved", { version: configure.data?.version })}
        </p>
      ) : null}
      <p className="mt-2">
        <Failure error={configure.error} />
      </p>
    </form>
  );
}

/** Opening weeks is a "do it now": the nightly job materialises them anyway. */
function Periods({ configured }: { configured: boolean }) {
  const { t } = useTranslation();
  const periods = usePeriods();
  const ensure = useEnsurePeriods();
  const [through, setThrough] = useState(todayLocal(addWeeks(new Date(), 8)));

  const opened = periods.data ?? [];
  const last = opened.at(-1);

  return (
    <div className="mt-5 border-t border-border pt-4">
      <p className="text-sm" data-testid="period-state">
        {opened.length
          ? t("calendar.periods", {
              count: opened.length,
              through: formatLocalDate(last!.local_end),
            })
          : t("calendar.noPeriods")}
      </p>

      <div className="mt-3 flex flex-wrap items-end gap-4">
        <label className="block">
          <span className="field-label">{t("calendar.openThrough")}</span>
          <input
            type="date"
            value={through}
            onChange={(event) => setThrough(event.target.value)}
            className="input"
          />
        </label>
        <button
          type="button"
          disabled={!configured || ensure.isPending}
          onClick={() => ensure.mutate(through)}
          className="btn-ghost"
        >
          {t("calendar.open")}
        </button>
      </div>

      <p className="stamp mt-3">{t("calendar.autoNote")}</p>
      <p className="mt-2">
        <Failure error={ensure.error} />
      </p>
    </div>
  );
}

function addWeeks(from: Date, weeks: number): Date {
  const to = new Date(from);
  to.setDate(to.getDate() + weeks * 7);
  return to;
}
