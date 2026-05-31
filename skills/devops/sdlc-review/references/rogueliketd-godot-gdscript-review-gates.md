# RoguelikeTD: Godot GDScript review gates (SDLC review agent)

Use on **every** Kanban review run where the diff touches `Scripts/**/*.gd` or attaches new scripts under `Scenes/**/*.tscn`.

## Why this exists

RoguelikeTD ships many **grep-only** static tests (`tests/test_*_static.py`). They never compile GDScript. Implementers can report 8/8 or 12/12 unittest passes while the project has a **parse error** that blocks the Godot editor and in-game playtest.

Recurring failure when adding tower archetypes:

```
Parse Error: The member "_enemy_registry" already exists in parent class Tower.
ERROR: Failed to load script "res://Scripts/Towers/<new>_tower.gd"
```

## Gate 1 — Godot headless load (necessary, not sufficient)

`--quit-after 1` only boots the **main scene** and **autoloads**. It does **not** parse scripts loaded later via `preload()` on tower/archetype paths (e.g. `Scripts/Effects/frost_slow_aura.gd` pulled in when Frost Obelisk spawns an aura). Those can pass Gate 1 and still **crash on run start** with a parse error.

**Frost Obelisk case (2026-05):** review approved handoff `2225f5e` with “headless exit 0” while `const FALL_DIR = Vector2(-1.0, 1.0).normalized()` in `frost_slow_aura.gd` was invalid — game crashed when the effect script first loaded. Gate 4 would have caught it.

From repo root (`$HERMES_KANBAN_WORKSPACE`):

**Windows (git-bash / Hermes terminal):**

```bash
GODOT="${GODOT:-$(ls -1 /c/Godot/Godot_*_console.exe 2>/dev/null | tail -1)}"
if [ -z "$GODOT" ] || [ ! -x "$GODOT" ]; then
  GODOT="$(command -v godot 2>/dev/null || true)"
fi
"$GODOT" --headless --path . --quit-after 1 2>&1 | tee /tmp/godot-headless-review.log
echo "exit=$?"
```

**PowerShell (Cursor Shell):**

```powershell
$godot = $env:GODOT
if (-not $godot) { $godot = (Get-Command godot -ErrorAction SilentlyContinue).Source }
& $godot --headless --path . --quit-after 1
```

**Pass criteria:** exit code `0`. **Fail → Critical** → `kanban_request_changes` if stderr contains any of:

- `Parse Error`
- `Failed to load script`
- `already exists in parent class`
- `SCRIPT ERROR`

Do **not** list a failed headless run as residual risk. Do **not** approve based on unittest counts alone when `.gd` files changed.

Record in the review comment: exact Godot binary path, exit code, and whether stderr was clean.

## Gate 2 — Tower subclass shadow members (Critical)

`Tower` (`Scripts/Towers/tower.gd`) already owns private state subclasses must **reuse**, not redeclare.

| Member | Notes |
|--------|--------|
| `_enemy_registry` | Most common duplicate — lazy-init in methods like `tesla_coil_tower.gd`, not `var` in subclass |
| `_range_area` | Collision range |
| `_range_shape` | |
| `_current_target` | |
| `_manual_target_node` | |
| `_has_manual_target` | |
| `_mouse_target_node` | |
| `_is_selected` | |
| `_cooldown_remaining` | |
| `_base_range_pixels` | |
| `_was_debug_enabled` | |
| `_stats_dirty` | |
| `_pending_modifier_hits` | |
| `_modifier_indicator` |

For each **new or changed** `Scripts/Towers/*_tower.gd` with `extends Tower`:

```bash
git diff main...HEAD --name-only -- 'Scripts/Towers/*_tower.gd'
# For each path:
grep -nE '^var _(enemy_registry|range_area|range_shape|current_target|manual_target_node|has_manual_target|mouse_target_node|is_selected|cooldown_remaining|base_range_pixels|was_debug_enabled|stats_dirty|pending_modifier_hits|modifier_indicator)\b' -- "$path"
```

