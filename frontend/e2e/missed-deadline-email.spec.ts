/**
 * AC-19 / REP-08, at the level the service tests cannot reach: mail actually leaving the host.
 *
 * Everything about who gets written to is settled in `tests/module/test_deadline_drill.py`. What
 * only a running stack can show is the rest of the chain — the worker's sender, SMTP, and a
 * message arriving in a mailbox — and the content rule that matters most, which is that the email
 * carries no assessment and no other student's name.
 *
 * The drill command creates the one precondition a browser cannot: a deadline already behind us.
 * From that point on it is the production path.
 */
import { execSync } from "node:child_process";

import { expect, test } from "@playwright/test";

import { clearInbox, addressesOf, inbox, messageBody, PROF, signIn } from "./helpers";

type Drill = {
  period_id: string;
  unsubmitted_email: string;
  submitted_email: string;
  excused_email: string;
  emails_sent: number;
};

const COMPOSE =
  process.env.E2E_COMPOSE ??
  "docker compose -f ../infra/docker-compose.yml -f ../infra/docker-compose.dev.yml --env-file ../infra/.env";

function runDrill(): Drill {
  const output = execSync(
    `${COMPOSE} exec -T api uv run python -m app.cli seed missed-deadline-drill`,
    {
      encoding: "utf8",
    },
  );
  const line = output.trim().split("\n").filter(Boolean).at(-1)!;
  return JSON.parse(line) as Drill;
}

test.describe.configure({ mode: "serial" });

let drill: Drill;

test.beforeAll(async ({ request }) => {
  await clearInbox(request);
  drill = runDrill();
});

test("the unsubmitted student is emailed, and nobody else in the scenario is", async ({
  request,
}) => {
  const messages = await inbox(request);
  const addresses = addressesOf(messages);

  expect(addresses.filter((address) => address === drill.unsubmitted_email)).toHaveLength(1);
  expect(addresses).not.toContain(drill.submitted_email);
  expect(addresses).not.toContain(drill.excused_email);
});

test("the professor is told in-app and is not emailed", async ({ page, request }) => {
  // REP-08: the professor sees the outstanding list at the same moment, without an email.
  // Use cases v0.3 retired the notifications screen, so the overview is where they see it — the
  // same obligations, read from the table that owes them rather than from a message about it.
  expect(addressesOf(await inbox(request))).not.toContain(PROF.email);

  await signIn(page, PROF);
  await page.goto("/overview");

  // The drill's one unsubmitted student, listed by id — the overview names nobody by email.
  const outstanding = page.getByTestId("outstanding");
  await expect(outstanding).not.toContainText(/nothing outstanding/i);
  await expect(outstanding.locator("li")).toHaveCount(1);
});

test("the email lists the missing entry and carries no assessment or other student", async ({
  request,
}) => {
  const messages = await inbox(request);
  const mine = messages.find((message) =>
    message.To.some((to) => to.Address === drill.unsubmitted_email),
  )!;
  const body = await messageBody(request, mine.ID);

  expect(body).toMatch(/deadline drill/i); // the project whose entry is missing
  expect(body).toMatch(/report/i);
  expect(body).not.toContain(drill.submitted_email);
  expect(body).not.toContain(drill.excused_email);
  // UI-07: no assessment content ever travels by email.
  expect(body).not.toMatch(/progress index|rubric|rating/i);
});

test("running the dispatch again sends no duplicate", async ({ request }) => {
  // AC-19: the notification key and the queueing lock make a retried job a no-op.
  const before = addressesOf(await inbox(request)).filter(
    (address) => address === drill.unsubmitted_email,
  ).length;

  execSync(
    `${COMPOSE} exec -T api uv run python -m app.cli notifications dispatch-missed-deadline --period ${drill.period_id}`,
    { encoding: "utf8" },
  );

  const after = addressesOf(await inbox(request)).filter(
    (address) => address === drill.unsubmitted_email,
  ).length;
  expect(after).toBe(before);
});
