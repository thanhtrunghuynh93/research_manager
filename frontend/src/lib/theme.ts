export type Theme = "light" | "dark";

const KEY = "rm.theme";

/** The reader's stored choice, or failing that what their system asks for. */
export function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // A private window can refuse storage entirely. The system preference is a fine answer.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Tailwind runs in `darkMode: ["class"]` and index.css defines the dark palette under `.dark`,
 * so the entire theme hangs off this one class on the root element.
 */
export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Not worth failing a click over; the choice just will not survive the reload.
  }
}
