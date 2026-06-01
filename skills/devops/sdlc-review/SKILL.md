---
name: sdlc-review
description: Full code review on Kanban Review column — loop via kanban_request_changes until clean, then review-required block for human merge. Never merge autonomously.
version: 2.0.2
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [kanban, review, sdlc, pr]
    related_skills: [kanban-worker, github-code-review, requesting-code-review]
---

# SDLC Review Agent

You were spawned from the Kanban **Review** column (`HERMES_KANBAN_REVIEW=1`). The implementer called `kanban_complete`; the kernel moved the card to `review` with run outcome `submitted_for_review`. Read that handoff in `kanban_show` before reviewing.

Full procedure: `references/sdlc-review-flow.md`. Review loop and verdict rules: `references/review-loop-and-verdict.md`.

## Your job: full code review (not a light AC check)

Perform a **complete code review** of every change in scope — same bar as `github-code-review` Section 3 (correctness, security, quality, tests, performance, docs). **Load `skill_view(name='github-code-review')` at the start of every review run** and follow its checklist and output template (`references/review-output-template.md`).

This is an **automated review loop** before human merge:

```
implementer kanban_complete → review → YOU
  → issues found?  kanban_comment + kanban_request_changes → ready (implementer fixes, re-submits)
  → repeat until Verdict: Approved (zero Critical, zero Warning)
  → decomposed subtask (default): kanban_comment + kanban_complete → done
  → epic root / standalone: kanban_comment + kanban_block(review-required:…) → blocked
```

When `kanban.defer_human_review_to_decompose_root` is true (default), **decomposed child** cards (created by `kanban decompose`) must **`kanban_complete` to done** after Approved — not `review-required` block. Human merge/sign-off is on the **epic root** when the graph finishes. `kanban_block(review-required:…)` on a subtask is auto-converted to done by the kernel.

Do **not** `kanban_block(review-required:…)` while any Critical or Warning remains. Suggestions alone do not block the loop.

On **re-review** (card returned from a prior `kanban_request_changes`), verify every prior finding is fixed in the current diff; reopen or add findings if not.

## Hard rules

- **Do not merge PRs** (`gh pr merge`, squash, rebase) unless the task body explicitly instructs you to merge a specific PR.
- **Do not call `kanban_complete`** — rejected for review runs.
- **Do not implement fixes** unless the task body explicitly says the review agent should patch code.
- **Do not push** to protected branches or mark the card `done`.
- **Do not pass with “residual risk”** for defects you would flag as Critical or Warning in a human PR review — use `kanban_request_changes` instead.

## Workflow

1. `kanban_show()` — AC, implementer `summary`/`metadata`, prior review comments, parent handoffs.
2. `cd $HERMES_KANBAN_WORKSPACE` — full review on the current tree (see flow doc).
3. **Full code review** — every changed file; re-run cited tests; AC + quality bar (flow doc). When a PR exists, run **`references/pr-mergeability-gate.md`** before Approved.
4. `kanban_comment` with **Code Review Summary** (template) — **before** any status transition.
5. Verdict:
   - **Changes Requested** (any Critical or Warning) → `kanban_request_changes(reason="code review: …")` — one-line reason; details in comment.
   - **Approved** (zero Critical, zero Warning) → decomposed subtask: `kanban_complete(summary=…)`; epic root / standalone: `kanban_block(reason="review-required: …")`.

## What not to do

| Wrong | Right |
|-------|-------|
| `kanban_complete` → done on subtasks | `kanban_block(review-required:…)` on epic root / standalone after Approved |
| `kanban_block` with open Critical/Warning | `kanban_request_changes` → loop until clean |
| Spot-check only / trust implementer test counts | Re-run cited tests; read every changed file |
| `gh pr merge` by default | Human merges after `review-required` block |
| Re-implement the feature | Comment + `kanban_request_changes` |

## RoguelikeTD: Godot GDScript gates (mandatory when diff touches `.gd`)

**Before Approved** when any changed path matches `Scripts/**/*.gd`:

1. **Gate 1** — `--headless --quit-after 1` (exit `0`). **Not sufficient alone** — does not parse lazy-loaded effect scripts.
2. **Gate 4** — `--script tests/godot/sdlc_parse_smoke.gd` when present; `tests.test_gdscript_const_init_static` when present. Skipping Gate 4 when smoke script exists → **Critical**.
3. **Gate 2** — tower subclass shadow `var` grep. **Gate 3** — `test_tower_subclass_gdscript_static`.

Frost Obelisk miss: `const FALL_DIR = Vector2(-1,1).normalized()` in `frost_slow_aura.gd` passed Gate 1, crashed at run start. Details: `references/rogueliketd-godot-gdscript-review-gates.md`.

## Reference

- `references/sdlc-review-flow.md` — orient, full review steps, platform notes, handoff
- `references/pr-mergeability-gate.md` — PR merges cleanly into base; request changes to merge base into head when conflicted
- `references/review-loop-and-verdict.md` — loop diagram, severity → action, re-review rules
- `references/rogueliketd-godot-gdscript-review-gates.md` — Gates 1–4 (headless, parse smoke, tower grep, static tests)
