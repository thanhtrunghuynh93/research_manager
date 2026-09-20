/** The default is a product decision, so it is pinned here rather than left to the browser. */
import { afterEach, expect, test } from "vitest";

import { applyTheme, initialTheme } from "@/lib/theme";

afterEach(() => {
  localStorage.removeItem("rm.theme");
  document.documentElement.classList.remove("dark");
});

test("a reader with no stored choice gets dark", () => {
  expect(initialTheme()).toBe("dark");
});

test("a stored choice wins over the default, including the light one", () => {
  applyTheme("light");

  expect(initialTheme()).toBe("light");
});

test("the system preference does not decide it", () => {
  // A light desktop still opens the app dark: the default describes the product, not the OS.
  const matchMedia = window.matchMedia;
  Object.defineProperty(window, "matchMedia", {
    value: () => ({ matches: false }),
    configurable: true,
  });

  expect(initialTheme()).toBe("dark");

  Object.defineProperty(window, "matchMedia", { value: matchMedia, configurable: true });
});
