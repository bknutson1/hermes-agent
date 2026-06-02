"""Tests for kanban worker log streaming (specify/decompose + active workers)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_worker_log as kwl


class KanbanWorkerLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.home = Path(self._tmpdir.name) / ".hermes"
        self.home.mkdir()
        self._env_patch = patch.dict(
            os.environ,
            {"HERMES_HOME": str(self.home)},
            clear=False,
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self._home_patch = patch.object(Path, "home", lambda: Path(self._tmpdir.name))
        self._home_patch.start()
        self.addCleanup(self._home_patch.stop)
        kb.init_db()
        kwl._worker_header_written = False

    def test_write_active_worker_log_noop_without_env(self) -> None:
        kb.begin_worker_log("t_active", clear=True)
        kwl.write_active_worker_log("should not appear\n")
        self.assertFalse(kb.worker_log_path("t_active").exists())

    def test_write_active_worker_log_appends_when_env_set(self) -> None:
        os.environ["HERMES_KANBAN_TASK"] = "t_active"
        os.environ["HERMES_KANBAN_BOARD"] = "default"
        self.addCleanup(os.environ.pop, "HERMES_KANBAN_TASK", None)
        self.addCleanup(os.environ.pop, "HERMES_KANBAN_BOARD", None)
        kwl.write_active_worker_log("hello\n")
        text = kb.worker_log_path("t_active", board="default").read_text(
            encoding="utf-8"
        )
        self.assertIn("=== Kanban worker (", text)
        self.assertIn("hello\n", text)

    def test_active_worker_header_written_once(self) -> None:
        os.environ["HERMES_KANBAN_TASK"] = "t_hdr"
        self.addCleanup(os.environ.pop, "HERMES_KANBAN_TASK", None)
        kwl.maybe_write_active_worker_header(model="composer-2.5")
        kwl.maybe_write_active_worker_header(model="composer-2.5")
        text = kb.worker_log_path("t_hdr").read_text(encoding="utf-8")
        self.assertEqual(text.count("=== Kanban worker ("), 1)
        self.assertIn("model=composer-2.5", text)

    def test_cursor_stream_logger_emits_thinking_deltas(self) -> None:
        emitted: list[str] = []
        logger = kwl.CursorStreamLogger(emitted.append)
        logger.handle({"type": "thinking", "text": "Hmm"})
        logger.handle({"type": "thinking", "text": "Hmm maybe"})
        self.assertEqual("".join(emitted), "Hmm maybe")

    def test_wire_kanban_worker_log_callbacks_mirrors_events(self) -> None:
        os.environ["HERMES_KANBAN_TASK"] = "t_wire"
        self.addCleanup(os.environ.pop, "HERMES_KANBAN_TASK", None)
        agent = SimpleNamespace(
            model="composer-2.5",
            stream_delta_callback=None,
            tool_progress_callback=None,
            thinking_callback=None,
            reasoning_callback=None,
        )
        kwl.wire_kanban_worker_log_callbacks(agent)

        agent.stream_delta_callback("token")
        agent.tool_progress_callback(
            "tool.started", function_name="read", function_args={}
        )
        agent.tool_progress_callback(
            "tool.completed",
            function_name="read",
            function_args={},
            duration=1.5,
            is_error=False,
        )
        agent.thinking_callback("working…")
        agent.reasoning_callback("plan the search")

        text = kb.worker_log_path("t_wire").read_text(encoding="utf-8")
        self.assertIn("token", text)
        self.assertIn("[tool started] read", text)
        self.assertIn("[tool completed] read (1.5s)", text)
        self.assertIn("[progress] working…", text)
        self.assertIn("plan the search", text)

    def test_wire_preserves_existing_callbacks(self) -> None:
        os.environ["HERMES_KANBAN_TASK"] = "t_preserve"
        self.addCleanup(os.environ.pop, "HERMES_KANBAN_TASK", None)
        existing_delta = MagicMock()
        existing_tool = MagicMock()
        agent = SimpleNamespace(
            model="",
            stream_delta_callback=existing_delta,
            tool_progress_callback=existing_tool,
            thinking_callback=None,
        )
        kwl.wire_kanban_worker_log_callbacks(agent)
        agent.stream_delta_callback("x")
        agent.tool_progress_callback("tool.started", function_name="grep")
        existing_delta.assert_called_once_with("x")
        existing_tool.assert_called_once()


if __name__ == "__main__":
    unittest.main()
