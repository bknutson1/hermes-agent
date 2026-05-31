# Kanban dashboard — attention strip and diagnostics

Use when the board shows **"N tasks need attention"**, dismiss (✕) does not stick after refresh, or operators complain about block→unblock cycling noise.

## Attention strip behavior

- **Source:** `collectDiagTasks(boardData)` in `plugins/kanban/dashboard/dist/index.js` — one row per task with active diagnostics from `hermes_cli/kanban_diagnostics.py`.
- **Dismiss:** ✕ hides tasks until their diagnostics **clear**, not just until reload. Persisted per board in `localStorage` key `hermes.kanban.attentionDismissed` (map of board slug → task id list). Prune ids when a task no longer has diagnostics.
- **Pitfall (fixed):** Earlier implementation used React `dismissed` boolean only — tooltip even said "Hide until next page reload." Refresh always resurfaced the banner.

## Removed: `block_unblock_cycling` diagnostic

Rule `_rule_block_unblock_cycling` was removed from `_RULES` / `DIAGNOSTIC_KINDS` — normal block/unblock iteration is not actionable noise. **`_rule_stuck_in_blocked`** still covers tasks that stay blocked too long without progress.

If users still see cycling text after upgrade: hard-refresh dashboard; restart gateway so diagnostics recompute without the retired kind.

## Other diagnostics (unchanged)

`hallucinated_cards`, `triage_aux_unavailable`, `prose_phantom_refs`, `repeated_failures`, `repeated_crashes`, `stuck_in_blocked`, `stranded_in_ready`.

## Related

- Recovery drawer (reclaim / reassign): `kanban-worker` SKILL.md → "Recovering stuck workers" (orchestrator skill has the same section).
- Decompose workspace inheritance: `references/kanban-decompose-scratch-workspaces.md`.
