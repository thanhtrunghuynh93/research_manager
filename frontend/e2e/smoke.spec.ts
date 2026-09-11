import { expect, test } from "@playwright/test";

test("status page lists the API readiness checks", async ({ page }) => {
  await page.goto("/status");
  await expect(page.getByRole("heading", { name: /system status/i })).toBeVisible();
  await expect(page.getByText("database")).toBeVisible();
});

test("API liveness responds through the dev proxy", async ({ request }) => {
  const response = await request.get("/api/healthz");
  expect(response.ok()).toBeTruthy();
  expect(await response.json()).toEqual({ status: "ok" });
});
