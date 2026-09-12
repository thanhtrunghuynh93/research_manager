/** QA-03..07: the answer contract on screen, including the parts that say what is not known. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { AssistantPage } from "@/features/assistant/pages/AssistantPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const BASE = {
  id: "an1",
  conversation_id: "c1",
  question: "Which reports are missing?",
  scope: {
    student_id: null,
    student_name: "",
    project_id: null,
    project_name: "",
    since: null,
    until: null,
    as_of: "2026-09-21T03:00:00Z",
    role: "prof",
  },
  time_range: "all records up to 2026-09-21",
  answer: "One reporting obligation is unfulfilled.",
  facts: [
    {
      name: "missing_reports",
      label: "Unfulfilled reporting obligations",
      value: 1,
      as_of: "2026-09-21T03:00:00Z",
      rows: [],
      note: "Counted from the reporting obligations after exemptions and extensions.",
    },
  ],
  synthesis: [],
  suggestions: [],
  citations: [],
  gaps: [],
  clarifying_question: "",
  cached: false,
  generated_at: "2026-09-21T03:00:01Z",
  model_name: "fake-1",
  prompt_versions: {},
};

async function ask(answer: Record<string, unknown> = BASE) {
  server.use(http.post("/api/v1/assistant/ask", () => HttpResponse.json(answer)));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AssistantPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await userEvent.type(screen.getByLabelText(/question/i), "Which reports are missing?");
  await userEvent.click(screen.getByRole("button", { name: /^ask$/i }));
}

/** Render, then answer each POST in turn, recording the request bodies. */
async function conversation(answers: Record<string, unknown>[]) {
  const sent: Record<string, unknown>[] = [];
  let turn = 0;
  server.use(
    http.post("/api/v1/assistant/ask", async ({ request }) => {
      sent.push((await request.json()) as Record<string, unknown>);
      const answer = answers[Math.min(turn, answers.length - 1)]!;
      turn += 1;
      return answer.__status === 404
        ? HttpResponse.json({ detail: "conversation not found" }, { status: 404 })
        : HttpResponse.json(answer);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AssistantPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return {
    sent,
    async say(text: string) {
      await userEvent.clear(screen.getByLabelText(/question/i));
      await userEvent.type(screen.getByLabelText(/question/i), text);
      await userEvent.click(screen.getByRole("button", { name: /^ask$/i }));
    },
  };
}

test("shows the active scope and the time range beside the answer", async () => {
  await ask();

  expect(await screen.findByTestId("scope-badge")).toHaveTextContent(/whole workspace/i);
  expect(screen.getByTestId("answer")).toHaveTextContent(/all records up to/);
});

test("keeps computed facts visually apart from model synthesis", async () => {
  await ask({
    ...BASE,
    synthesis: ["The gap is concentrated in one project."],
  });

  const facts = await screen.findByTestId("facts");
  expect(facts).toHaveTextContent(/Computed from the database, not written by the model/);
  const synthesis = screen.getByTestId("synthesis");
  expect(synthesis).toHaveTextContent(/The model's reading/);
  expect(synthesis).toHaveTextContent(/concentrated in one project/);
});

test("labels suggestions as drafts rather than actions taken", async () => {
  await ask({ ...BASE, suggestions: ["Ask about the cluster queue at the meeting."] });

  expect(await screen.findByTestId("suggestions")).toHaveTextContent(/never actions taken/i);
});

test("shows what could not be established as prominently as the answer", async () => {
  await ask({
    ...BASE,
    gaps: ["2 citation(s) did not match any retrieved record and were removed"],
  });

  expect(await screen.findByTestId("gaps")).toHaveTextContent(/did not match any retrieved record/);
});

test("a private note is shown locked rather than as a followable link", async () => {
  await ask({
    ...BASE,
    citations: [
      {
        source_kind: "supervision_note",
        source_id: "n1",
        source_version: "",
        locator: "/students/s1#notes",
        label: "private supervision note",
        available: true,
      },
    ],
  });

  expect(await screen.findByTestId("citation-private")).toBeInTheDocument();
  expect(screen.queryByTestId("citation-link")).not.toBeInTheDocument();
});

test("a source the reader can no longer open is struck through, not silently dropped", async () => {
  await ask({
    ...BASE,
    citations: [
      {
        source_kind: "report_entry",
        source_id: "e1",
        source_version: "1",
        locator: "/report/p1",
        label: "entry submitted 2026-09-19",
        available: false,
      },
    ],
  });

  expect(await screen.findByTestId("citation-gone")).toHaveTextContent(/no longer available/);
});

test("an ambiguous question shows the clarifying question instead of an answer", async () => {
  await ask({
    ...BASE,
    answer: "Which Lan do you mean — Lan A, Lan B?",
    clarifying_question: "Which Lan do you mean — Lan A, Lan B?",
    facts: [],
  });

  expect(await screen.findByTestId("clarifying")).toHaveTextContent(/Which Lan do you mean/);
  expect(screen.queryByTestId("answer-text")).not.toBeInTheDocument();
});

test("says the assistant cannot act", async () => {
  await ask();

  expect(
    await screen.findByText(/sending, approving and changing remain your actions/i),
  ).toBeInTheDocument();
});

test("a follow-up carries the conversation id, not the id of the answer it came from", async () => {
  // The regression: "keep this scope" stored `answer.id`, which the server mints per answer and
  // cannot resolve as a conversation — so every follow-up 404'd (QA-05).
  const { sent, say } = await conversation([BASE]);

  await say("Which reports are missing?");
  await userEvent.click(await screen.findByRole("button", { name: /keep this scope/i }));
  await say("And last month?");

  expect(sent).toHaveLength(2);
  expect(sent[0]!.conversation_id).toBeNull();
  expect(sent[1]!.conversation_id).toBe("c1");
});

test("a conversation the server rejects does not wedge every later question", async () => {
  const { sent, say } = await conversation([BASE, { __status: 404 }, BASE]);

  await say("Which reports are missing?");
  await userEvent.click(await screen.findByRole("button", { name: /keep this scope/i }));
  await say("And last month?");
  await screen.findByText(/could not be answered/i);
  await say("Try again");

  // The rejected id is dropped rather than resent, so the third question starts fresh.
  expect(sent[1]!.conversation_id).toBe("c1");
  expect(sent[2]!.conversation_id).toBeNull();
});
