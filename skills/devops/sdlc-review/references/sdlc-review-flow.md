# SDLC review agent — full code review procedure

Loop and verdict rules: `review-loop-and-verdict.md`.

You are on a card that already has an implementer run with `outcome: submitted_for_review` in run history (or a **re-review** after `kanban_request_changes`).

## Orient

1. `kanban_show()` — AC in body, implementer `summary`/`metadata`, **all prior review comments**, parent handoffs, prior runs.
2. `cd $HERMES_KANBAN_WORKSPACE` — diff/PR live here for worktree tasks.
3. Confirm `HERMES_KANBAN_REVIEW=1` (review spawn). If unset, you are not the review agent.
4. **Load `github-code-review`** — mandatory every run; use its checklist and `references/review-output-template.md` for the `kanban_comment` body.

## Full code review (required before any transition)

Do not treat this as a quick AC gate. Minimum bar:

### 1. Map the change set

```bash
git diff main...HEAD --stat
git diff main...HEAD --name-only
git status
```

Union: all paths from `git diff`, `metadata.changed_files`, and PR file list (`gh pr diff N --name-only` if applicable). **Every path in that union must be reviewed.**

### 2. Read every changed file

For each changed file:

- `git diff main...HEAD -- <path>` for the delta.
- `read_file` (or equivalent) for **surrounding context** — diffs alone miss cross-file and call-site issues.

Large PRs: still cover every file; use `kanban_heartbeat` during long reads. If you cannot finish in one run, say so in the comment and `kanban_request_changes` with reason `code review: incomplete — N files remaining: …` — do **not** `kanban_block`.

### 3. Apply the github-code-review checklist

Work through **all** categories in `github-code-review` Section 3:

- Correctness (edge cases, error paths)
- Security (secrets, injection, authz, validation)
- Code quality (naming, DRY, complexity)
- Testing (new paths covered; failures reproduced)
- Performance (obvious N+1, blocking in async)
- Documentation (API/README if behavior changed)

Automated greps from `github-code-review` (TODO/FIXME, secrets patterns, conflict markers) on the full diff.

### 4. AC verification (in addition to code review)

| Check | How |
|-------|-----|
| AC satisfied | Map each AC bullet to evidence in diff/tests |
| Scope | No missing AC; call out drive-by files not in AC |
| PR exists / matches | `metadata.pr` or `gh pr view`; workspace matches PR head |
| Fork PR merge base | `git log origin/main..HEAD` — note extra commits in **Residual risk** for humans |
| Unstaged out-of-scope edits | `git status` — local experiments not in PR (see godot balance note below) |
| Prior review findings | On re-review, each earlier Critical/Warning verified fixed |

### 5. Tests — re-run, do not trust handoff counts

- Re-run **every** test command or module list the implementer cited in `metadata` / `summary`.
- Add tests for changed areas if handoff omitted them and AC implies coverage → **Warning** if missing.
- Record exact commands and pass/fail counts in the review comment.

See platform sections below for pytest/unittest/Godot specifics.

### 6. Write the comment (before transition)

Use `github-code-review` → `references/review-output-template.md`:

- **Verdict: Changes Requested** if any Critical or Warning.
- **Verdict: Approved** only if zero Critical and zero Warning.

Include: files reviewed count, tests re-run, AC mapping, **full PR URL** on the **PR:** line (`https://github.com/.../pull/N` — see `github-code-review` → `references/review-output-template.md`), residual risk (human merge caveats only — not a bucket for code defects).

## Hand off

**Changes Requested** (any Critical or Warning):

```python
kanban_comment(body="<Code Review Summary from template — full findings>")
kanban_request_changes(
    reason="code review: <N> critical, <M> warning — see latest review comment",
)
```

Card returns to **ready**; implementer fixes and calls `kanban_complete` again → **review** → you run again.

**Approved** (zero Critical, zero Warning):

```python
kanban_comment(body="<Code Review Summary — Verdict: Approved>")
kanban_block(
    reason="review-required: code review approved — <AC one-liner>, tests re-run, PR #N ready for human merge",
)
```

Post the comment **before** `kanban_request_changes` or `kanban_block`.

Optional: leave a GitHub PR comment or `gh pr review` when a PR exists — Kanban comment is still required.

## Platform notes

### Targeted pytest (hermes-agent / dir workspaces)

Re-run implementer-cited tests **and** any test files touched by the diff. Clear isolation on Windows:

```bash
python -m pytest tests/path/test_foo.py -q -o addopts=
```

**Review spawn env:** Unset `HERMES_KANBAN_REVIEW` before re-running tests that assert implementer redirect behavior:

```bash
unset HERMES_KANBAN_REVIEW   # bash
```

**Env vs AC:** Missing optional module when AC does not require that integration → note under residual risk, do not fail review. If AC requires the integration and tests fail → **Warning** or **Critical** → `kanban_request_changes`.

### RoguelikeTD Godot static unittest bundles

1. Re-run the **named module list** from metadata — do not trust counts without evidence.
2. Windows: clear `PYTHONHOME` / `PYTHONPATH`; use system Python if uv breaks stdlib.
3. **Godot GDScript gates (mandatory)** — if **any** path in the review union matches `Scripts/**/*.gd`, follow `references/rogueliketd-godot-gdscript-review-gates.md`:
   - Gate 1: `godot --headless --path . --quit-after 1` (exit `0`). Skipping → **Critical**.
   - Gate 4: `godot --headless --path . --script tests/godot/sdlc_parse_smoke.gd` when that file exists — parses all `Scripts/**/*.gd`, including lazy-loaded effect scripts. Skipping when present → **Critical**. Also run `tests.test_gdscript_const_init_static` when present.
   - Gate 2: grep tower subclass shadow `var` redeclarations.
   - Gate 3: re-run `tests.test_tower_subclass_gdscript_static` when present.
   - Record `godot_headless_exit` and `godot_parse_smoke_exit` in the review comment.
4. Unstaged `*Curve.tres` not in PR → residual risk unless AC required those files.
5. **Deferred AC** only when task body or `metadata.acceptance` explicitly defers — otherwise missing deferred work is a **Warning** (or Critical if AC-required).

### Dir workspace without PR metadata

Uncommitted `git status` is residual risk for human merge — **Warning** if AC required a PR and none exists.

### Kanban dashboard API slimming

Re-run cited tests in `tests/plugins/test_kanban_dashboard_plugin.py` with `-o addopts=`. Verify list vs detail contract per `kanban-worker` → `references/kanban-dashboard-board-performance.md`.

## Implementer handoff quirks

- Only `metadata.review_waived: true` on `kanban_complete` bypasses Review — not narrative in `decisions` or summary.
- `metadata.decisions` is context only, not kernel flags.

## Common mistakes

| Mistake | Why it fails |
|---------|----------------|
| `kanban_block` with open Critical/Warning | Skips the fix loop — use `kanban_request_changes` |
| `kanban_complete` | Tool error on review runs |
| Spot-check / AC-only pass | Violates full code review mandate |
| Approve after `--quit-after 1` only on `.gd` diff | Misses lazy-loaded scripts — run `sdlc_parse_smoke.gd` when present |
| `gh pr merge` | Out of scope unless task orders merge |
| Re-implementing | `kanban_request_changes`; implementer picks up from `ready` |
| Empty `kanban_block` reason | Use `review-required:` prefix |

## After you block

Card is `blocked` until a human merges the PR and marks done or unblocks.
