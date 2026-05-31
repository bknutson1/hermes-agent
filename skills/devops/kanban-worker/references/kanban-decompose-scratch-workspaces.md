# Kanban decompose — workspace inheritance (scratch / dir / worktree)

Use when a triage card was decomposed and children have unexpected workspaces, or when parallel cards must merge back into the game repo.

## What decompose actually does

`decompose_triage_task` **copies the triage parent's** `workspace_kind` (and related fields) onto every child:

| Parent `workspace_kind` | Each child gets |
|-------------------------|-----------------|
| `scratch` (default) | `scratch` — isolated board folder, provisioned at claim |
| `dir` | same `workspace_path` as parent (shared tree) |
| `worktree` | same `workspace_path`, `branch_name`, and `base_branch` as parent (one feature checkout; defaults `.worktrees/<parent_id>` and `wt/<parent_id>` when unset) |

Set workspace on the **triage** card before decomposing (`hermes kanban` workspace picker or DB update while still in triage).

**Scratch-specific implications** (when parent was scratch or default):

- Children are **not** git branches under the project repo.
- Each scratch path lives under the board data dir, e.g.:
  - Windows: `%LOCALAPPDATA%\hermes\kanban\boards\<slug>\workspaces\t_<child_id>/`
  - Linux/macOS: `~/.local/share/hermes/kanban/boards/<slug>/workspaces/t_<child_id>/`
- Dispatcher sets `HERMES_KANBAN_WORKSPACE` and `TERMINAL_CWD` to that folder for each run.
- Nothing automatically copies the app repo into scratch; nothing auto-merges scratch output back to `default_workdir`.

**Worktree decompose:** children share the parent's branch and checkout path (not scratch). Parallel lanes without parent links can stomp the same tree — link dependencies when work must serialize. Integration still needs an explicit merge/integrator card when lanes are independent branches.

## Ephemeral scratch lifecycle (cleanup + handoffs)

On `kanban_complete`, scratch workspaces are `rmtree`'d (best-effort). Durable handoffs are `summary` + `metadata` on the run row and **Parent task results** injected when the parent becomes `ready`. Board logs under `kanban/boards/<slug>/logs/t_<id>.log` are a fallback.

## How to merge parallel children

There is **no** Kanban step that combines scratch workspaces. Read child handoffs, apply in the real repo manually, or spawn a **`worktree`** integrator card with `parents=[all children]`.

## Recommended shapes

**Planning decompose (scratch parent):** triage → decompose → N × scratch → parent synthesizes → promote worktree implement cards.

**Parallel code (worktree parent):** set `workspace=worktree` + branch on triage before decompose → N children on the same branch → integrator with `parents=[...]` when needed.

**Custom branch names:** use orchestrator `kanban_create(..., workspace=worktree)` fan-out instead of decompose.

## Related

- `kanban-orchestrator` — decomposition playbook and RoguelikeTD batch patterns
- `kanban-worker` → `references/kanban-review-column.md` — Review column vs reviewer task
