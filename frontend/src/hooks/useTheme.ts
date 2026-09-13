import { useCallback, useState } from "react";

import { applyTheme, initialTheme, type Theme } from "@/lib/theme";

/**
 * The current theme and a way to flip it. The class is applied in main.tsx before the first
 * render, so this holds the value only to label the control.
 */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      applyTheme(next);
      return next;
    });
  }, []);

  return { theme, toggle };
}
