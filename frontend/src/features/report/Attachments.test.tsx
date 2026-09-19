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

test("a link is listed by its address, which is the only thing that identifies one", async () => {
  // A link's filename is derived from its path, so two links to different sites both read "link"
  // or share a last segment — and the address was on no screen at all.
  renderPanel([attachment({ filename: "link", source_url: "https://example.com/ablation-table" })]);

  const shown = screen.getByRole("link", { name: "https://example.com/ablation-table" });
  expect(shown).toHaveAttribute("href", "https://example.com/ablation-table");
});

test("a file, which has no address, is still listed by its filename", async () => {
  renderPanel([attachment({ filename: "notes.md" })]);

  expect(screen.getByText("notes.md")).toBeInTheDocument();
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

test("a file stays removable after the week is submitted", async () => {
  // The bound at submission was dropped: an attachment is the student's own evidence for their own
  // work, and someone who uploaded the wrong thing should not have to ask permission to take it
  // back. The panel therefore has no state in which it hides the control.
  const removed: string[] = [];
  server.use(
    http.delete("/api/v1/artifacts/a1", () => {
      removed.push("a1");
      return new HttpResponse(null, { status: 204 });
    }),
  );
  vi.spyOn(window, "confirm").mockReturnValue(true);
  renderPanel([attachment()]);

  await userEvent.click(screen.getByTestId("remove-attachment"));

  await waitFor(() => expect(removed).toEqual(["a1"]));
});

test("a typo in the link box is caught before anything is created", async () => {
  // The server records a refused link rather than rejecting it — deliberately, so the record says
  // what the student pointed at (REPO-08). That is right for a link resolving somewhere we will
  // not go, and wrong for `not a url`, which became a permanent row badged COULD NOT BE READ.
  const posted: unknown[] = [];
  server.use(
    http.post("/api/v1/artifacts/links", async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json(attachment({ source_url: "x" }), { status: 201 });
    }),
  );
  renderPanel();
  const user = userEvent.setup();

  await user.type(screen.getByPlaceholderText(/https/i), "not a url");
  await user.click(screen.getByRole("button", { name: /add link/i }));

  expect(await screen.findByTestId("attachment-error")).toHaveTextContent(
    /http:\/\/ or https:\/\//,
  );
  expect(posted).toEqual([]);
});

test("a real link is still sent", async () => {
  const posted: unknown[] = [];
  server.use(
    http.post("/api/v1/artifacts/links", async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json(attachment({ source_url: "https://example.org/run" }), {
        status: 201,
      });
    }),
  );
  const { onAttached } = renderPanel();
  const user = userEvent.setup();

  await user.type(screen.getByPlaceholderText(/https/i), "https://example.org/run");
  await user.click(screen.getByRole("button", { name: /add link/i }));

  await waitFor(() => expect(onAttached).toHaveBeenCalled());
  expect(posted).toHaveLength(1);
});

test("the claim the student wrote is shown back on the row", async () => {
  // It was recorded and then appeared on no screen, so nobody could check it, correct it, or
  // notice that a file had gone up without one.
  renderPanel([attachment({ supported_claim: "the run log behind the nDCG number" })]);

  expect(await screen.findByTestId("claim")).toHaveTextContent(
    "the run log behind the nDCG number",
  );
});

test("why a file could not be read is text, not a tooltip", async () => {
  // As the badge's `title` it did not exist on a touch device and was not announced as content.
  renderPanel([
    attachment({
      extraction_state: "failed",
      extraction_note: "only http and https links can be fetched",
    }),
  ]);

  expect(await screen.findByTestId("extraction-note")).toHaveTextContent(/only http and https/);
});

test("a link is not offered a download it has no bytes for", async () => {
  // `/artifacts/{id}/download` 404s for a link, and the rejected promise reached the console and
  // stopped there — from the student's side the button was simply dead.
  renderPanel([attachment({ source_url: "https://example.org/run", filename: "run" })]);

  expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
  // The address is the way to open one, and it is already a link.
  expect(screen.getByRole("link", { name: "https://example.org/run" })).toBeInTheDocument();
});

test("a download that fails says so on the screen", async () => {
  server.use(
    http.get("/api/v1/artifacts/a1/download", () =>
      HttpResponse.json(
        { title: "Not found", status: 404, detail: "this artifact has no stored version" },
        { status: 404 },
      ),
    ),
  );
  renderPanel([attachment()]);

  await userEvent.click(screen.getByRole("button", { name: /download/i }));

  expect(await screen.findByTestId("attachment-error")).toHaveTextContent(/no stored version/i);
});

test("removing a link says what actually happens to it, and names it by its address", async () => {
  // Both halves were wrong. The name came from `filename`, which is derived from the URL's path,
  // so every link without one was called "link" — and the warning promised that "the file and its
  // extracted text are deleted", which is not what removing a link does to a page on the internet.
  server.use(http.delete("/api/v1/artifacts/a1", () => new HttpResponse(null, { status: 204 })));
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  renderPanel([attachment({ filename: "link", source_url: "https://example.com/" })]);

  await userEvent.click(screen.getByTestId("remove-attachment"));

  const asked = confirm.mock.calls[0]![0] as string;
  expect(asked).toContain("https://example.com/");
  expect(asked).not.toContain("The file and its extracted text are deleted");
  expect(asked).toMatch(/page itself is untouched/);
});
