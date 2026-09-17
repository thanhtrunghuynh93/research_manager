export type Theme = "light" | "dark";

const KEY = "rm.theme";

/**
 * The reader's stored choice, or failing that the product default, which is dark.
 *
 * Deliberately not `prefers-color-scheme`: the default is a decision about this product rather
 * than a reading of the operating system, so a reader on a light desktop still opens the app dark
 * and the toggle is what changes that. The toggle's answer is stored and wins here ever after, so
 * the system preference is overridden only until someone says otherwise.
 */
export function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // A private window can refuse storage entirely. The default is a fine answer.
  }
  return "dark";
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
