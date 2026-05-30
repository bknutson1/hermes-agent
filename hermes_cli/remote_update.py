"""Sync a fork's origin/main with upstream/main (fetch, merge, push)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re
import subprocess
from typing import Callable, Literal, Sequence

ConflictResolution = Literal["llm", "upstream", "none"]
DEFAULT_CONFLICT_RESOLUTION: ConflictResolution = "llm"
_MAX_LLM_RESOLVE_BYTES = 512_000

_MERGE_RESOLVE_SYSTEM = """You resolve git merge conflicts for a Hermes Agent fork merging NousResearch/hermes-agent upstream into the fork branch.

Rules:
- Output ONLY the complete resolved file content. No markdown fences, no explanation.
- Keep intentional fork-only changes (Kanban, LM Studio aux JSON, dashboard/plugins, Windows-specific fixes) when they are not clearly superseded by upstream.
- Prefer upstream for bug fixes and refactors that replace obsolete fork patches.
- Remove every conflict marker (<<<<<<<, =======, >>>>>>>, |||||||).
"""


class RemoteUpdateStatus(str, Enum):
    UP_TO_DATE = "up_to_date"
    MERGED = "merged"
    CONFLICTS = "conflicts"
    FAILED = "failed"


@dataclass
class RemoteUpdateReport:
    status: RemoteUpdateStatus
    lines: list[str] = field(default_factory=list)
    upstream_ahead: int = 0
    conflict_files: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def ok(self) -> bool:
        return self.status not in (
            RemoteUpdateStatus.FAILED,
            RemoteUpdateStatus.CONFLICTS,
        )


def _run_git(
    git_cmd: Sequence[str],
    cwd: Path,
    extra: Sequence[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*git_cmd, *extra],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _count_commits(git_cmd: Sequence[str], cwd: Path, base: str, head: str) -> int:
    try:
        result = _run_git(git_cmd, cwd, ["rev-list", "--count", f"{base}..{head}"])
        return int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return -1


def _remote_exists(git_cmd: Sequence[str], cwd: Path, name: str) -> bool:
    result = _run_git(
        git_cmd, cwd, ["remote", "get-url", name], check=False
    )
    return result.returncode == 0


def _ref_exists(git_cmd: Sequence[str], cwd: Path, ref: str) -> bool:
    result = _run_git(git_cmd, cwd, ["rev-parse", "--verify", ref], check=False)
    return result.returncode == 0


def _current_branch(git_cmd: Sequence[str], cwd: Path) -> str | None:
    try:
        result = _run_git(git_cmd, cwd, ["rev-parse", "--abbrev-ref", "HEAD"])
        branch = result.stdout.strip()
        return branch if branch and branch != "HEAD" else None
    except subprocess.CalledProcessError:
        return None


def _dirty_files(git_cmd: Sequence[str], cwd: Path) -> list[str]:
    result = _run_git(git_cmd, cwd, ["status", "--porcelain"], check=False)
    if result.returncode != 0:
        return ["(could not read git status)"]
    return [line for line in result.stdout.splitlines() if line.strip()]


def _unmerged_files(git_cmd: Sequence[str], cwd: Path) -> list[str]:
    result = _run_git(
        git_cmd,
        cwd,
        ["diff", "--name-only", "--diff-filter=U"],
        check=False,
    )
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.splitlines() if f.strip()]


def _merge_in_progress(git_cmd: Sequence[str], cwd: Path) -> bool:
    return (cwd / ".git" / "MERGE_HEAD").exists()


def _has_conflict_markers(text: str) -> bool:
    return bool(
        re.search(r"^<<<<<<< ", text, re.MULTILINE)
        or re.search(r"^=======\s*$", text, re.MULTILINE)
        or re.search(r"^>>>>>>> ", text, re.MULTILINE)
    )


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip("\n") + ("\n" if text.endswith("\n") else "")


def _resolve_file_with_llm(rel_path: str, content: str) -> str:
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning

    response = call_llm(
        task="compression",
        messages=[
            {"role": "system", "content": _MERGE_RESOLVE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"File: {rel_path}\n\n"
                    "Resolve all merge conflicts in this file:\n\n"
                    f"{content}"
                ),
            },
        ],
        temperature=0.1,
        max_tokens=16384,
    )
    resolved = _strip_code_fences(extract_content_or_reasoning(response))
    if not resolved.strip():
        raise RuntimeError("LLM returned empty content")
    if _has_conflict_markers(resolved):
        raise RuntimeError("LLM output still contains conflict markers")
    return resolved


def _resolve_merge_conflicts(
    cwd: Path,
    git: list[str],
    paths: list[str],
    mode: ConflictResolution,
    say: Callable[[str], None],
) -> bool:
    """Resolve unmerged paths. Returns True if all paths are staged."""
    if mode == "upstream":
        say(f"→ Resolving {len(paths)} conflict(s) using upstream (theirs)...")
        for path in paths:
            _run_git(git, cwd, ["checkout", "--theirs", "--", path])
            _run_git(git, cwd, ["add", "--", path])
        return not _unmerged_files(git, cwd)

    if mode == "none":
        return False

    say(f"→ Resolving {len(paths)} conflict(s) with auxiliary LLM...")
    for path in paths:
        full = cwd / path
        if not full.is_file():
            say(f"  ✗ {path}: not a regular file")
            return False
        raw = full.read_bytes()
        if b"\x00" in raw:
            say(f"  ✗ {path}: binary file — cannot auto-resolve")
            return False
        if len(raw) > _MAX_LLM_RESOLVE_BYTES:
            say(f"  ✗ {path}: too large for LLM resolve ({len(raw)} bytes)")
            return False
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            say(f"  ✗ {path}: not valid UTF-8")
            return False
        if not _has_conflict_markers(content):
            say(f"  • {path}: no markers (staging as-is)")
            _run_git(git, cwd, ["add", "--", path])
            continue
        say(f"  • {path}: LLM merge...")
        try:
            resolved = _resolve_file_with_llm(path, content)
        except Exception as exc:
            say(f"  ✗ {path}: {exc}")
            return False
        full.write_text(resolved, encoding="utf-8", newline="")
        _run_git(git, cwd, ["add", "--", path])
        say(f"    ✓ {path}")

    remaining = _unmerged_files(git, cwd)
    if remaining:
        say("✗ Unmerged paths remain after resolution:")
        for path in remaining:
            say(f"  {path}")
        return False
    return True


def _complete_merge_and_push(
    cwd: Path,
    git: list[str],
    branch: str,
    merge_message: str | None,
    say: Callable[[str], None],
    lines: list[str],
    *,
    upstream_ahead: int = 0,
) -> RemoteUpdateReport:
    msg = merge_message or "merge: sync fork with upstream/main"
    if _merge_in_progress(git, cwd):
        say("→ Committing merge...")
        try:
            _run_git(git, cwd, ["commit", "-m", msg])
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc)).strip()
            say(f"✗ git commit failed: {err}")
            return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    say(f"→ Pushing to origin {branch}...")
    push = _run_git(git, cwd, ["push", "origin", branch], check=False)
    if push.returncode != 0:
        err = (push.stderr or push.stdout or "push failed").strip()
        say(f"✗ git push origin {branch} failed: {err}")
        return RemoteUpdateReport(
            RemoteUpdateStatus.FAILED, lines, upstream_ahead=upstream_ahead
        )

    say(f"✓ Fork updated: merged from upstream and pushed to origin/{branch}.")
    return RemoteUpdateReport(
        RemoteUpdateStatus.MERGED, lines, upstream_ahead=upstream_ahead
    )


def finish_remote_update(
    repo_dir: Path | str,
    *,
    branch: str = "main",
    merge_message: str | None = None,
    git_cmd: Sequence[str] | None = None,
    log: Callable[[str], None] | None = None,
    conflict_resolution: ConflictResolution = DEFAULT_CONFLICT_RESOLUTION,
) -> RemoteUpdateReport:
    """Complete an in-progress merge (resolve conflicts if needed), then push."""
    cwd = Path(repo_dir).resolve()
    git = list(git_cmd or ["git"])
    lines: list[str] = []

    def say(msg: str) -> None:
        lines.append(msg)
        if log is not None:
            log(msg)

    if not (cwd / ".git").exists():
        say("✗ Not a git repository.")
        return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    if not _merge_in_progress(git, cwd):
        say("✗ No merge in progress. Run `/remote-update` first.")
        return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    remaining = _unmerged_files(git, cwd)
    if remaining:
        if conflict_resolution == "none":
            say("✗ Unresolved conflicts remain:")
            for path in remaining:
                say(f"  {path}")
            return RemoteUpdateReport(
                RemoteUpdateStatus.CONFLICTS, lines, conflict_files=remaining
            )
        if not _resolve_merge_conflicts(cwd, git, remaining, conflict_resolution, say):
            still = _unmerged_files(git, cwd)
            return RemoteUpdateReport(
                RemoteUpdateStatus.FAILED,
                lines,
                conflict_files=still or remaining,
            )
        say("  ✓ Conflicts resolved")

    return _complete_merge_and_push(
        cwd, git, branch, merge_message, say, lines,
    )


def run_remote_update(
    repo_dir: Path | str,
    *,
    branch: str = "main",
    conflict_resolution: ConflictResolution = DEFAULT_CONFLICT_RESOLUTION,
    finish: bool = False,
    merge_message: str | None = None,
    git_cmd: Sequence[str] | None = None,
    log: Callable[[str], None] | None = None,
    # Back-compat alias
    prefer_upstream_on_conflict: bool = False,
) -> RemoteUpdateReport:
    """Fetch, merge upstream into local branch, auto-resolve conflicts, push origin.

    One-shot by default: uses the auxiliary LLM to intelligently merge conflicted
    files, then commits and pushes. No manual ``--finish`` step required.
    """
    if prefer_upstream_on_conflict:
        conflict_resolution = "upstream"

    if finish:
        return finish_remote_update(
            repo_dir,
            branch=branch,
            merge_message=merge_message,
            git_cmd=git_cmd,
            log=log,
            conflict_resolution=conflict_resolution,
        )

    cwd = Path(repo_dir).resolve()
    git = list(git_cmd or ["git"])
    lines: list[str] = []

    def say(msg: str) -> None:
        lines.append(msg)
        if log is not None:
            log(msg)

    origin_ref = f"origin/{branch}"
    upstream_ref = f"upstream/{branch}"

    if not (cwd / ".git").exists():
        say("✗ Not a git repository.")
        return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    if _merge_in_progress(git, cwd):
        say("→ Resuming in-progress merge...")
        return finish_remote_update(
            cwd,
            branch=branch,
            merge_message=merge_message,
            git_cmd=git,
            log=log,
            conflict_resolution=conflict_resolution,
        )

    for remote in ("origin", "upstream"):
        if not _remote_exists(git, cwd, remote):
            say(f"✗ Missing git remote '{remote}'.")
            return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    say("→ Fetching origin and upstream...")
    for remote in ("origin", "upstream"):
        try:
            _run_git(git, cwd, ["fetch", remote])
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc)).strip()
            say(f"✗ git fetch {remote} failed: {err}")
            return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    for ref in (origin_ref, upstream_ref):
        if not _ref_exists(git, cwd, ref):
            say(f"✗ Ref {ref} not found after fetch.")
            return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    upstream_ahead = _count_commits(git, cwd, origin_ref, upstream_ref)
    if upstream_ahead < 0:
        say("✗ Could not compare origin and upstream.")
        return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    if upstream_ahead == 0:
        say(f"✓ {origin_ref} is already up to date with {upstream_ref}.")
        return RemoteUpdateReport(
            RemoteUpdateStatus.UP_TO_DATE, lines, upstream_ahead=0
        )

    dirty = _dirty_files(git, cwd)
    if dirty:
        say("✗ Working tree has uncommitted changes. Commit or stash first:")
        for row in dirty[:12]:
            say(f"  {row}")
        if len(dirty) > 12:
            say(f"  … and {len(dirty) - 12} more")
        return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    current = _current_branch(git, cwd)
    if current != branch:
        say(f"→ Checking out {branch}...")
        try:
            _run_git(git, cwd, ["checkout", branch])
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc)).strip()
            say(f"✗ git checkout {branch} failed: {err}")
            return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    say(f"→ Fast-forwarding local {branch} from origin...")
    try:
        _run_git(git, cwd, ["pull", "--ff-only", "origin", branch])
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        say(f"✗ git pull origin {branch} failed: {err}")
        return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

    msg = merge_message or f"merge: sync fork with {upstream_ref}"
    say(f"→ Merging {upstream_ref} ({upstream_ahead} commit(s))...")
    merge = _run_git(
        git,
        cwd,
        ["merge", upstream_ref, "-m", msg, "--no-edit"],
        check=False,
    )
    if merge.returncode != 0:
        conflicts = _unmerged_files(git, cwd)
        if not conflicts:
            err = (merge.stderr or merge.stdout or "merge failed").strip()
            say(f"✗ git merge failed: {err}")
            return RemoteUpdateReport(RemoteUpdateStatus.FAILED, lines)

        if conflict_resolution == "none":
            say(f"✗ Merge stopped with {len(conflicts)} conflict(s):")
            for path in conflicts:
                say(f"  • {path}")
            return RemoteUpdateReport(
                RemoteUpdateStatus.CONFLICTS,
                lines,
                upstream_ahead=upstream_ahead,
                conflict_files=conflicts,
            )

        if not _resolve_merge_conflicts(
            cwd, git, conflicts, conflict_resolution, say
        ):
            still = _unmerged_files(git, cwd)
            return RemoteUpdateReport(
                RemoteUpdateStatus.FAILED,
                lines,
                upstream_ahead=upstream_ahead,
                conflict_files=still or conflicts,
            )
        say("  ✓ Conflicts resolved")

    return _complete_merge_and_push(
        cwd,
        git,
        branch,
        merge_message,
        say,
        lines,
        upstream_ahead=upstream_ahead,
    )


def default_hermes_repo_dir() -> Path:
    """Return the Hermes Agent source checkout (package root)."""
    return Path(__file__).resolve().parent.parent
