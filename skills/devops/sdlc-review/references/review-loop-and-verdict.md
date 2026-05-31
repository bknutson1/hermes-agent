# Review loop and verdict rules

## Loop (kernel + your tools)

```
ready/running (implementer)
  → kanban_complete(handoff)
  → review                    # submitted_for_review
  → running (you, HERMES_KANBAN_REVIEW=1, sdlc-review skill)
  → ready                     # kanban_request_changes — implementer addresses findings
  → … implementer fixes, kanban_complete again …
  → review → running (you again)
  → blocked                   # kanban_block(review-required:…) — ONLY when Approved
  → human merge / unblock / done
```

The same card id cycles **review ↔ ready** until you approve. Each return to `ready` should leave a durable fix list in `kanban_comment` so the implementer knows what to change.

## Verdict → Kanban action

| Verdict | Critical | Warning | Action |
|---------|----------|---------|--------|
| **Changes Requested** | ≥ 1 | any | `kanban_comment` (full summary) → `kanban_request_changes` |
| **Changes Requested** | 0 | ≥ 1 | same |
| **Approved** | 0 | 0 | `kanban_comment` (full summary) → `kanban_block(review-required:…)` |

**Suggestions (💡)** alone never trigger `kanban_request_changes`. Mention them in the comment; implementer may address optionally before human merge.

Use severity definitions from `github-code-review` → `references/review-output-template.md`.

## Re-review after request_changes

When `kanban_show` shows a prior review comment with Critical/Warning items:

1. Confirm each item is **fixed in the current workspace diff** (not merely claimed in summary).
2. If still present → list again (reference prior comment date/id if visible).
3. Run a **fresh full review** on the whole change set — fixes can introduce regressions.
4. Do not `kanban_block` until the new pass is Approved.

## Comment before transition (always)

Post the structured **Code Review Summary** via `kanban_comment` **before** `kanban_request_changes` or `kanban_block`. The `reason` on those tools is a one-line dashboard label; the comment is the authoritative fix list / approval record. The **PR:** header must include the full `https://github.com/.../pull/N` URL so the dashboard **PR Status** row can link the task.

## `kanban_request_changes` reason line

Keep short and actionable, e.g.:

```
code review: 2 critical (SQL injection auth.py:45, missing test for logout); 1 warning (swallowed error in api/routes.py:112)
```

## `kanban_block` reason line (Approved only)

Prefix required for dashboard filtering:

```
review-required: code review approved — AC met, 14/14 tests re-run, PR #123 ready for human merge
```

## What humans still do

Automated review does **not** replace the human reading the PR. After `review-required` block, a human merges (or unblocks). Your Approved verdict means “no blocking code-review issues found by the agent” — not “ship without human eyes.”

## Bypass paths (no review loop)

- `scratch` workspace → implementer goes straight to `done`
- `metadata.review_waived: true` on `kanban_complete`
- `kanban.allow_complete_without_review: true` in config
