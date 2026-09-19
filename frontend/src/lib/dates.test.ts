/**
 * Dates cross a timezone boundary twice: stored in UTC, lived in by a workspace. Both directions
 * were wrong in the same direction, and both showed a plausible date rather than an error.
 */
import { describe, expect, test } from "vitest";

import {
  formatInstant,
  formatLocalDate,
  formatTimeOfDay,
  localDateToInstant,
  todayLocal,
} from "@/lib/dates";

describe("a workspace-local calendar date", () => {
  test("renders as itself, whatever timezone the viewer is in", () => {
    // It was built as a UTC instant and formatted in the browser's zone, so every such date read
    // a day early for any viewer west of UTC.
    expect(formatLocalDate("2026-09-14")).toContain("14");
    expect(formatLocalDate("2026-01-01")).toContain("2026");
    expect(formatLocalDate("2026-01-01")).toContain("01");
  });
});

describe("today, where the workspace is", () => {
  test("is the workspace's date, not UTC's", () => {
    // 2026-09-21 06:00 in Asia/Ho_Chi_Minh is still the 20th in UTC. Comparing the UTC answer
    // against workspace-local period bounds showed last week as "this week" until 07:00 daily.
    const early = new Date("2026-09-20T23:00:00Z");

    expect(todayLocal(early, "Asia/Ho_Chi_Minh")).toBe("2026-09-21");
    expect(todayLocal(early, "UTC")).toBe("2026-09-20");
  });

  test("is ISO-shaped, so it compares with a plain date", () => {
    expect(todayLocal(new Date("2026-09-05T05:00:00Z"), "Asia/Ho_Chi_Minh")).toBe("2026-09-05");
  });
});

describe("a calendar date turned into an instant", () => {
  test("starts and ends the day in the workspace, not in UTC", () => {
    // `${date}T00:00:00Z` moved an export window seven hours: records filed before 07:00 on the
    // first day went missing and seven hours of the following day came along.
    expect(localDateToInstant("2026-09-14", "start", "Asia/Ho_Chi_Minh")).toBe(
      "2026-09-13T17:00:00.000Z",
    );
    expect(localDateToInstant("2026-09-20", "end", "Asia/Ho_Chi_Minh")).toBe(
      "2026-09-20T16:59:59.999Z",
    );
  });

  test("is the plain reading in UTC", () => {
    expect(localDateToInstant("2026-09-14", "start", "UTC")).toBe("2026-09-14T00:00:00.000Z");
  });

  test("handles a zone with a half-hour offset", () => {
    expect(localDateToInstant("2026-09-14", "start", "Asia/Kolkata")).toBe(
      "2026-09-13T18:30:00.000Z",
    );
  });
});

describe("an instant", () => {
  test("is rendered in the workspace's zone, not the viewer's", () => {
    // Every call site took the default, so a workspace configured for anywhere else still read
    // its deadlines in Vietnam's clock.
    expect(formatInstant("2026-09-20T16:59:00Z", "Asia/Ho_Chi_Minh")).toContain("23:59");
    expect(formatInstant("2026-09-20T16:59:00Z", "Europe/Berlin")).toContain("18:59");
  });

  test("shows its clock time in that same zone, and says which zone", () => {
    // The autosave stamp used `toLocaleTimeString`, which answers in the viewer's zone — so it
    // sat on the same line as the deadline in a different clock. Naming the zone is what makes
    // the two comparable to a reader who is in neither.
    const at = new Date("2026-09-20T16:59:00Z");

    expect(formatTimeOfDay(at, "Asia/Ho_Chi_Minh")).toBe("23:59:00 GMT+7");
    expect(formatTimeOfDay(at, "UTC")).toBe("16:59:00 UTC");
  });
});
