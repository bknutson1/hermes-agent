# Kanban PR URL discovery

Use when a task card shows no PR badge, merge auto-complete does not fire, or you are writing implementer/review handoffs that reference a GitHub pull request.

## How the dashboard resolves a PR link

`hermes_cli.kanban_pr.find_pr_urls_for_tasks` builds `{task_id: pr_url}` in order:

1. **Comments** — newest `task_comments` row whose body contains `github.com/.../pull/`
2. **Runs** — up to **16** recent `task_runs` per task (newest first); first row where `_pr_url_from_run_row` finds a URL wins
3. **`tasks.result`** — legacy free-text field

Per run, `_pr_url_from_run_row` searches (in order): `summary`, `error`, then all string values in parsed `metadata` JSON.

Only strings matching `https://github.com/<owner>/<repo>/pull/<number>` count. **`PR: #181` or `PR #181` without a full URL is not parsed.**

## Implementer handoff (required for reliable badges)

On `kanban_complete` for worktree/dir tasks:

```python
metadata={
    "pr": "https://github.com/org/repo/pull/42",
    # ...
}
```

Also acceptable: full URL in the run `summary` (e.g. `shipped — PR: https://github.com/.../pull/42`).

## Review agent handoff (common pitfall)

Review runs often end with a **Code Review Summary** like `**PR:** #181 — fix widgets`. That is enough for humans and `gh pr view 181` in the repo cwd, but **not** for URL discovery if it is the newest run and no older run or comment has the full link.

**Do not** block review on repeating the full URL in every review comment unless the implementer omitted it everywhere — but **implementers** should always set `metadata.pr` once when opening the PR.

## Maintainer note (Hermes fork)

If discovery still fails when the latest run lacks a URL but an older implementer run has one, ensure `find_pr_urls_for_tasks` scans multiple runs (not only `rn = 1`) and includes `error` in `_pr_url_from_run_row`. Regression test: `tests/hermes_cli/test_kanban_pr.py::test_find_pr_url_from_older_run_when_latest_lacks_url`.
