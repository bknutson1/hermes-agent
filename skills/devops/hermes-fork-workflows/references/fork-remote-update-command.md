# Fork sync: `/remote-update` skill

Sync your fork's `origin/main` with `upstream/main` (NousResearch/hermes-agent).

## Invocation

| Surface | How |
|---------|-----|
| TUI / gateway / CLI chat | `/remote-update` |
| Resume merge | `/remote-update finish` |

The **remote-update** skill instructs the agent to run git in the terminal and resolve conflicts by editing files — not via a background script or `hermes_cli.remote_update`.

## Pipeline

1. `git fetch origin` then `git fetch upstream` (separate fetches)
2. Compare `origin/main..upstream/main`; exit early if 0 commits ahead
3. Clean working tree; `git checkout main`; `git pull --ff-only origin main`
4. `git merge upstream/main`
5. On conflicts: agent reads/writes each file, `git add`, then commit + `git push origin main`

## Troubleshooting

- **Repo path:** `hermes --version` → `Project:` (not the cwd where you invoked Hermes).
- **`couldn't find remote ref upstream`:** missing `upstream` remote or wrong fetch syntax.
- **Re-run while merge in progress:** `/remote-update finish` — do not re-fetch.

## Implementation note

`hermes_cli/remote_update.py` remains in the codebase for tests/reference but is **not** used by this skill.
