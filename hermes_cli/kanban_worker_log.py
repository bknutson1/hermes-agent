"""Worker-log streaming for kanban auxiliary ops and active workers.

Kanban workers spawned by the dispatcher write stdout/stderr to
``<board>/logs/<task_id>.log``. Specify/decompose run in-process and
clear that log for a fresh run. Active workers append to the same file
the dispatcher opened — this module writes there when
``HERMES_KANBAN_TASK`` is set so the dashboard log drawer stays live
during Cursor SDK turns and other quiet ``chat -Q -q`` worker modes.
"""

from __future__ import annotations

import contextvars
import os
import threading
from datetime import datetime
from typing import Any, Callable, Optional

from hermes_cli import kanban_db as kb

WorkerLogSink = Callable[[str], None]

_sink: contextvars.ContextVar[Optional[WorkerLogSink]] = contextvars.ContextVar(
    "kanban_worker_log_sink",
    default=None,
)

_worker_header_lock = threading.Lock()
_worker_header_written = False


def kanban_task_id_from_env() -> Optional[str]:
    task_id = os.environ.get("HERMES_KANBAN_TASK", "").strip()
    return task_id or None


def kanban_board_from_env() -> Optional[str]:
    board = os.environ.get("HERMES_KANBAN_BOARD", "").strip()
    return board or None


def write_active_worker_log(text: str) -> None:
    """Append to the active kanban task log when ``HERMES_KANBAN_TASK`` is set."""
    task_id = kanban_task_id_from_env()
    if not task_id or not text:
        return
    maybe_write_active_worker_header()
    kb.append_worker_log(task_id, text, board=kanban_board_from_env())


def maybe_write_active_worker_header(*, model: str = "") -> None:
    """Write a one-time session header for spawned kanban workers."""
    global _worker_header_written
    task_id = kanban_task_id_from_env()
    if not task_id:
        return
    with _worker_header_lock:
        if _worker_header_written:
            return
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        profile = os.environ.get("HERMES_PROFILE", "").strip()
        header = f"=== Kanban worker ({started})"
        if profile:
            header += f" profile={profile}"
        if model:
            header += f" model={model}"
        header += " ===\n"
        kb.append_worker_log(task_id, header, board=kanban_board_from_env())
        _worker_header_written = True


def get_task_worker_log_sink() -> Optional[WorkerLogSink]:
    return _sink.get()


def emit_task_worker_log(text: str) -> None:
    sink = _sink.get()
    if sink and text:
        sink(text)
    elif kanban_task_id_from_env() and text:
        write_active_worker_log(text)


