/**
 * Tailwind config for the product theme — use with `src/theme-product.css`.
 *
 * Two differences from `tailwind.config.ts`: `display` is the grotesk rather than Newsreader, so
 * the `font-display` already written into components resolves to the sans instead of needing a
 * pass over every file; and `--radius` is 6px, so `rounded-lg` softens with it.
 */
import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        surface: "hsl(var(--surface))",
        raised: "hsl(var(--raised))",
        foreground: "hsl(var(--foreground))",
        ink2: "hsl(var(--ink-2))",
        faint: "hsl(var(--faint))",
        track: "hsl(var(--track))",
        divider: "hsl(var(--divider))",
        border: { DEFAULT: "hsl(var(--border))", strong: "hsl(var(--border-strong))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          soft: "hsl(var(--accent-soft))",
          line: "hsl(var(--accent-line))",
        },
        good: {
          DEFAULT: "hsl(var(--good))",
          soft: "hsl(var(--good-soft))",
          line: "hsl(var(--good-line))",
        },
        warn: {
          DEFAULT: "hsl(var(--warn))",
          strong: "hsl(var(--warn-strong))",
          soft: "hsl(var(--warn-soft))",
          line: "hsl(var(--warn-line))",
          rule: "hsl(var(--warn-rule))",
        },
        bad: {
          DEFAULT: "hsl(var(--bad))",
          soft: "hsl(var(--bad-soft))",
          line: "hsl(var(--bad-line))",
        },
      },
      fontFamily: {
        display: ['"Be Vietnam Pro"', "system-ui", "sans-serif"],
        sans: ['"Be Vietnam Pro"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 3px)",
      },
      keyframes: {
        "rise-in": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "none" },
        },
      },
      animation: { "rise-in": "rise-in 320ms ease both" },
    },
  },
  plugins: [animate],
} satisfies Config;
