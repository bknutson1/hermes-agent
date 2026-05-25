"""Cursor runtime retries once after session retirement (codex parity)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from agent.cursor_runtime import run_cursor_sdk_turn
from agent.transports.cursor_sdk_session import TurnResult


def test_run_cursor_sdk_turn_retries_after_should_retire(monkeypatch):
    calls: list[str] = []

    def _fake_run_turn(self, user_input, **kwargs):
        calls.append(user_input)
        if len(calls) == 1:
            return TurnResult(
                final_text="",
                error="bridge disconnected",
                should_retire=True,
            )
        return TurnResult(final_text="recovered")

    monkeypatch.setattr(
        "agent.transports.cursor_sdk_session.preflight_cursor_sdk",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "agent.transports.cursor_sdk_session.CursorSDKSession.run_turn",
        _fake_run_turn,
    )

    agent = SimpleNamespace(
        api_mode="cursor_sdk_runtime",
        session_id="sess-1",
        model="composer-2.5",
        api_key="test-key",
        session_cwd=".",
        quiet_mode=True,
        _cached_system_prompt="SYSTEM",
        ephemeral_system_prompt=None,
        _cursor_session=None,
        thinking_callback=None,
        tool_progress_callback=None,
        _skill_nudge_interval=0,
        _iters_since_skill=0,
        valid_tool_names=set(),
        _interrupt_requested=False,
        _sync_external_memory_for_turn=lambda **kwargs: None,
        _spawn_background_review=lambda **kwargs: None,
    )

    result = run_cursor_sdk_turn(
        agent,
        user_message="continue",
        original_user_message="continue",
        messages=[],
        effective_task_id="task-1",
    )

    assert result["final_response"] == "recovered"
    assert result["completed"] is True
    assert len(calls) == 2
    assert getattr(agent, "_cursor_session", None) is not None


def test_proactive_retire_before_turn(monkeypatch):
    """Stale session is replaced before run_turn when past max age."""
    run_calls: list[int] = []

    class _StaleThenFresh:
        _counter = 0

        def __init__(self):
            _StaleThenFresh._counter += 1
            self._instance_num = _StaleThenFresh._counter
            self._turns_sent = 0

        def should_proactively_retire(self):
            return self._instance_num == 1

        def session_age_seconds(self):
            return 4000.0

        def run_turn(self, user_input, **kwargs):
            run_calls.append(1)
            self._turns_sent += 1
            return TurnResult(final_text="ok")

        def close(self):
            pass

    _StaleThenFresh._counter = 0
    sessions: list[_StaleThenFresh] = []

    def _factory(**kwargs):
        s = _StaleThenFresh()
        sessions.append(s)
        return s

    monkeypatch.setattr(
        "agent.transports.cursor_sdk_session.preflight_cursor_sdk",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "agent.transports.cursor_sdk_session.CursorSDKSession",
        _factory,
    )

    agent = SimpleNamespace(
        api_mode="cursor_sdk_runtime",
        session_id="sess-1",
        model="composer-2.5",
        api_key="test-key",
        session_cwd=".",
        quiet_mode=True,
        _cached_system_prompt="SYSTEM",
        ephemeral_system_prompt=None,
        _cursor_session=None,
        thinking_callback=None,
        tool_progress_callback=None,
        _skill_nudge_interval=0,
        _iters_since_skill=0,
        valid_tool_names=set(),
        _interrupt_requested=False,
        _sync_external_memory_for_turn=lambda **kwargs: None,
        _spawn_background_review=lambda **kwargs: None,
    )

    result = run_cursor_sdk_turn(
        agent,
        user_message="after idle hour",
        original_user_message="after idle hour",
        messages=[{"role": "user", "content": "earlier"}],
        effective_task_id="task-1",
    )

    assert result["final_response"] == "ok"
    assert len(sessions) == 2
    assert len(run_calls) == 1