def _message_field(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(key, default)
    return getattr(message, key, default)


def _assistant_visible_text(message: Any) -> str:
    inner = _message_field(message, "message") or {}
    if not isinstance(inner, dict):
        inner = getattr(inner, "__dict__", {}) or {}
    blocks = inner.get("content") if isinstance(inner, dict) else getattr(inner, "content", None)
    if not blocks:
        return ""
    parts: list[str] = []
    for block in blocks:
        block_dict = block if isinstance(block, dict) else getattr(block, "__dict__", {})
        block_type = str(
            (block_dict.get("type") if isinstance(block_dict, dict) else getattr(block, "type", ""))
            or ""
        ).lower()
        if block_type == "text":
            text = block_dict.get("text") if isinstance(block_dict, dict) else getattr(block, "text", "")
            if text:
                parts.append(str(text))
    return "".join(parts)


class CursorStreamLogger:
    """Write Cursor SDK stream events to a worker log sink."""

    def __init__(
        self,
        emit: Callable[[str], None],
        *,
        emit_thinking: bool = True,
    ) -> None:
        self._emit = emit
        self._emit_thinking = emit_thinking
        self._last_assistant = ""
        self._last_thinking = ""

    def handle(self, message: Any) -> None:
        msg_type = str(_message_field(message, "type") or "").strip().lower()
        if msg_type == "status":
            text = str(
                _message_field(message, "message")
                or _message_field(message, "status")
                or ""
            ).strip()
            if text:
                self._emit(f"\n[status] {text}\n")
            return
        if msg_type == "tool_call":
            name = str(_message_field(message, "name") or "tool")
            status = str(_message_field(message, "status") or "").strip().lower()
            if status:
                self._emit(f"\n[tool {status}] {name}\n")
            return
        if msg_type == "thinking":
            if not self._emit_thinking:
                return
            text = str(
                _message_field(message, "text")
                or _message_field(message, "thinking")
                or ""
            )
            if not text:
                return
            if text.startswith(self._last_thinking):
                delta = text[len(self._last_thinking) :]
            else:
                delta = text
            if delta:
                self._emit(delta)
            self._last_thinking = text
            return
        if msg_type != "assistant":
            return
        text = _assistant_visible_text(message)
        if not text:
            return
        if text.startswith(self._last_assistant):
            delta = text[len(self._last_assistant) :]
            if delta:
                self._emit(delta)
        else:
            self._emit(text)
        self._last_assistant = text


def wire_kanban_worker_log_callbacks(agent: Any) -> None:
    """Mirror agent progress callbacks into the task worker log."""
    if not kanban_task_id_from_env():
        return
    if getattr(agent, "_kanban_worker_log_wired", False):
        return
    agent._kanban_worker_log_wired = True
    maybe_write_active_worker_header(model=str(getattr(agent, "model", "") or ""))

    existing_delta = getattr(agent, "stream_delta_callback", None)

    def _delta_cb(text: str, *args, **kwargs) -> None:
        if text:
            write_active_worker_log(text)
        if existing_delta is not None:
            existing_delta(text, *args, **kwargs)

    agent.stream_delta_callback = _delta_cb

    existing_tool = getattr(agent, "tool_progress_callback", None)

    def _tool_cb(event_type: str, *args, **kwargs) -> None:
        name = kwargs.get("function_name") or kwargs.get("name") or "tool"
        if event_type == "tool.started":
            write_active_worker_log(f"\n[tool started] {name}\n")
        elif event_type == "tool.completed":
            duration = kwargs.get("duration")
            suffix = f" ({duration:.1f}s)" if isinstance(duration, (int, float)) else ""
            err = " error" if kwargs.get("is_error") else ""
            write_active_worker_log(f"\n[tool completed{err}] {name}{suffix}\n")
        if existing_tool is not None:
            existing_tool(event_type, *args, **kwargs)

    agent.tool_progress_callback = _tool_cb

    existing_thinking = getattr(agent, "thinking_callback", None)

    def _thinking_cb(text: str) -> None:
        if text:
            write_active_worker_log(f"\n[progress] {text}\n")
        if existing_thinking is not None:
            existing_thinking(text)

    agent.thinking_callback = _thinking_cb

    existing_reasoning = getattr(agent, "reasoning_callback", None)

    def _reasoning_cb(text: str) -> None:
        if text:
            write_active_worker_log(text)
        if existing_reasoning is not None:
            existing_reasoning(text)

    agent.reasoning_callback = _reasoning_cb


class task_worker_log:
    """Context manager: open a fresh worker log and stream auxiliary output."""

    def __init__(
        self,
        task_id: str,
        *,
        operation: str,
        model: str = "",
        board: Optional[str] = None,
    ) -> None:
        self.task_id = task_id
        self.operation = operation
        self.model = (model or "").strip()
        self.board = board
        self._token: Optional[contextvars.Token] = None
        self._failed = False

    def write(self, text: str) -> None:
        if text:
            kb.append_worker_log(self.task_id, text, board=self.board)

    def __enter__(self) -> "task_worker_log":
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        kb.begin_worker_log(self.task_id, board=self.board, clear=True)
        header = f"=== Kanban {self.operation} ({started})"
        if self.model:
            header += f" model={self.model}"
        header += " ===\n"
        self.write(header)
        self._token = _sink.set(self.write)
        return self

    def __exit__(self, exc_type, exc, _tb) -> bool:
        if self._token is not None:
            _sink.reset(self._token)
            self._token = None
        if exc is not None:
            self._failed = True
            detail = str(exc).strip() or type(exc).__name__
            self.write(f"\n=== {self.operation} failed: {detail} ===\n")
        else:
            self.write(f"\n=== {self.operation} complete ===\n")
        return False
