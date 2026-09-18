/** REP-04: the three-step upload, and saying plainly what happened to the file afterwards. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { Attachments, type Attachment } from "@/features/report/components/Attachments";
import "@/lib/i18n";
import { server } from "@/test/setup";

const GRANT = {
  artifact_id: "a1",
  version_no: 1,
  url: "https://objects.example/upload/a1",
  expires_in: 900,
  headers: { "Content-Type": "text/markdown" },
};

function renderPanel(attachments: Attachment[] = [], onAttached = vi.fn()) {
  return {
    onAttached,
    ...render(
      <Attachments
        projectId="p1"
        periodId="per1"
        attachments={attachments}
        onAttached={onAttached}
      />,
    ),
  };
}

function attachment(overrides: Partial<Attachment> = {}): Attachment {
  return {
    artifact_id: "a1",
    version_no: 1,
    filename: "notes.md",
    byte_size: 42,
    extraction_state: "ok",
    extraction_note: "",
    truncated: false,
    ...overrides,
  };
}

test("the file goes to object storage and only the confirmation goes to the API", async () => {
  const seen: string[] = [];
  server.use(
    http.post("/api/v1/artifacts/uploads", () => {
      seen.push("grant");
      return HttpResponse.json(GRANT, { status: 201 });
    }),
    http.put("https://objects.example/upload/a1", () => {
      seen.push("put");
      return new HttpResponse(null, { status: 200 });
    }),
    http.post("/api/v1/artifacts/a1/confirm", () => {
      seen.push("confirm");
      return HttpResponse.json(attachment());
    }),
  );
  const { onAttached } = renderPanel();

  await userEvent.upload(
    screen.getByLabelText(/attach a file/i),
    new File(["# notes"], "notes.md", { type: "text/markdown" }),
  );

  await waitFor(() => expect(onAttached).toHaveBeenCalled());
  // The bytes went straight to the store, between the grant and the confirmation.
  expect(seen).toEqual(["grant", "put", "confirm"]);
});

test("a file the server refuses shows the reason it gave", async () => {
  server.use(
    http.post("/api/v1/artifacts/uploads", () =>
      HttpResponse.json(
        {
          title: "Validation failed",
          status: 422,
          detail: "this file is larger than the 25 MB per-file limit",
        },
        { status: 422 },
      ),
    ),
  );
  renderPanel();

  await userEvent.upload(
    screen.getByLabelText(/attach a file/i),
    new File(["x"], "huge.pdf", { type: "application/pdf" }),
  );

  expect(await screen.findByTestId("attachment-error")).toHaveTextContent(/25 MB/);
});

test("a file that could not be read says so, with the reason in reach", async () => {
  // REP-04: unreadable and empty are different, and the student can only fix the first.
  renderPanel([
    attachment({
      filename: "scan.pdf",
      extraction_state: "failed",
      extraction_note: "the file could not be read (PdfReadError); it is stored unchanged",
    }),
  ]);

  const badge = screen.getByTestId("extraction-badge");
  expect(badge).toHaveTextContent(/could not be read/i);
  expect(badge).toHaveAttribute("title", expect.stringContaining("PdfReadError"));
});

test("an image is shown as stored rather than as a failure", async () => {
  renderPanel([attachment({ filename: "figure.png", extraction_state: "unsupported" })]);

  expect(screen.getByTestId("extraction-badge")).toHaveTextContent(/stored, no text/i);
});

test("a link is attached through the API, which decides whether to follow it", async () => {
  server.use(
    http.post("/api/v1/artifacts/links", () =>
      HttpResponse.json(
        attachment({
          filename: "2401.00001",
          extraction_state: "failed",
          extraction_note: "example.com resolves to a private or reserved address",
        }),
        { status: 201 },
      ),
    ),
  );
  const { onAttached } = renderPanel();

  await userEvent.type(screen.getByPlaceholderText("https://…"), "https://example.com/paper");
  await userEvent.click(screen.getByRole("button", { name: /add link/i }));

  await waitFor(() => expect(onAttached).toHaveBeenCalled());
});

test("the panel says what the claim field is for", async () => {
  // REPO-08: what the student says a file shows is their claim, not a finding.
  renderPanel();

  expect(screen.getByText(/Recorded as your claim, not as a finding/i)).toBeInTheDocument();
});

test("while a file is in flight the panel names it, rather than going quiet", async () => {
  // On the live stack the grant took 1.5s and the confirmation 4.6s, because confirming reads the
  // text out of the file. For those six seconds the input is disabled and — since the change
  // handler clears its value so the same file can be chosen again — shows no filename either. A
  // disabled control showing nothing is indistinguishable from a broken one, which is what it was
  // taken for.
  let release: (() => void) | undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http.post("/api/v1/artifacts/uploads", () => HttpResponse.json(GRANT, { status: 201 })),
    http.put("https://objects.example/upload/a1", () => new HttpResponse(null, { status: 200 })),
    http.post("/api/v1/artifacts/a1/confirm", async () => {
      await held;
      return HttpResponse.json(attachment());
    }),
  );
  const { onAttached } = renderPanel();

  await userEvent.upload(
    screen.getByLabelText(/attach a file/i),
    new File(["# notes"], "notes.md", { type: "text/markdown" }),
  );

  const sending = await screen.findByTestId("attachment-sending");
  expect(sending).toHaveTextContent(/notes\.md/);
  expect(screen.getByLabelText(/attach a file/i)).toBeDisabled();

  release?.();
  await waitFor(() => expect(onAttached).toHaveBeenCalled());
  await waitFor(() => expect(screen.queryByTestId("attachment-sending")).not.toBeInTheDocument());
});

test("a student removes a file they attached, and the list is refetched", async () => {
  const removed: string[] = [];
  server.use(
    http.delete("/api/v1/artifacts/a1", () => {
      removed.push("a1");
      return new HttpResponse(null, { status: 204 });
    }),
  );
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const { onAttached } = renderPanel([attachment()]);

  await userEvent.click(screen.getByTestId("remove-attachment"));

  await waitFor(() => expect(removed).toEqual(["a1"]));
  expect(onAttached).toHaveBeenCalled();
});

test("declining the confirmation removes nothing", async () => {
  const removed: string[] = [];
  server.use(
    http.delete("/api/v1/artifacts/a1", () => {
      removed.push("a1");
      return new HttpResponse(null, { status: 204 });
    }),
  );
  vi.spyOn(window, "confirm").mockReturnValue(false);
  renderPanel([attachment()]);

  await userEvent.click(screen.getByTestId("remove-attachment"));

  expect(removed).toEqual([]);
});

test("a submitted week offers no removal, and says why", async () => {
  // The API refuses it, so offering a button that always fails would be worse than no button —
  // and an absent button with no explanation reads as something missing.
  render(
    <Attachments
      projectId="p1"
      periodId="per1"
      attachments={[attachment()]}
      submitted
      onAttached={vi.fn()}
    />,
  );

  expect(screen.queryByTestId("remove-attachment")).not.toBeInTheDocument();
  expect(screen.getByTestId("attachments-locked")).toHaveTextContent(/part of the record/i);
});

test("the locked notice names when the week went in, and says attaching did not do it", async () => {
  // It appears directly under a file the student has just attached, so without the date it reads
  // as cause and effect — which is how it was read.
  render(
    <Attachments
      projectId="p1"
      periodId="per1"
      attachments={[attachment()]}
      submitted
      submittedAt="2026-09-17T03:54:12Z"
      onAttached={vi.fn()}
    />,
  );

  const locked = screen.getByTestId("attachments-locked");
  expect(locked).toHaveTextContent(/Sep 17, 2026/);
  expect(locked).toHaveTextContent(/does not submit anything/i);
});
