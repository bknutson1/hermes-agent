"""Cursor SDK session retirement — proactive age limit and terminal errors."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.transports.cursor_sdk_session import (
    CursorSDKSession,
    _DEFAULT_SESSION_MAX_AGE_SECONDS,
)


def test_should_proactively_retire_when_past_max_age(monkeypatch):
    session = CursorSDKSession(api_key="test-key")
    session._agent = object()
    session._agent_started_at = 1000.0
    session._max_session_age_seconds = 60.0
    monkeypatch.setattr(
        "agent.transports.cursor_sdk_session.time.monotonic", lambda: 1070.0
    )
    assert session.session_age_seconds() == 70.0
    assert session.should_proactively_retire() is True


def test_should_not_proactively_retire_before_max_age(monkeypatch):
    session = CursorSDKSession(api_key="test-key")
    session._agent = object()
    session._agent_started_at = 1000.0
    session._max_session_age_seconds = 3600.0
    monkeypatch.setattr(
        "agent.transports.cursor_sdk_session.time.monotonic", lambda: 1500.0
    )
    assert session.should_proactively_retire() is False


def test_terminal_error_status_sets_should_retire():
    session = CursorSDKSession(api_key="test-key")
    session._agent = MagicMock()
    session._agent.send.return_value = MagicMock(
        id="run-1",
        messages=lambda: iter([]),
        wait=lambda: SimpleNamespace(status="error", result="bridge disconnected"),
        supports=lambda _: False,
    )

    with patch.object(session, "ensure_started", return_value="agent-1"):
        result = session.run_turn("hello", turn_timeout=5.0)

    assert result.error
    assert result.should_retire is True


def test_terminal_expired_status_sets_should_retire():
    session = CursorSDKSession(api_key="test-key")
    session._agent = MagicMock()
    session._agent.send.return_value = MagicMock(
        id="run-1",
        messages=lambda: iter([]),
        wait=lambda: SimpleNamespace(status="expired", result="session expired"),
        supports=lambda _: False,
    )

    with patch.object(session, "ensure_started", return_value="agent-1"):
        result = session.run_turn("hello", turn_timeout=5.0)

    assert result.error
    assert result.should_retire is True


def test_default_max_age_is_under_one_hour():
    session = CursorSDKSession(api_key="test-key")
    assert session._max_session_age_seconds == _DEFAULT_SESSION_MAX_AGE_SECONDS
    assert session._max_session_age_seconds < 3600.0


def test_max_age_respects_env(monkeypatch):
    monkeypatch.setenv("HERMES_CURSOR_SESSION_MAX_AGE_SECONDS", "120")
    session = CursorSDKSession(api_key="test-key")
    assert session._max_session_age_seconds == 120.0