Any match in a subclass → **Critical** (remove the line; use parent's field or lazy-init inside a method).

**Reference implementation:** `Scripts/Towers/tesla_coil_tower.gd` — uses `_enemy_registry` without redeclaring it.

## Gate 3 — Static unittest (re-run on review)

When present in the repo:

```bash
export PYTHONHOME= PYTHONPATH=
"$LOCALAPPDATA/Programs/Python/Python312/python.exe" -m unittest tests.test_tower_subclass_gdscript_static -v
```

Add pass/fail to the review comment. If the module is missing on an old branch, rely on Gate 1 + Gate 2 + Gate 4.

## Gate 4 — Parse all Scripts + const-init static (Critical if skipped)

When **any** path in the review union matches `Scripts/**/*.gd` (including `Scripts/Effects/*.gd`, not only `Scripts/Towers/`):

### 4a. Godot parse smoke (preferred)

If `tests/godot/sdlc_parse_smoke.gd` exists in the repo:

```bash
"$GODOT" --headless --path . --script tests/godot/sdlc_parse_smoke.gd 2>&1 | tee /tmp/godot-parse-smoke.log
echo "parse_smoke_exit=$?"
```

**Pass:** exit `0` **and** stderr has no `SCRIPT ERROR`, `Parse Error`, `PARSE FAIL`, or `Too many arguments for "load()"`. **Fail → Critical** (records which script failed to parse).

**Windows:** Prefer `Godot_*_console.exe` (not the GUI `godot.exe`) so `parse_smoke_exit` matches `quit(code)`. The GUI build can return exit `0` even when `sdlc_parse_smoke.gd` itself fails to load — always read the log, not only `$?`.

**Smoke script API (Godot 4.5):** `ResourceLoader.load(path, type_hint, cache_mode)` — three arguments only. Do not pass an `Error` out-param; GDScript bindings reject a 4th argument and the harness never runs.

### 4b. Const-init static unittest

When present:

```bash
export PYTHONHOME= PYTHONPATH=
"$LOCALAPPDATA/Programs/Python/Python312/python.exe" -m unittest tests.test_gdscript_const_init_static -v
```

Catches illegal patterns such as `const FALL_DIR = Vector2(-1.0, 1.0).normalized()` before playtest.

### 4c. Review scope

- Include **every** changed `.gd` in the diff union — effect/VFX scripts count (`Scripts/Effects/`, `Scripts/UI/`, etc.).
- When a tower `preload()`s a new scene, read that script too even if only the tower file appears in `git diff --stat`.

**Do not approve** RoguelikeTD `.gd` diffs with only Gate 1 + tower static tests. Gate 4 is mandatory on modern branches that ship `sdlc_parse_smoke.gd`.

## Severity

| Finding | Severity |
|---------|----------|
| Headless not run but `.gd` in diff | **Critical** (review incomplete) |
| Headless failed / parse error in stderr | **Critical** |
| Parse smoke not run but `sdlc_parse_smoke.gd` exists | **Critical** (incomplete review) |
| Parse smoke failed | **Critical** |
| `test_gdscript_const_init_static` failed | **Critical** |
| Subclass redeclares `Tower` private `var` | **Critical** |
| Gate 1 passed only; lazy-loaded script has parse error | **Critical** (false confidence) |
| Headless passed; only `.tres` string drift | Usually residual risk (see `godot-tres-serialization-static-tests.md`) |

## Archetype cards

Archetype implement/integration checklists live in `godot-combat-modifiers` (e.g. `rogueliketd-mortar-battery-archetype-ship.md`). Implementer fix pattern and test commands: `godot-combat-modifiers` → `references/tower-subclass-gdscript-static.md`. Those docs assume **this gate** ran during SDLC review — they are not a substitute for headless load.
