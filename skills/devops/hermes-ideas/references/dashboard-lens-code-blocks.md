# Ideas dashboard — LENS theme and Notion-style code blocks

Use when fenced code in the Ideas editor is invisible, flat (no panel), or missing syntax colors on the Hermes dashboard (especially LENS_0 / teal).

## Symptom: invisible code until selected

**Cause:** Theme globals paint every `<code>` with `--foreground`, which is **transparent** on LENS layered skins. Lexical prose inherits readable text; nested fenced `<code>` nodes do not.

**Fix:** In `plugins/ideas/dashboard/dist/style.css`, under `.ideas-page`:

- Reset generic `code` / `pre` to `color: inherit` (exclude `.ideas-lexical-codeblock` and inline code classes).
- Kanban already documents the same pattern in `plugins/kanban/dashboard/dist/style.css` (`.hermes-kanban pre` reset + intentional pill on `.hermes-kanban-md-code`).

## Symptom: code visible but not a "block" (Notion look)

User wants a **lifted panel**: rounded rect, padding, subtle border, mono font, horizontal scroll.

**CSS targets:** `.ideas-lexical-content .ideas-lexical-codeblock`

- `background: color-mix(in srgb, currentColor 9%, transparent)`
- `box-shadow: inset 0 0 0 1px color-mix(...)`
- `font-family` from `--theme-font-mono`
- Token colors on `.ideas-lexical-token-*` (keywords yellow, strings peach, comments muted)

**JS:** `registerCodeHighlighting(editor)` from `@lexical/code` in `web/src/plugins/registry.ts`; rebuild Ideas dashboard bundle (`plugins/ideas/dashboard/dist/index.js`).

## Verify

1. Hard-refresh dashboard (Ctrl+Shift+R) or restart `hermes dashboard`.
2. Open an idea with a ` ``` ` fenced block — text readable without selection; block reads as a distinct panel.

## Do not

- Revert to the legacy contenteditable block editor for this — user prefers Lexical.
- Fix only `color` without background — blocks still won't read as Notion-style panels.
