/**
 * Dates are stored in UTC and displayed in the workspace timezone (requirements REP-01).
 *
 * That zone comes from `useTimezone`, which reads the reporting calendar in force — the same
 * configuration the deadlines were computed from. It is passed in rather than read here so these
 * stay pure functions. The default below applies only until the calendar arrives, and in a
 * workspace that has none; every call site used to take it, which meant a workspace configured
 * for anywhere else still displayed every time in Vietnam's.
 *
 * Two kinds of value, and they are not interchangeable:
 *
 *   - an *instant* (`deadline_utc`, `created_at`) is a moment, rendered in the workspace's zone;
 *   - a *plain date* (`local_start`, `joined_on`) is already a workspace-local calendar date and
 *     names no moment at all. Turning one into a `Date` and letting the browser format it shifts
 *     it by the viewer's offset, which showed every such date a day early west of UTC.
 *
 * `todayLocal` is the counterpart for the other direction: "what day is it, where the workspace
 * is", which is what a plain date must be compared against. `new Date().toISOString()` answers
 * for UTC instead, so between midnight and 07:00 in Asia/Ho_Chi_Minh it named the day before.
 */

export const DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh";

export function formatInstant(iso: string, timeZone = DEFAULT_TIMEZONE, locale = "en"): string {
  return new Intl.DateTimeFormat(locale, {
    timeZone,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    // A deadline reads as 23:59, the way the requirement states it, in either language.
    hourCycle: "h23",
    timeZoneName: "short",
  }).format(new Date(iso));
}

/**
 * The clock time of an instant, in the workspace's zone — for a stamp sitting beside a deadline.
 *
 * `toLocaleTimeString()` answers in the *viewer's* zone, which put the autosave time and the
 * deadline next to each other on the same line in two different clocks. The zone is named for the
 * same reason the deadline names it: two unlabelled clocks on one line are only reassuring while
 * the reader is in the workspace's zone.
 */
export function formatTimeOfDay(at: Date, timeZone = DEFAULT_TIMEZONE, locale = "en"): string {
  return new Intl.DateTimeFormat(locale, {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
    timeZoneName: "short",
  }).format(at);
}

/**
 * Render a workspace-local calendar date. Formatted from its parts, with no instant in between,
 * so the viewer's own timezone cannot move it.
 */
export function formatLocalDate(isoDate: string, locale = "en"): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(new Date(Date.UTC(y!, m! - 1, d!)));
}

/** Today's date in the workspace timezone, as `YYYY-MM-DD` — comparable with a plain date. */
export function todayLocal(at = new Date(), timeZone: string = DEFAULT_TIMEZONE): string {
  // "en-CA" is ISO-shaped, which is what makes the string comparison below meaningful.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(at);
}

/**
 * Turn a workspace-local calendar date into the instant that day begins or ends there.
 *
 * A `<input type="date">` yields a plain date. Stamping it with `Z` treats it as UTC, which in a
 * UTC+7 workspace moved an export window seven hours: everything filed before 07:00 on the first
 * day was missing, and seven hours of the day after the last one were included.
 */
export function localDateToInstant(
  isoDate: string,
  edge: "start" | "end",
  timeZone = DEFAULT_TIMEZONE,
): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const wall = Date.UTC(
    y!,
    m! - 1,
    d!,
    ...(edge === "start" ? ([0, 0, 0, 0] as const) : ([23, 59, 59, 999] as const)),
  );
  // The zone's offset at that moment, found by asking how the instant reads there.
  return new Date(wall - offsetMs(new Date(wall), timeZone)).toISOString();
}

function offsetMs(at: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(at);
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  const asUtc = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour") % 24,
    get("minute"),
    get("second"),
  );
  // formatToParts has no milliseconds, so compare against the same instant with its own
  // stripped — otherwise the "offset" absorbs them and the result drifts by up to a second.
  return asUtc - (at.getTime() - at.getUTCMilliseconds());
}
