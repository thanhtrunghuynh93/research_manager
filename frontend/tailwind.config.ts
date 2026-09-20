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
          rule: "hsl(var(--bad-rule))",
        },
      },
      fontFamily: {
        display: ["Newsreader", "Georgia", "serif"],
        sans: ['"Be Vietnam Pro"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      /**
       * The type scale, named for what each step is for.
       *
       * These were 106 arbitrary values spelled out in the components — `text-[13px]`,
       * `text-[13.5px]`, `text-[12.5px]`, `text-[11.5px]` — twelve distinct sizes with no name
       * and no single place to change them. That is not a scale, it is a habit, and it had two
       * consequences worth naming. A design pass could not move the type at all, because nothing
       * it owns reaches a literal inside a className. And steps half a pixel apart kept appearing:
       * the professor's overview set a project heading at 13.5px over its students at 13px, which
       * is a hierarchy nobody can see.
       *
       * So the sizes live here, where the design system already keeps the palette and the
       * families, and the components ask for a role instead of a number. The half-pixel
       * neighbours are gone — 11.5 joined 11, 12 joined 12.5 — because a step the eye cannot
       * resolve is not a step.
       *
       * Sizes only, deliberately. Tailwind lets a step carry a line-height, and that would apply
       * everywhere a size is used without an explicit `leading-*` — which is most places. The
       * leading stays where it is set today, so naming the sizes changes no spacing.
       */
      fontSize: {
        /** Uppercase micro-labels on chips and tab states. */
        tag: "10px",
        /** Provenance: timestamps, ids, versions, sync states. Matches `.stamp` and `.eyebrow`. */
        meta: "11px",
        /** A secondary note under a row, and the filenames of attachments. */
        note: "12.5px",
        /** Labels, links and row text — what the reader scans. */
        ui: "13px",
        /** Sentences the reader actually reads. */
        prose: "13.5px",
        /** A heading over a list, which has to outrank the rows under it. */
        title: "15px",
        /** Display prose: the one paragraph a page opens with. */
        lead: "1.1875rem",
        /** Display headings, below `.page-title`. */
        "display-sm": "1.55rem",
        display: "1.625rem",
        /** A single number shown large, beside its unit and its caveat. */
        figure: "2.125rem",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 1px)",
        sm: "calc(var(--radius) - 2px)",
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
