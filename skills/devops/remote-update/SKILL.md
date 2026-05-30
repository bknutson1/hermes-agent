---
name: remote-update
description: >-
  Use when the user runs /remote-update — guide syncing their Hermes Agent fork
  with NousResearch/upstream via git fetch, pull, merge, conflict resolution,
  commit, and push (all in-terminal, no scripts).
version: 1.1.1
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [devops, git, fork, upstream, hermes-agent]
    related_skills: [hermes-fork-workflows]
---

# Remote update (fork sync)

## Overview

Sync the user's Hermes Agent **fork** with **upstream** (`NousResearch/hermes-agent`): fetch both remotes, fast-forward from `origin/main`, merge `upstream/main`, resolve conflicts in-chat, commit, and push to `origin/main`.

Invoked as **`/remote-update`**. Resume an in-progress merge with **`/remote-update finish`** (skip fetch; resolve → commit → push).

**Critical:** Perform every step yourself with the **terminal** tool (git commands) and **read/write** tools (conflicted files). **Do not** run any bundled script, `hermes remote-update`, or `python …/run_remote_update.py`. **Do not** delegate to a background process.

## Repository

1. Run `hermes --version` and use the `Project:` path as `REPO` (typically `C:/Users/tiger/AppData/Local/hermes/hermes-agent`).
2. All git commands: `cd "$REPO" && git …` (or Windows-equivalent).
3. Remotes required: **origin** (user's fork), **upstream** (`NousResearch/hermes-agent`, fetch only).

## Preconditions (check before mutating)

```bash
cd "$REPO" && git remote -v
cd "$REPO" && git status --porcelain
```

- If `origin` or `upstream` is missing → stop and tell the user how to add upstream.
- If working tree is dirty (and no merge in progress) → stop; list files; ask user to commit or stash.

## Mode A — full sync (`/remote-update`)

Execute in order. Report each step briefly to the user.

### 1. Resume or start

```bash
cd "$REPO" && test -f .git/MERGE_HEAD && echo MERGE_IN_PROGRESS || echo CLEAN
```

- **MERGE_IN_PROGRESS** → jump to [Conflict resolution](#conflict-resolution) then [Complete merge](#complete-merge).
- **CLEAN** → continue below.

### 2. Fetch (separate remotes — never `git fetch origin upstream`)

```bash
cd "$REPO" && git fetch origin
cd "$REPO" && git fetch upstream
```

### 3. Compare

```bash
cd "$REPO" && git rev-list --count origin/main..upstream/main
```

- **0** → tell user fork is already up to date with upstream; **stop**.
- **N > 0** → note N commits to merge; continue.

Verify refs exist:

```bash
cd "$REPO" && git rev-parse origin/main upstream/main
```

### 4. Checkout and pull from fork

```bash
cd "$REPO" && git checkout main
cd "$REPO" && git pull --ff-only origin main
```

### 5. Merge upstream

```bash
cd "$REPO" && git merge upstream/main -m "merge: sync fork with upstream/main" --no-edit
```

- **Clean merge** → go to [Complete merge](#complete-merge) (commit may already exist; still push).
- **Conflicts** → go to [Conflict resolution](#conflict-resolution).

## Mode B — finish only (`/remote-update finish`)

When `.git/MERGE_HEAD` exists and user asked to finish:

1. List conflicts: `git diff --name-only --diff-filter=U`
2. [Conflict resolution](#conflict-resolution)
3. [Complete merge](#complete-merge)

## Conflict resolution

List unmerged files:

```bash
cd "$REPO" && git diff --name-only --diff-filter=U
```

For **each** conflicted file:

1. **Read** the full file (read_file or `git show :path` / cat).
2. If binary or >512KB → stop; tell user to resolve manually.
3. **Resolve in your reasoning** using these rules (same intent as upstream Hermes fork merges):

   - Output the **complete resolved file** when writing — no `<<<<<<<` / `=======` / `>>>>>>>` markers.
   - **Keep** intentional fork-only changes (Kanban, LM Studio aux config, dashboard/plugins, Windows-specific fixes) when not clearly superseded by upstream.
   - **Prefer upstream** for bug fixes and refactors that replace obsolete fork patches.
   - Remove every conflict marker.

4. **Write** the resolved content (write_file / patch) and stage:

   ```bash
   cd "$REPO" && git add -- "<path>"
   ```

5. Confirm no unmerged paths remain:

   ```bash
   cd "$REPO" && git diff --name-only --diff-filter=U
   ```

**Upstream-only shortcut** (only if user explicitly asks to prefer upstream): per file `git checkout --theirs -- "<path>" && git add -- "<path>"`.

## Complete merge

```bash
cd "$REPO" && git status
```

If merge still in progress:

```bash
cd "$REPO" && git commit -m "merge: sync fork with upstream/main" --no-edit
```

(Use existing merge message if commit already created.)

Push fork:

```bash
cd "$REPO" && git push origin main
```

## Success

Tell the user that `origin/main` now includes the upstream changes.

## Failures

| Situation | Action |
|-----------|--------|
| `fetch` fails | Show stderr; check network / remote URLs |
| `couldn't find remote ref upstream` | User confused branch name with remote — verify `git remote -v` |
| `pull --ff-only` fails | Local main diverged; explain; do not force without user consent |
| Unresolved conflicts after your pass | List paths; user can fix manually or re-run `/remote-update finish` |
| `push` rejected | Show stderr; may need pull/rebase — ask user |

## Do not

- Run Python scripts, `hermes remote-update`, or `hermes_cli.remote_update`
- Use `git fetch origin upstream` (wrong — fetches a branch named `upstream` on origin)
- Suggest `/update` or `hermes update` after success — fork sync and local install refresh are separate; the user only asked to update `origin/main`
- Force-push without explicit user approval
- Skip reporting what you did at each major step
