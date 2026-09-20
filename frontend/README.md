# What to copy, and what NOT to

**Do not replace your `src/` with this folder.** The `frontend/` tree in the design project is a
partial mirror — only the files that were read or changed. Your `main.tsx`, query layer, API
client and most feature pages are not in it, and a wholesale copy would delete them.

These 6 files are everything that changed. Copy them over your equivalents:

| From | To | Why |
| --- | --- | --- |
| `src/index.css` | `frontend/src/index.css` | Tokens: white `:root`, product-dark `.dark`, link + button rules |
| `src/app/layout/AppShell.tsx` | `frontend/src/app/layout/AppShell.tsx` | Workspace chip, tagline removed, header no-wrap |
| `tailwind.config.ts` | `frontend/tailwind.config.ts` | Sans → Be Vietnam Pro, `--bad-rule` colour |
| `index.html` | `frontend/index.html` | Font link: Be Vietnam Pro replaces IBM Plex Sans |
| `STYLE-NOTES.md` | `frontend/STYLE-NOTES.md` | The reasoning, for whoever reads this next |

`src/theme-product.css` and `tailwind.product.config.ts` are **optional** — the denser sans-only
variant. They are not wired up; see STYLE-NOTES.

## What changed, in one list

- **Type.** IBM Plex Sans → Be Vietnam Pro (Vietnamese diacritics clear the ascenders). Newsreader
  is gone; one grotesk for everything. The mono is provenance only — timestamps, ids, versions,
  sync states — and came off eyebrows and field labels.
- **Light is white.** Warm paper → `#FFFFFF` ground, cool grey neutrals, a true blue accent. The
  paper-dot texture is off in light (`--paper-dot` = the background) and kept in dark.
- **Dark is a near-black product surface.** Neutral `#0D0E10` ground, hairline borders, indigo
  primary. `--primary` is the accent in both modes, not the ink.
- **Links are the ink**, underlined on hover; the accent is reserved for fills — primary button,
  progress meters, trajectory bars.
- **Scale.** 26 page title / 28 figure / 22 value / 15 section head / 13 body, one tracking value
  per role. `--radius` 4px → 6px.

## Two things the CSS cannot carry

1. **The week board hierarchy** on `/overview`: the project name should be `text-[15px]
   font-semibold tracking-[-0.01em]` with `pt-3`, against the student names' `text-[13px]`. That
   is a change in `OverviewPage.tsx`, which is not in this package.
2. **`useTheme` still toggles `.dark`** and defaults to dark — correct for `index.css`. If you
   adopt `theme-product.css` instead, dark is `:root` there and `.light` is the opt-out, so the
   toggle has to invert.

## Before committing

```
npm run lint && npm run typecheck && npm run build
```

Watch for `dark:` variant classes in components — the palettes changed underneath them.
