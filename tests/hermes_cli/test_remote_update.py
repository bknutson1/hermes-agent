"""Tests for hermes_cli.remote_update."""

from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_cli.remote_update import (
    RemoteUpdateStatus,
    finish_remote_update,
    run_remote_update,
)


def _git_side_effect_factory(
    *,
    upstream_ahead: int = 2,
    dirty: bool = False,
    merge_conflicts: bool = False,
    push_ok: bool = True,
):
    unmerged_calls = {"count": 0}

    def side_effect(cmd, **kwargs):
        import subprocess

        args = [str(c) for c in cmd]
        joined = " ".join(args)
        check = kwargs.get("check", True)

        if joined.endswith("remote get-url origin") or joined.endswith(
            "remote get-url upstream"
        ):
            return subprocess.CompletedProcess(cmd, 0, stdout="url\n", stderr="")

        if joined.endswith("fetch origin") or joined.endswith("fetch upstream"):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if "rev-parse --verify" in joined:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc\n", stderr="")

        if "rev-list --count origin/main..upstream/main" in joined:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=f"{upstream_ahead}\n", stderr=""
            )

        if joined.endswith("status --porcelain"):
            out = " M file\n" if dirty else ""
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        if "rev-parse --abbrev-ref HEAD" in joined:
            return subprocess.CompletedProcess(cmd, 0, stdout="main\n", stderr="")

        if "pull --ff-only origin main" in joined:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if joined.startswith("git merge upstream/main"):
            if merge_conflicts:
                return subprocess.CompletedProcess(
                    cmd, 1, stdout="", stderr="CONFLICT\n"
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if "diff --name-only --diff-filter=U" in joined:
            unmerged_calls["count"] += 1
            if merge_conflicts and unmerged_calls["count"] == 1:
                out = "conflicted.txt\n"
            else:
                out = ""
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        if "checkout --theirs -- conflicted.txt" in joined:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if joined.endswith("add -- conflicted.txt"):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if "commit" in joined:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if "push origin main" in joined:
            rc = 0 if push_ok else 1
            return subprocess.CompletedProcess(
                cmd, rc, stdout="", stderr="" if push_ok else "rejected\n"
            )

        if not check:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return side_effect


class TestRunRemoteUpdate:
    @patch("hermes_cli.remote_update.subprocess.run")
    def test_up_to_date(self, mock_run, tmp_path: Path):
        mock_run.side_effect = _git_side_effect_factory(upstream_ahead=0)
        (tmp_path / ".git").mkdir()
        report = run_remote_update(tmp_path)
        assert report.status == RemoteUpdateStatus.UP_TO_DATE
        assert report.ok

    @patch("hermes_cli.remote_update.subprocess.run")
    def test_merge_and_push(self, mock_run, tmp_path: Path):
        mock_run.side_effect = _git_side_effect_factory(upstream_ahead=3)
        (tmp_path / ".git").mkdir()
        report = run_remote_update(tmp_path)
        assert report.status == RemoteUpdateStatus.MERGED
        assert report.ok

    @patch("hermes_cli.remote_update.subprocess.run")
    def test_dirty_tree_aborts(self, mock_run, tmp_path: Path):
        mock_run.side_effect = _git_side_effect_factory(upstream_ahead=2, dirty=True)
        (tmp_path / ".git").mkdir()
        report = run_remote_update(tmp_path)
        assert report.status == RemoteUpdateStatus.FAILED

    @patch("hermes_cli.remote_update.subprocess.run")
    def test_conflicts_stop_when_resolution_none(self, mock_run, tmp_path: Path):
        mock_run.side_effect = _git_side_effect_factory(
            upstream_ahead=1, merge_conflicts=True
        )
        (tmp_path / ".git").mkdir()
        report = run_remote_update(tmp_path, conflict_resolution="none")
        assert report.status == RemoteUpdateStatus.CONFLICTS
        assert report.conflict_files == ["conflicted.txt"]

    @patch("hermes_cli.remote_update.subprocess.run")
    def test_prefer_upstream_resolves(self, mock_run, tmp_path: Path):
        mock_run.side_effect = _git_side_effect_factory(
            upstream_ahead=1, merge_conflicts=True
        )
        (tmp_path / ".git").mkdir()
        report = run_remote_update(tmp_path, conflict_resolution="upstream")
        assert report.status == RemoteUpdateStatus.MERGED
        commands = [" ".join(str(a) for a in c.args[0]) for c in mock_run.call_args_list]
        assert any("checkout --theirs" in c for c in commands)

    @patch("hermes_cli.remote_update._resolve_file_with_llm")
    @patch("hermes_cli.remote_update.subprocess.run")
    def test_llm_resolves_then_pushes(
        self, mock_run, mock_llm, tmp_path: Path
    ):
        mock_run.side_effect = _git_side_effect_factory(
            upstream_ahead=1, merge_conflicts=True
        )
        (tmp_path / ".git").mkdir()
        conflicted = tmp_path / "conflicted.txt"
        conflicted.write_text(
            "<<<<<<< HEAD\nfork\n=======\nupstream\n>>>>>>> upstream/main\n",
            encoding="utf-8",
        )
        mock_llm.return_value = "merged content\n"

        report = run_remote_update(tmp_path, conflict_resolution="llm")
        assert report.status == RemoteUpdateStatus.MERGED
        assert conflicted.read_text(encoding="utf-8") == "merged content\n"
        mock_llm.assert_called_once()


class TestFinishRemoteUpdate:
    @patch("hermes_cli.remote_update.subprocess.run")
    @patch("hermes_cli.remote_update._merge_in_progress", return_value=True)
    def test_finish_pushes_after_clean_merge(
        self, _merge, mock_run, tmp_path: Path
    ):
        def side_effect(cmd, **kwargs):
            import subprocess

            joined = " ".join(str(c) for c in cmd)
            if "diff --name-only --diff-filter=U" in joined:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "commit" in joined:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "push origin main" in joined:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        (tmp_path / ".git").mkdir()
        report = finish_remote_update(tmp_path)
        assert report.status == RemoteUpdateStatus.MERGED
