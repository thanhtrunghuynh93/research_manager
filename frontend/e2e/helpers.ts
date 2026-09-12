/**
 * Shared helpers for the end-to-end specs.
 *
 * These run against the dev Compose stack loaded with the demo dataset, so they act as the people
 * in the product act: sign in through the form, click through the screens, and read what a user
 * would read. Anything that reaches past the UI is limited to setting up a precondition the
 * product has no screen for (a deadline in the past), and is called out where it happens.
 */
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const PROF = { email: "prof@example.edu", password: "demo-password-change-me" };
export const STUDENT = { email: "an.nguyen@example.edu", password: "demo-password-change-me" };

/** Mailpit's HTTP API, so a delivered email can be read without a mailbox. */
export const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";

export async function signIn(page: Page, who: { email: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(who.email);
  await page.getByLabel(/password/i).fill(who.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("button", { name: /sign out/i })).toBeVisible();
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: /sign out/i }).click();
}

type Message = { ID: string; To: { Address: string }[]; Subject: string };

export async function inbox(request: APIRequestContext): Promise<Message[]> {
  const response = await request.get(`${MAILPIT}/api/v1/messages?limit=200`);
  if (!response.ok()) return [];
  const body = (await response.json()) as { messages?: Message[] };
  return body.messages ?? [];
}

export async function clearInbox(request: APIRequestContext): Promise<void> {
  await request.delete(`${MAILPIT}/api/v1/messages`);
}

export async function messageBody(request: APIRequestContext, id: string): Promise<string> {
  const response = await request.get(`${MAILPIT}/api/v1/message/${id}`);
  const body = (await response.json()) as { Text?: string; HTML?: string };
  return `${body.Text ?? ""}\n${body.HTML ?? ""}`;
}

export function addressesOf(messages: Message[]): string[] {
  return messages.flatMap((message) => message.To.map((to) => to.Address));
}
