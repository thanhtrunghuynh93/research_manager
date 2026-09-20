# Ledger theme — implementation notes

Restyle only. No route, hook, query, mutation, payload, `data-testid`, `aria-*` or copy key was
changed, so the existing vitest/Playwright suites and the API contract are untouched. Every file
below is a drop-in replacement for the same path in `research_manager`.

## Files

| File | Change |
| --- | --- |
| `frontend/index.html` | Google Fonts preconnect + Newsreader / IBM Plex Sans / IBM Plex Mono |
| `frontend/tailwind.config.ts` | Token colours, three font families, radii, `rise-in` keyframes |
| `frontend/src/index.css` | All tokens (light + `.dark`), plus the component layer below |
| `src/app/layout/AppShell.tsx` | Header lockup, `NavLink` active rule (was `Link`), language/sign-out as controls |
| `src/app/RequireAuth.tsx`, `src/app/StatusPage.tsx` | Loading/state styling only |
| `src/components/evidence/Badges.tsx` | Mono chips; `Badge` now merges an incoming `className`; `ProgressIndex` gained `size?: "inline" \| "figure"` |
| `src/components/evidence/CitationLink.tsx` | Mono citations |
| `src/features/*/pages/*.tsx`, `src/features/report/components/*` | Class names, eyebrows, stamps, panels |

Two component signatures widened (both additive, both backwards compatible):
`Badge` accepts `className`, and `ProgressIndex` accepts `size`. Nothing else changed shape.

## The type system

Three families, three jobs:

- **Newsreader** — page titles, section titles, and any figure the reader is meant to weigh
  (progress index, completion percentage).
- **IBM Plex Sans** — the interface: labels, body, buttons, rows.
- **IBM Plex Mono** — anything the *system* asserts: timestamps, identifiers, versions, rubric ids,
  sync states, status chips, the export request line. Provenance is set in the typeface that looks
  like a machine wrote it, because a machine did.

## Component classes (`index.css`)

`.eyebrow` `.stamp` `.figure` `.figure-unit` `.page-title` `.section-title` `.panel` `.row`
`.card` `.chip` + `.chip-{neutral,accent,good,warn,bad}` `.field-label` `.input` `.textarea`
`.select` `.btn-primary` `.btn-ghost` `.btn-quiet` `.notice-warn` `.meter` `.meter-fill`

`.panel` owns its own row dividers (`.panel > * + *`), so lists no longer need `divide-y`.

## Dark mode

Shipped: `lib/theme.ts` + `hooks/useTheme.ts` toggle `.dark` on the root and store the choice under
`rm.theme`. The product default is dark, decided outright rather than read from
`prefers-color-scheme`.

## Design decisions worth keeping

- Nothing appears as a bare number. Counts carry an as-of stamp; the progress index sits on its
  scale next to its confidence; percentages carry their denominator.
- Claim status is a coloured left edge on the card, so the review screen is scannable by edge.
- The trajectory stays as cards rather than a line, and a card after a rubric change carries a
  warn edge — a line through a rubric break would assert a comparison the data does not support.
- `COMPUTED` / `MODEL` chips on the assistant's blocks keep QA-03's distinction visible to a reader
  who only skims.

---

# Applied here, not yet upstream

Two changes made in the prototypes (`Research Manager.dc.html`, `Research Manager Dark.dc.html`)
and now written into this project's `index.html`, `tailwind.config.ts` and `index.css`. Both are
token-level: no component class changes. Not yet committed to `main`.

## 1. Interface sans: IBM Plex Sans → Be Vietnam Pro

Drawn for Vietnamese first, so stacked diacritics (Nguyễn, Phạm, Trần — every name on the roll)
sit clear of ascenders instead of colliding with them. Slightly warmer and rounder than Plex Sans
at the same optical size, which is the whole of the "chill" brief.

Newsreader and IBM Plex Mono are unchanged: the mono is doing epistemic work — timestamps,
versions, rubric ids, sync states — and should stay visibly machine-set.

`index.html`:

    <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300..600;1,6..72,300..500&family=Be+Vietnam+Pro:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet" />

`tailwind.config.ts`:

    sans: ['"Be Vietnam Pro"', "system-ui", "sans-serif"],

## 2. A calmer `.dark` palette

The ground lifts off near-black, the paper texture quietens, the ink stops glaring, and the four
signal hues each lose some saturation so an amber warn no longer reads as an alarm on a dark
field. Body text still clears 4.5:1. Soft fills and lines (`--*-soft`, `--*-line`) are unchanged.

    .dark {
      --background: 45 10% 8%;        /* was 30 8% 7%   */
      --surface: 40 11% 11%;          /* was 35 12% 10% */
      --raised: 38 13% 13%;           /* was 30 12% 11% */
      --foreground: 40 26% 87%;       /* was 38 32% 91% */
      --paper-dot: 40 10% 11%;        /* was 35 15% 13% */

      --accent: 211 36% 75%;          /* was 214 47% 74% */
      --good: 151 28% 63%;            /* was 149 35% 62% */
      --warn: 36 53% 66%;             /* was 38 66% 63%  */
      --warn-strong: 37 51% 74%;      /* was 38 63% 74%  */
      --warn-rule: 45 59% 45%;        /* was 45 68% 47%  */
      --bad: 7 47% 71%;               /* was 6 60% 72%   */

      --primary: 40 26% 87%;
      --primary-foreground: 45 10% 8%;
    }

The light palette is untouched — it was already low-contrast paper, and softening it further would
cost legibility rather than tension.

---

# The product theme — an alternative, not a revision

`src/theme-product.css` + `tailwind.product.config.ts` are a second stylesheet for the same
components. Nothing in `src/**` changes: identical class names, identical token names. To try it,
swap one import in `main.tsx` and point the build at the other config:

    import "./theme-product.css";   // instead of "./index.css"

`Research Manager Product.dc.html` is what it looks like.

## What it changes

**One family, not three.** Newsreader goes; headings are the interface grotesk, small and tight —
`page-title` 40px → 26px, `section-title` 20px → 15px, `figure` 34px → 28px. `font-display` still
resolves (the config maps it to the sans), so no component file needs touching.

**The mono keeps one job.** Provenance only: timestamps, ids, versions, rubric ids, sync states.
It comes off `.eyebrow` and `.field-label`, which become sans caps — those are furniture, not
assertions, and the mono on them is most of what made the ledger look typed.

**Dark is `:root`.** `.light` is the opt-out, matching `lib/theme.ts`, which defaults to dark
outright. `useTheme` currently toggles `.dark`; with this sheet, invert it or drop the toggle.

**Flatter and denser.** No paper texture, body 14px → 13px, `.row` padding 16/10 → 14/8,
`--radius` 4px → 6px, chips square rather than pills (a pill in a data row reads as a button).

**The primary button is the accent, not the ink.** On a dark product ground an almost-white
button is the loudest object on screen, and "Send invitation" is not the loudest act.

**Links carry colour, not a rule** — the underline returns on hover.

## What it deliberately keeps

The signal colours and their soft/line pairs, at contrast. An amber that means "deferred,
retryable" is load-bearing. `.notice-warn` keeps its 3px left rule, `Not rated` keeps a real cell,
the rubric break keeps its labelled gap. This is a change of voice, not of epistemics.

## Before adopting

The two sheets share token names but not token values, so they cannot both be loaded. Check any
`dark:` variants in components — under this sheet the default is already dark and those invert.
And the accent is now a saturated indigo used for both links and the primary fill; if a screen
puts a primary button on `accent-soft`, re-check that pair.
