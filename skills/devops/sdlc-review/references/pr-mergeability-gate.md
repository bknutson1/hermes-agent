# PR mergeability gate (SDLC review)

When an open GitHub PR exists (`metadata.pr`, implementer handoff, or task comments), verify it can **merge cleanly into the target/base branch** before **Verdict: Approved**.

The review agent does **not** resolve conflicts or push — request changes so the implementer merges base into head and pushes.

## 1. GitHub check (preferred)

```bash
# N from full PR URL; run from repo root with gh authenticated
gh pr view N --json url,baseRefName,headRefName,mergeable,mergeStateStatus \
  --jq '{url, base:.baseRefName, head:.headRefName, mergeable, mergeStateStatus}'
```

| Signal | Meaning | Review action |
|--------|---------|---------------|
| `mergeable: MERGEABLE` and `mergeStateStatus` is `CLEAN`, `HAS_HOOKS`, or `UNSTABLE` | No merge conflicts with base (CI may still be red) | Pass merge gate |
| `mergeable: CONFLICTING` or `mergeStateStatus: DIRTY` | Conflicts with base | **Warning** → `kanban_request_changes` |
| `mergeStateStatus: BEHIND` | Head is behind base | **Warning** unless you confirm a clean merge locally (step 2) |
| `mergeable: UNKNOWN` | GitHub still computing | Re-run once; if still unknown, use step 2 |

Record the result on the **Merge status:** line in the Code Review Summary (see `github-code-review` → `references/review-output-template.md`).

## 2. Local confirmation (ambiguous gh, or no gh)

From `$HERMES_KANBAN_WORKSPACE` on the PR head branch:

```bash
BASE=main   # use baseRefName from gh pr view, or task base_branch metadata
git fetch origin "$BASE"
git merge-tree "$(git merge-base HEAD "origin/$BASE")" HEAD "origin/$BASE" | head -80
```

Conflict indicators in output (`changed in both`, conflict markers) → not cleanly mergeable.

**Do not** leave conflict markers in the tree for approval. If you used a mutating probe (`git merge origin/$BASE`), abort before continuing review: `git merge --abort`.

## 3. Verdict and implementer fix

**Not cleanly mergeable** → list under **⚠️ Warnings** (blocks Approved):

- **PR mergeability** — PR cannot merge cleanly into `<base>` (`mergeable` / `mergeStateStatus` or local `merge-tree` shows conflicts).

**Required fix (implementer):** on the PR head branch:

```bash
git fetch origin <base>
git merge origin/<base>    # merge target INTO feature branch — not rebase unless task orders rebase
# resolve <<<<<<< markers in conflicted files
git add <resolved>
git commit                 # merge commit is fine
# re-run cited tests
git push
```

Then `kanban_complete` again. Do **not** open a duplicate PR.

## 4. Skip conditions

- No PR URL in handoff and AC does not require one → note `Merge status: n/a (no PR)` in comment.
- Task body says PR is draft-only / not opened yet → **Warning** if AC required an open mergeable PR.

## 5. Re-review

After a prior `kanban_request_changes` for merge conflicts, re-run step 1 (and step 2 if needed) before Approved — do not assume push fixed it without checking.
