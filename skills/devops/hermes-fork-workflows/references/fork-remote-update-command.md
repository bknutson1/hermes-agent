# Fork sync: `/remote-update` and `hermes remote-update`

Fork-only command (not in upstream NousResearch Hermes). **One run** syncs your fork's `origin/main` with `upstream/main` before `/update` or `hermes update`.

## Pipeline (default: `conflict_resolution=llm`)

1. Fetch both remotes: `git fetch origin` then `git fetch upstream` (not a single `git fetch origin upstream` — see Troubleshooting)
2. Compare `upstream/{branch}` vs `origin/{branch}` (default `main`)
3. If upstream is not ahead → report up to date
4. Else (clean working tree required):
   - `git checkout {branch}`, `git pull --ff-only origin {branch}`
   - `git merge upstream/{branch}`
   - **On conflicts:** auxiliary LLM resolves each UTF-8 text file via `agent.auxiliary_client` (task `compression`); keeps fork-only behavior when appropriate; removes all conflict markers; `git add` each file
   - Commit merge + `git push origin {branch}`

No `--finish` step unless resuming an interrupted merge.

Core module: `hermes_cli/remote_update.py` (`run_remote_update`, `finish_remote_update`, `DEFAULT_CONFLICT_RESOLUTION = "llm"`).

## How to invoke

| Surface | Command |
|---------|---------|
| Gateway / TUI | `/remote-update` |
| Terminal | `hermes remote-update` |

Resume interrupted merge: `hermes remote-update --finish` or `/remote-update finish`.

## Conflict resolution modes

| Mode | Flag | Behavior |
|------|------|----------|
| `llm` | default | Auxiliary model merges per file intelligently |
| `upstream` | `--prefer-upstream` or `--conflict-resolution=upstream` | Blind `git checkout --theirs` (**loses fork edits**) |
| `none` | `--conflict-resolution=none` | Stop with exit 2; merge left in progress for manual/agent chat resolution |

Other CLI flags: `--repo PATH`, `--branch NAME`.

Exit codes: `0` success/up-to-date, `1` failure, `2` conflicts (`none` mode only).

## vs `/update`

| | `/remote-update` | `/update` |
|---|------------------|-----------|
| Target | GitHub fork (`origin`) | Local Hermes install |
| Action | Merge upstream into fork, push | Pull from origin, deps, restart |
| Order | **First** | **Second** |

## Requirements

- Remotes: `origin` (fork, push allowed), `upstream` (NousResearch, push disabled)
- Clean working tree before a **new** sync
- Push access to `origin`
- LLM credentials for default `llm` mode (same auxiliary chain as compression / Kanban aux JSON)

## Auxiliary LLM chain (`llm` mode)

Per-file merge resolution calls `agent.auxiliary_client.call_llm` with **`task="compression"`** — not `vision` and not the main agent loop.

Typical `~/.hermes/config.yaml` on this fork:

```yaml
auxiliary:
  compression:
    provider: auto
    model: ''
    timeout: 120
```

With `provider: auto`, step 1 is the **main session** (`model.provider: cursor` → Composer 2.5 via `CursorAuxiliaryClient` / `cursor://sdk`, `CURSOR_API_KEY`). It does **not** use `auxiliary.vision.base_url` (LM Studio at `127.0.0.1:1234`) unless you pin compression explicitly.

Fallback when Cursor is missing, times out, or is marked unhealthy (in order):

1. OpenRouter (`OPENROUTER_API_KEY`)
2. Nous Portal (`~/.hermes/auth.json`)
3. Custom / `OPENAI_BASE_URL`
4. Other API-key providers in the auto chain

Pin local merge resolution instead:

```yaml
auxiliary:
  compression:
    provider: custom
    base_url: http://127.0.0.1:1234/v1
    model: qwen/qwen3.6-35b-a3b
```

Runtime check (from Hermes venv):

```bash
python -c "
import sys; sys.path.insert(0, 'path/to/hermes-agent')
from agent.auxiliary_client import _get_cached_client
c, m = _get_cached_client('auto', task='compression')
print(type(c).__name__, m, getattr(c, 'base_url', None))
"
```

## Troubleshooting

### `fatal: couldn't find remote ref upstream`

- **Not wrong cwd.** `hermes remote-update` runs in `default_hermes_repo_dir()` (package root next to `hermes_cli/remote_update.py`), overridable with `--repo PATH` — not the directory where you invoked the command. Confirm with `hermes --version` (`Project:` line).
- **Cause:** `git fetch origin upstream` asks remote **`origin`** (your fork) for a ref named **`upstream`**. Typical forks only have `main` on origin; NousResearch is remote **`upstream`**, branch **`main`** (`upstream/main`).
- **Workaround until code is fixed:**
  ```bash
  cd C:/Users/tiger/AppData/Local/hermes/hermes-agent   # or your install checkout
  git fetch origin
  git fetch upstream
  git checkout main
  git pull --ff-only origin main
  git merge upstream/main
  # resolve conflicts, then:
  git push origin main
  ```
  Then `hermes update` for the local install.
- **Code fix:** in `hermes_cli/remote_update.py`, replace `["fetch", "origin", "upstream"]` with separate `fetch origin` and `fetch upstream` calls.

## Pitfalls

- **`git fetch origin upstream` is wrong** — documented above; reproduces `couldn't find remote ref upstream` on standard fork layouts.
- **Do not default to upstream/theirs** — user wants smart merges, not blind upstream wins.
- **Compression ≠ vision** — LM Studio at `auxiliary.vision.base_url` is not used for `/remote-update` unless `auxiliary.compression` is pinned to that URL.
- **Cursor SDK timeouts** during sync may skip Composer and fall through to OpenRouter; pin `compression` to LM Studio for predictable local merges.
- **LM Studio thinking models** may return empty `message.content` on aux calls — if LLM resolve fails, set `reasoning_effort: none` for aux (see `references/lm-studio-kanban-aux-json.md`) or use `--conflict-resolution=none` and resolve in chat.
- **LLM limits:** binary files, non-UTF-8, or files > 512 KB fail auto-resolve — use `--conflict-resolution=upstream`, manual edit + `--finish`, or split the change.
- **Dirty tree** aborts before a new merge — stash or commit first.
- **Re-run while merge in progress:** resumes via `finish_remote_update` (same LLM resolution), not a fresh fetch.
- **Gateway restart** required after deploying code that registers the slash command.

## Tests

`tests/hermes_cli/test_remote_update.py` — mock git + `_resolve_file_with_llm` for llm/upstream/none paths.
