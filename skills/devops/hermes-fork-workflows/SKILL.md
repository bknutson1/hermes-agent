---
name: hermes-fork-workflows
description: >-
  Use when syncing a Hermes Agent fork with NousResearch/upstream — remote-update,
  merge conflicts, or pushing to origin after upstream changes.
---

# Hermes fork workflows

## Remotes

- **origin** — your fork (`bknutson1/hermes-agent`)
- **upstream** — official repo (`NousResearch/hermes-agent`), fetch only

Repo: `C:/Users/tiger/AppData/Local/hermes/hermes-agent` (or `hermes_cli.remote_update.default_hermes_repo_dir()`).

## One-shot sync: `/remote-update`

Run once — no manual steps:

```
hermes remote-update
# or /remote-update in gateway/TUI
```

Pipeline:

1. `git fetch origin` then `git fetch upstream` (not `git fetch origin upstream` — see `references/fork-remote-update-command.md` → Troubleshooting)
2. If `upstream/main` ahead of `origin/main`: pull origin, merge upstream
3. **On conflicts:** auxiliary LLM resolves each file (keeps intentional fork edits when appropriate)
4. Commit merge + `git push origin main`

Requires Hermes provider credentials (auxiliary LLM uses the same resolution chain as compression/web_extract).

Then refresh local install: `hermes update` or `/update`.

## Flags (optional)

| Flag | Effect |
|------|--------|
| `--conflict-resolution=llm` | Default — smart merge |
| `--conflict-resolution=upstream` | Blind `theirs` (loses fork edits) |
| `--conflict-resolution=none` | Stop on conflicts (exit 2) |
| `--finish` | Resume interrupted merge |
| `--repo PATH` | Non-default repo |

Details: `references/fork-remote-update-command.md`.

**Troubleshooting:** `couldn't find remote ref upstream` means Git looked for a branch named `upstream` on your fork (`origin`), not that the command ran in the wrong cwd. `hermes remote-update` always uses the Hermes install checkout (`hermes --version` → `Project:`).

## Manual upstream merge (no command)

Only if `remote-update` is unavailable:

```bash
cd ~/AppData/Local/hermes/hermes-agent   # or your checkout
git fetch upstream && git checkout main && git pull origin main
git merge upstream/main
# resolve conflicts, git add, git commit, git push origin main
```
