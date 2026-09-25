/**
 * The weekly schedule: when a week runs, when the professor meets, and so when a report is due
 * (REP-01).
 *
 * It is the one manual step in the chain that makes a report due, and it used to be three: save a
 * calendar, then "open weeks", then derive who owes on the overview. Nobody could be expected to
 * know the second and third existed, and a workspace with five active projects stayed empty. Saving
 * now does all three on the server, so this card asks two questions and shows what they produce —
 * the next few weeks and their deadlines — rather than describing the mechanism.
 *
 * Saving writes a new calendar version. Weeks that have not begun take it; the week under way
 * keeps the deadline students are already working towards.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Failure } from "@/components/Failure";
import { useCalendar, useConfigureCalendar } from "@/features/calendar/queries";
import type { CalendarConfig } from "@/features/calendar/types";
import { usePeriods } from "@/features/report/queries";
import { useCurrentWorkspace } from "@/features/workspaces/queries";
import { DEFAULT_TIMEZONE, formatInstant, formatLocalDate, todayLocal } from "@/lib/dates";

const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6] as const;

/** Monday is 0, as the API counts. */
function weekdayOf(isoDate: string): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  return (new Date(Date.UTC(y!, m! - 1, d!)).getUTCDay() + 6) % 7;
}

function addDays(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(y!, m! - 1, d! + days)).toISOString().slice(0, 10);
}

/** The most recent `weekStart` on or before `today`: the start of the week `today` is in. */
function startOfWeek(today: string, weekStart: number): string {
  return addDays(today, -((weekdayOf(today) - weekStart + 7) % 7));
}

export function CalendarPanel() {
  const { t } = useTranslation();
  const calendar = useCalendar();
  const workspace = useCurrentWorkspace();
  const [editing, setEditing] = useState(false);

  if (calendar.isPending) return null;

  const timezone = calendar.data?.timezone ?? workspace?.timezone ?? DEFAULT_TIMEZONE;
  const current = calendar.data ?? null;
  const day = (n: number) => t(`calendar.weekday.${n}`);

  return (
    <section className="panel mt-6 p-4" data-testid="calendar-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="section-title">{t("calendar.title")}</h2>
        {current && !editing && (
          <button type="button" className="btn-quiet" onClick={() => setEditing(true)}>
            {t("calendar.edit")}
          </button>
        )}
      </div>

      {calendar.isError ? (
        <p className="mt-2">
          <Failure error={calendar.error} />
        </p>
      ) : current ? (
        <p className="mt-2 text-prose" data-testid="calendar-state">
          {t("calendar.summary", {
            start: day(current.week_start_weekday),
            end: day((current.week_start_weekday + 6) % 7),
            due: day((current.meeting_weekday + 6) % 7),
            meeting: day(current.meeting_weekday),
            timezone,
          })}
        </p>
      ) : (
        <p className="notice-warn mt-3" data-testid="calendar-state">
          {t("calendar.none")}
        </p>
      )}

      {current && !editing && <UpcomingWeeks timezone={timezone} />}

      {(!current || editing) && (
        <ScheduleForm
          current={current}
          timezone={timezone}
          onDone={() => setEditing(false)}
          onCancel={current ? () => setEditing(false) : undefined}
        />
      )}
    </section>
  );
}

/** What the schedule produces, which is easier to check than the rule that produces it. */
function UpcomingWeeks({ timezone }: { timezone: string }) {
  const { t } = useTranslation();
  const periods = usePeriods();
  const today = todayLocal(new Date(), timezone);
  const upcoming = (periods.data ?? []).filter((period) => period.local_end >= today).slice(0, 3);

  if (periods.isPending) return null;

  return (
    <div className="mt-4 border-t border-border pt-3">
      <p className="eyebrow">{t("calendar.upcoming")}</p>
      {upcoming.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">{t("calendar.noUpcoming")}</p>
      ) : (
        <ul className="mt-2" data-testid="upcoming-weeks">
          {upcoming.map((period) => (
            <li
              key={period.id}
              className="flex flex-wrap items-baseline justify-between gap-3 py-1 text-ui"
            >
              <span className="font-mono">
                {formatLocalDate(period.local_start)} – {formatLocalDate(period.local_end)}
                {period.local_start <= today && (
                  <span className="eyebrow ml-2.5">{t("calendar.thisWeek")}</span>
                )}
              </span>
              <span className="text-muted-foreground">
                {t("calendar.dueAt", { when: formatInstant(period.deadline_utc, timezone) })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ScheduleForm({
  current,
  timezone,
  onDone,
  onCancel,
}: {
  current: CalendarConfig | null;
  timezone: string;
  onDone: () => void;
  onCancel?: () => void;
}) {
  const { t } = useTranslation();
  const configure = useConfigureCalendar();
  const [weekStart, setWeekStart] = useState(current?.week_start_weekday ?? 0);
  const [meeting, setMeeting] = useState(current?.meeting_weekday ?? 0);
  const [grace, setGrace] = useState(current?.grace_minutes ?? 0);
  const [firstWeek, setFirstWeek] = useState<"this" | "next">("this");

  const today = todayLocal(new Date(), timezone);
  const thisWeek = startOfWeek(today, weekStart);
  const nextWeek = addDays(thisWeek, 7);
  // A first schedule starts on the week the professor picks. An edit applies from today, which
  // re-dates every week that has not begun and leaves the one under way alone.
  const effectiveFrom = current ? today : firstWeek === "this" ? thisWeek : nextWeek;

  const daySelect = (label: string, value: number, onChange: (next: number) => void) => (
    <label className="block">
      <span className="field-label">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="input"
      >
        {WEEKDAYS.map((day) => (
          <option key={day} value={day}>
            {t(`calendar.weekday.${day}`)}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <form
      className="mt-4 border-t border-border pt-4"
      onSubmit={(event) => {
        event.preventDefault();
        configure.mutate(
          {
            timezone,
            week_start_weekday: weekStart,
            meeting_weekday: meeting,
            grace_minutes: grace,
            effective_from: effectiveFrom,
          },
          { onSuccess: onDone },
        );
      }}
    >
      <div className="flex flex-wrap items-end gap-4">
        {daySelect(t("calendar.weekStart"), weekStart, setWeekStart)}
        {daySelect(t("calendar.meetingWeekday"), meeting, setMeeting)}
      </div>

      {!current && (
        <fieldset className="mt-4">
          <legend className="field-label">{t("calendar.firstWeek")}</legend>
          <div className="mt-1.5 flex flex-wrap gap-5 text-ui">
            {(
              [
                ["this", thisWeek],
                ["next", nextWeek],
              ] as const
            ).map(([choice, start]) => (
              <label key={choice} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="first-week"
                  checked={firstWeek === choice}
                  onChange={() => setFirstWeek(choice)}
                />
                {t(choice === "this" ? "calendar.firstThis" : "calendar.firstNext", {
                  start: formatLocalDate(start),
                })}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <details className="mt-4">
        <summary className="cursor-pointer text-ui text-muted-foreground">
          {t("calendar.advanced")}
        </summary>
        <label className="mt-2 block">
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
        <p className="stamp mt-1">{t("calendar.graceNote")}</p>
      </details>

      <p className="stamp mt-4">{current ? t("calendar.editNote") : t("calendar.firstNote")}</p>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="submit" disabled={configure.isPending} className="btn-primary">
          {t("calendar.save")}
        </button>
        {onCancel && (
          <button type="button" className="btn-quiet" onClick={onCancel}>
            {t("common.cancel")}
          </button>
        )}
      </div>
      <p className="mt-2">
        <Failure error={configure.error} />
      </p>
    </form>
  );
}
