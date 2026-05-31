# Cursor attribution (commits and PRs)

Kanban workers and Hermes agents must not add tool branding to git commits or PR bodies. Cursor can still inject trailers automatically unless disabled.

## Symptoms

- Commit message includes `Co-authored-by: Cursor <...>` or `Made-with: Cursor` you did not write
- PR description ends with `Made with Cursor` or similar footer
- Not from the body the agent passed to `git commit` / `gh pr create` — added by Cursor agent/CLI

## Fix (user environment)

1. **Cursor IDE:** Settings → Agents → Attribution → turn off **Commit Attribution** and **PR Attribution**
2. **Cursor CLI:** In `~/.cursor/cli-config.json` set both to `false`:

```json
"attribution": {
  "attributeCommitsToAgent": false,
  "attributePRsToAgent": false
}
```

Restart Cursor or run `cursor /update-cli-config` so the CLI picks up changes. Enterprise teams may override local config via the admin dashboard.

## Agent behavior

- Write only task-relevant commit subjects/bodies and PR summary + test plan
- Do not append `Made with Hermes`, `Co-authored-by: Cursor`, or other agent/IDE trailers
- If the environment still injects a trailer after `git commit`, amend locally (`git commit --amend`) with the same message and no trailer, or ask the user to disable Commit Attribution
- Kanban **Create PR** worker context (`kanban_db.py`) and `KANBAN_GUIDANCE` repeat the same rule

## Already-open PRs / pushed commits

Editing `cli-config.json` does not rewrite existing PR descriptions or amend commits already on a remote — fix manually on GitHub or amend/rebase locally before push.
