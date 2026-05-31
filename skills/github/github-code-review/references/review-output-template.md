# Review Output Template

Use this as the structure for PR review summary comments. Copy and fill in the sections.

## For PR Summary Comment

```markdown
## Code Review Summary

**Verdict: [Approved ✅ | Changes Requested 🔴 | Reviewed 💬]** ([N] issues, [N] suggestions)

**PR:** https://github.com/[owner]/[repo]/pull/[number] — [title]
**Author:** @[username]
**Files changed:** [N] (+[additions] -[deletions])

### 🔴 Critical
<!-- Issues that MUST be fixed before merge -->
- **file.py:line** — [description]. Suggestion: [fix].

### ⚠️ Warnings
<!-- Issues that SHOULD be fixed, but not strictly blocking -->
- **file.py:line** — [description].

### 💡 Suggestions
<!-- Non-blocking improvements, style preferences, future considerations -->
- **file.py:line** — [description].

### ✅ Looks Good
<!-- Call out things done well — positive reinforcement -->
- [aspect that was done well]

---
*Reviewed by Hermes Agent*
```

## Severity Guide

| Level | Icon | When to use | Blocks merge? |
|-------|------|-------------|---------------|
| Critical | 🔴 | Security vulnerabilities, data loss risk, crashes, broken core functionality | Yes |
| Warning | ⚠️ | Bugs in non-critical paths, missing error handling, missing tests for new code | Usually yes |
| Suggestion | 💡 | Style improvements, refactoring ideas, performance hints, documentation gaps | No |
| Looks Good | ✅ | Clean patterns, good test coverage, clear naming, smart design decisions | N/A |

## Verdict Decision

- **Approved ✅** — Zero critical/warning items. Only suggestions or all clear.
- **Changes Requested 🔴** — Any critical or warning item exists.
- **Reviewed 💬** — Observations only (draft PRs, uncertain findings, informational).

## For Inline Comments

Prefix inline comments with the severity icon so they're scannable:

```
🔴 **Critical:** User input passed directly to SQL query — use parameterized queries to prevent injection.
```

```
⚠️ **Warning:** This error is silently swallowed. At minimum, log it.
```

```
💡 **Suggestion:** This could be simplified with a dict comprehension:
`{k: v for k, v in items if v is not None}`
```

```
✅ **Nice:** Good use of context manager here — ensures cleanup on exceptions.
```

## PR URL (required for Kanban)

When the summary is posted via `kanban_comment` (SDLC review on the Hermes Kanban board), the **PR:** line must include the full `https://github.com/.../pull/N` URL — not only `#N` or `PR #N`. The dashboard **PR Status** widget discovers links from comments and run history; a number alone is not enough.

Copy the URL from the implementer handoff (`metadata.pr`, `metadata.pr_url`, prior run summary), from `gh pr view <N> --json url --jq .url`, or from the PR the user linked. If no PR exists yet, omit the **PR:** line and say so in the verdict section.

## For Local (Pre-Push) Review

When reviewing locally before push, use the same structure but present it as a message to the user instead of a PR comment. Skip the PR metadata header and just start with the severity sections.
