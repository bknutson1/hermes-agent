"""Tests for kanban git worktree provisioning."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_worktree as kwt


class KanbanWorktreeTests(unittest.TestCase):
    def _init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        (root / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=str(root), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "branch", "-M", "main"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )

    def test_fetch_remote_base_ref_runs_git_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            self._init_repo(repo)
            with patch("hermes_cli.kanban_worktree.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr="",
                )
                ok = kwt.fetch_remote_base_ref(repo, "origin/main")
            self.assertTrue(ok)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args[:3], ["git", "fetch", "origin"])
            self.assertIn("main", args)
            self.assertIn("--prune", args)

    def test_ensure_worktree_workspace_fetches_before_add(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            self._init_repo(repo)
            wt_path = repo / ".worktrees" / "t_fetch"
            task = kb.Task(
                id="t_fetch",
                title="x",
                body=None,
                assignee="worker",
                status="ready",
                priority=0,
                created_by=None,
                created_at=0,
                started_at=None,
                completed_at=None,
                workspace_kind="worktree",
                workspace_path=str(wt_path),
                claim_lock=None,
                claim_expires=None,
                tenant=None,
                branch_name="wt/t_fetch",
                base_branch="origin/main",
            )
            with patch(
                "hermes_cli.kanban_worktree.fetch_remote_base_ref",
                return_value=True,
            ) as mock_fetch:
                kwt.ensure_worktree_workspace(task, wt_path, repo_root=repo)
            mock_fetch.assert_called_once()
            call_args = mock_fetch.call_args[0]
            self.assertEqual(call_args[0], repo)
            self.assertEqual(call_args[1], "origin/main")

    def test_ensure_worktree_workspace_creates_git_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            self._init_repo(repo)
            wt_path = repo / ".worktrees" / "t_test"
            task = kb.Task(
                id="t_test",
                title="x",
                body=None,
                assignee="worker",
                status="ready",
                priority=0,
                created_by=None,
                created_at=0,
                started_at=None,
                completed_at=None,
                workspace_kind="worktree",
                workspace_path=str(wt_path),
                claim_lock=None,
                claim_expires=None,
                tenant=None,
                branch_name="wt/t_test",
                base_branch="origin/main",
            )
            created = kwt.ensure_worktree_workspace(task, wt_path, repo_root=repo)
            self.assertEqual(created, wt_path.resolve())
            self.assertTrue((wt_path / ".git").exists())
            self.assertTrue((wt_path / "README.md").exists())
            show = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(show.stdout.strip(), "wt/t_test")

    def test_list_git_branches_includes_local_and_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            self._init_repo(repo)
            branches = kwt.list_git_branches(repo)
            self.assertIn("main", branches)
            self.assertIn("origin/main", branches)

    def test_apply_kanban_worker_workspace_sets_cwd_and_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            original_cwd = os.getcwd()
            try:
                os.environ["HERMES_KANBAN_WORKSPACE"] = str(workspace)
                agent = type("Agent", (), {})()
                applied = kwt.apply_kanban_worker_workspace(agent)
                self.assertEqual(applied, str(workspace))
                self.assertEqual(agent.session_cwd, str(workspace))
                self.assertEqual(Path(os.getcwd()), workspace.resolve())
            finally:
                os.chdir(original_cwd)
                os.environ.pop("HERMES_KANBAN_WORKSPACE", None)
                os.environ.pop("TERMINAL_CWD", None)
                os.environ.pop("HERMES_CURSOR_AUX_CWD", None)

    def test_complete_task_persists_handoff_on_run_not_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".hermes"
            home.mkdir()
            with patch.dict(os.environ, {"HERMES_HOME": str(home)}, clear=False), patch.object(
                Path, "home", lambda: Path(tmp)
            ):
                kb.init_db()
                conn = kb.connect()
                try:
                    tid = kb.create_task(conn, title="x", assignee="worker")
                    kb.claim_task(conn, tid)
                    ok = kb.complete_task(
                        conn,
                        tid,
                        summary="shipped the fix",
                        metadata={"changed_files": ["a.py"]},
                    )
                    self.assertTrue(ok)
                    comments = kb.list_comments(conn, tid)
                    runs = kb.list_runs(conn, tid)
                finally:
                    conn.close()
            self.assertEqual(comments, [])
            self.assertEqual(len(runs), 1)
            self.assertIn("shipped the fix", runs[0].summary or "")
            self.assertEqual(runs[0].metadata.get("changed_files"), ["a.py"])


if __name__ == "__main__":
    unittest.main()
