/**
 * Every control class a component uses must exist in the stylesheet.
 *
 * `btn-secondary` was used in seven places and defined in none of them, so those buttons rendered
 * with no styling at all — browser default, easy to miss, and silent. Nothing catches that:
 * Tailwind emits no warning for a class it was never asked to make, TypeScript does not read
 * `className`, and the tests that clicked those buttons found them by test id.
 *
 * Scoped to the `btn-*` and `file-*` families rather than to every class, because the rest of what
 * appears in a `className` is Tailwind's and cannot be told apart from ours without asking Tailwind
 * itself. These two are where we name our own controls, and they are where the mistake happened.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "vitest";

function filesUnder(dir: string, suffix: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return filesUnder(path, suffix);
    return path.endsWith(suffix) ? [path] : [];
  });
}

test("no component uses a control class the stylesheet does not define", () => {
  const defined = new Set(
    [...readFileSync("src/index.css", "utf8").matchAll(/\.((?:btn|file)-[a-z-]+)\s*\{/g)].flatMap(
      (match) => match[1] ?? [],
    ),
  );
  expect(defined.size).toBeGreaterThan(0);

  const used = new Map<string, string[]>();
  for (const file of filesUnder("src", ".tsx")) {
    for (const match of readFileSync(file, "utf8").matchAll(/\b((?:btn|file)-[a-z-]+)\b/g)) {
      const name = match[1];
      if (name) used.set(name, [...(used.get(name) ?? []), file]);
    }
  }

  const undefinedClasses = [...used].filter(([name]) => !defined.has(name));
  expect(undefinedClasses).toEqual([]);
});
