---
name: hermes-fork-workflows
description: >-
  Use when syncing a Hermes Agent fork with NousResearch/upstream — remotes
  setup, merge conflicts, or pushing to origin after upstream changes.
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [devops, git, fork, upstream, hermes-agent]
    related_skills: [remote-update]
---

# Hermes fork workflows

## Remotes

- **origin** — your fork (`bknutson1/hermes-agent`)
- **upstream** — official repo (`NousResearch/hermes-agent`), fetch only

Repo: `C:/Users/tiger/AppData/Local/hermes/hermes-agent` (or `hermes --version` → `Project:`).

## One-shot sync: `/remote-update`

Run the **remote-update** skill from the TUI. The agent performs git steps directly (fetch, pull, merge, in-chat conflict resolution, commit, push) — **no scripts**.

```
/remote-update
/remote-update finish   # resume in-progress merge
```

Pipeline summary:

1. `git fetch origin` then `git fetch upstream` (separate — not `git fetch origin upstream`)
2. If `upstream/main` ahead of `origin/main`: checkout `main`, `git pull --ff-only origin main`, `git merge upstream/main`
3. On conflicts: agent reads each file, resolves markers, `git add`, commit, push
4. `git push origin main`

Details: `references/fork-remote-update-command.md`.

**Troubleshooting:** `couldn't find remote ref upstream` means Git looked for a branch named `upstream` on your fork (`origin`), not the `upstream` remote.

## Manual upstream merge

If you prefer to run git yourself:

```bash
cd ~/AppData/Local/hermes/hermes-agent
git fetch upstream && git checkout main && git pull origin main
git merge upstream/main
# resolve conflicts, git add, git commit, git push origin main
```
