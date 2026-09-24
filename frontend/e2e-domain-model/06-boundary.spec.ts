import { test, expect } from "@playwright/test";
import { PROF, signIn, api, asList } from "./qa-helpers";
import * as fs from "node:fs";
import { fileURLToPath } from "node:url";

// frontend/ is an ES module package, so there is no __dirname here.
const HERE = fileURLToPath(new URL(".", import.meta.url));

const read = () => JSON.parse(fs.readFileSync(`${HERE}state.json`, "utf8"));

/**
 * PROJ-02, ADR 0017 §4, the UI's own promise on the joinable list, and the docstring on
 * `memberships_active_in_range` all say a student who joins an existing project owes from the
 * week after the one they joined in. The predicate is `joined_on <= local_start`, which owes a
 * week that begins on the day of the join.
 *
 * This only shows on the first day of a reporting week, which is why it survives: run the suite
 * on a Wednesday and it passes.
 */
test("B1 joining on the first day of the week owes that week, though the rule says the next one", async ({ page }) => {
  await signIn(page, PROF);
  const { periodId, profProjectId, studentId } = read();
  const period = asList(await api(page, "GET", "/periods")).find((p) => p.id === periodId);
  const members = asList(await api(page, "GET", `/projects/${profProjectId}/members`));
  const mine = members.find((m) => m.student_id === studentId);

  expect(mine.origin).toBe("self_joined");
  expect(mine.joined_on, "the student joined on the first day of this week").toBe(period.local_start);

  const owed = asList(await api(page, "GET", `/periods/${periodId}/obligations`))
    .filter((o) => o.student_id === studentId)
    .map((o) => o.project_id);
  expect(owed, "a week that began on the day of the join is not a week that began after it").not.toContain(
    profProjectId,
  );
});
