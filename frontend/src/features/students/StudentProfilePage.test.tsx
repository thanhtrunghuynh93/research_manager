/**
 * UI-04: the professor reading what a student actually handed in.
 *
 * The assessments are about the work; the materials are the work. Until artifacts could be listed,
 * the only place an artifact id ever appeared was the response to the upload that created it, so
 * there was no route from a student to their files at all (REP-04, AC-02).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { StudentProfilePage } from "@/features/students/pages/StudentProfilePage";
import "@/lib/i18n";
import { server } from "@/test/setup";

function artifact(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: "a1",
    owner_student_id: "s1",
    project_id: "pr1",
    period_id: "p1",
    entry_id: null,
    kind: "upload",
    filename: "week3.pptx",
    supported_claim: "the deck behind the recall number",
    source_url: null,
    version_no: 1,
    byte_size: 33797,
    content_type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    extraction_state: "ok",
    extraction_note: "",
    uploaded: true,
    created_at: "2026-09-15T02:00:00Z",
    ...overrides,
  };
}

/** The account the page is about. It carries the workspace the weekly list is narrowed to. */
function user(overrides: Record<string, unknown> = {}) {
  return {
    id: "s1",
    workspace_id: "w1",
    display_name: "Bao Tran",
    email: "bao@example.com",
    role: "student",
    state: "active",
    created_at: "2026-01-01T00:00:00Z",
    deactivated_at: null,
    ...overrides,
  };
}

function renderProfile(rows: unknown[]) {
  server.use(
    http.get("/api/v1/assessments", () => HttpResponse.json([])),
    http.get("/api/v1/artifacts", () => HttpResponse.json(rows)),
    // The page has always read this — it is where the student's name comes from — and the weekly
    // list now reads the workspace off it too, so leaving it unhandled no longer merely costs a
    // heading.
    http.get("/api/v1/users/s1", () => HttpResponse.json(user())),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/students/s1"]}>
        <Routes>
          <Route path="/students/:id" element={<StudentProfilePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("lists every file the student attached, whatever its format", async () => {
  renderProfile([
    artifact(),
    artifact({ artifact_id: "a2", filename: "report.docx" }),
    artifact({ artifact_id: "a3", filename: "summary.html" }),
    artifact({ artifact_id: "a4", filename: "notes.md" }),
  ]);

  // The list element is on screen before its contents are, so wait for a row rather than the list.
  await screen.findByText("week3.pptx");
  const materials = screen.getByTestId("materials");

  for (const name of ["week3.pptx", "report.docx", "summary.html", "notes.md"]) {
    expect(within(materials).getByText(name)).toBeInTheDocument();
  }
});

test("shows what the student said each file supports", async () => {
  renderProfile([artifact()]);

  expect(await screen.findByText(/the deck behind the recall number/)).toBeInTheDocument();
});

test("says plainly when a file was stored but could not be read", async () => {
  // ASSESS-06: unreadable and empty are different, and the professor is the one who acts on it.
  renderProfile([artifact({ extraction_state: "failed" })]);

  expect(await screen.findByText(/Could not be read/)).toBeInTheDocument();
});

test("downloading follows the short-lived grant rather than the endpoint that issues it", async () => {
  // The download endpoint answers with JSON, so a plain link took the reader to a page of it.
  const assign = vi.fn();
  Object.defineProperty(window, "location", {
    value: { ...window.location, assign },
    writable: true,
  });
  server.use(
    http.get("/api/v1/artifacts/a1/download", () =>
      HttpResponse.json({ url: "https://objects.example/signed/week3.pptx", expires_in: 300 }),
    ),
  );
  renderProfile([artifact()]);

  await userEvent.click(await screen.findByRole("button", { name: /Download/i }));

  await waitFor(() =>
    expect(assign).toHaveBeenCalledWith("https://objects.example/signed/week3.pptx"),
  );
});

test("an empty profile says so rather than showing nothing", async () => {
  renderProfile([]);

  expect(await screen.findByText(/has not attached anything yet/)).toBeInTheDocument();
});

// ---------------------------------------------------------------- weeks that have happened
//
// The calendar materialises periods ahead of time, eight weeks out by default. The list took the
// newest eight, which were therefore the eight that had not begun — a column of empty weeks
// running into next month, each offering to open a report that cannot exist, with every week the
// student had actually reported pushed below the cut.

/** A period starting `offsetDays` from today, in the shape the API returns. */
function period(id: string, offsetDays: number) {
  const start = new Date();
  start.setDate(start.getDate() + offsetDays);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return {
    id,
    workspace_id: "w1",
    local_start: iso(start),
    local_end: iso(end),
    start_utc: `${iso(start)}T00:00:00Z`,
    end_utc: `${iso(end)}T23:59:00Z`,
    meeting_date: iso(end),
    deadline_utc: `${iso(end)}T16:59:00Z`,
    reminder_due_utc: `${iso(end)}T17:00:00Z`,
  };
}

test("the weekly list holds the weeks that have begun, not the ones the calendar has opened", async () => {
  server.use(
    http.get("/api/v1/periods", () =>
      HttpResponse.json([period("past", -28), period("current", -1), period("future", 21)]),
    ),
  );
  renderProfile([]);

  const list = await screen.findByTestId("weekly-reports");
  await waitFor(() => expect(within(list).getAllByRole("link").length).toBeGreaterThan(0));

  const weeks = within(list).getAllByRole("link");
  const hrefs = weeks.map((link) => link.getAttribute("href"));
  expect(hrefs).toContain("/students/s1/reports/current");
  expect(hrefs).toContain("/students/s1/reports/past");
  expect(hrefs).not.toContain("/students/s1/reports/future");
  // Newest first, so the week just gone is the one at the top rather than the oldest on record.
  expect(hrefs[0]).toBe("/students/s1/reports/current");
});

// ------------------------------------------------------------- weeks that are this student's
//
// `useAllPeriods` spans every workspace the professor belongs to (ADR 0016). Unfiltered, a
// professor in two workspaces got both calendars interleaved into one list of eight: half the
// rows named a period this student has no report under, and their own older weeks fell past the
// cut. The rows that "worked" and the rows that did not were decided by the order postgres
// happened to return two periods sharing a `local_start`, which `list_periods` does not break.

test("the weekly list holds this student's weeks, not another workspace's", async () => {
  // Twelve weeks in each of two workspaces, on the same dates. The student is in w1.
  const weeks: unknown[] = [];
  for (let i = 12; i >= 1; i--) {
    weeks.push(period(`w1-week-${i}`, -7 * i));
    weeks.push({ ...period(`w2-week-${i}`, -7 * i), workspace_id: "w2" });
  }
  server.use(http.get("/api/v1/periods", () => HttpResponse.json(weeks)));
  renderProfile([]);

  const list = await screen.findByTestId("weekly-reports");
  await waitFor(() => expect(within(list).getAllByRole("link").length).toBeGreaterThan(0));
  const hrefs = within(list)
    .getAllByRole("link")
    .map((link) => link.getAttribute("href"));

  expect(hrefs.filter((href) => href?.includes("/w2-"))).toEqual([]);
  // And with the other workspace out of the way, the eight rows are eight of this student's
  // weeks rather than four of them.
  expect(hrefs).toEqual([
    "/students/s1/reports/w1-week-1",
    "/students/s1/reports/w1-week-2",
    "/students/s1/reports/w1-week-3",
    "/students/s1/reports/w1-week-4",
    "/students/s1/reports/w1-week-5",
    "/students/s1/reports/w1-week-6",
    "/students/s1/reports/w1-week-7",
    "/students/s1/reports/w1-week-8",
  ]);
});
