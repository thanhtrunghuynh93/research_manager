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

Comes free: the dark palette is the same stylesheet under `.dark`, and the whole theme hangs off
that one class on the root element.

**Dark is the default.** `initialTheme()` in `src/lib/theme.ts` returns the reader's stored choice
and otherwise `"dark"` — deliberately not `prefers-color-scheme`, because the default describes
this product rather than the reader's desktop. `main.tsx` applies it before the first render and
`index.html` carries `color-scheme: dark light`, so the page never flashes light on its way in. The
header toggle flips it and persists the answer under `rm.theme`, which wins from then on.

## Design decisions worth keeping

- Nothing appears as a bare number. Counts carry an as-of stamp; the progress index sits on its
  scale next to its confidence; percentages carry their denominator.
- Claim status is a coloured left edge on the card, so the review screen is scannable by edge.
- The trajectory stays as cards rather than a line, and a card after a rubric change carries a
  warn edge — a line through a rubric break would assert a comparison the data does not support.
- `COMPUTED` / `MODEL` chips on the assistant's blocks keep QA-03's distinction visible to a reader
  who only skims.
