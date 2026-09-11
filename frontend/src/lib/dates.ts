/**
 * Dates are stored in UTC and displayed in the workspace timezone (requirements REP-01).
 * The workspace timezone arrives with the session; until then Asia/Ho_Chi_Minh is the default.
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

export function formatLocalDate(isoDate: string, locale = "en"): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(new Date(Date.UTC(y!, m! - 1, d!)));
}
