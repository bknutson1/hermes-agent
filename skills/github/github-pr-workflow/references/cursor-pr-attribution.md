# Cursor PR attribution ("Made with Cursor")

Kanban workers and Hermes agents must not add tool branding to PR bodies. Cursor can still inject it automatically unless disabled.

## Symptoms

- PR description ends with `Made with Cursor` or similar footer
- Not from `gh pr create` body the agent wrote — added by Cursor agent/CLI

## Fix (user environment)

1. **Cursor IDE:** Settings → Agents → Attribution → turn off **PR Attribution**
2. **Cursor CLI:** In `~/.cursor/cli-config.json` set:

```json
"attribution": {
  "attributeCommitsToAgent": true,
  "attributePRsToAgent": false
}
```

Restart Cursor or run `cursor /update-cli-config` so the CLI picks up changes.

## Agent behavior

- Use only task summary + test plan in `gh pr create --body` / `--body-file`
- Do not append `Made with Hermes`, co-authored-by agent trailers, or IDE footers
- Kanban **Create PR** worker context (`kanban_db.py`) and `KANBAN_GUIDANCE` repeat the same rule

## Already-open PRs

Editing `cli-config.json` does not rewrite existing PR descriptions — remove the line manually on GitHub.
