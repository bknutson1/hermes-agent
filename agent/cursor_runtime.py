"""Cursor SDK runtime — hands Hermes turns to a Cursor Agent subprocess."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_CURSOR_TURN_SEPARATOR = "\n\n---\n\n"
_CURSOR_TURN_MAX_ATTEMPTS = 2


def _retire_cursor_session(agent) -> None:
    """Close and drop the lazy Cursor SDK session so the next turn respawns."""
    session = getattr(agent, "_cursor_session", None)
    if session is None:
        return
    try:
        session.close()
    except Exception:
        pass
    agent._cursor_session = None


def _ensure_cursor_sdk_session(agent, *, progress_callback, tool_progress_callback) -> None:
    """Lazy-create ``CursorSDKSession`` on the agent (mirrors codex path)."""
    reasoning_callback = getattr(agent, "reasoning_callback", None)
    if getattr(agent, "_cursor_session", None) is not None:
        session = agent._cursor_session
        if progress_callback is not None:
            session._progress_callback = progress_callback
        session._reasoning_callback = reasoning_callback
        session._tool_progress_callback = tool_progress_callback
        return

    from agent.transports.cursor_sdk_session import CursorSDKSession

    cwd = getattr(agent, "session_cwd", None) or os.getcwd()
    api_key = getattr(agent, "api_key", None) or os.environ.get("CURSOR_API_KEY")
    model = getattr(agent, "model", None) or "composer-2.5"
    agent._cursor_session = CursorSDKSession(
        cwd=cwd,
        api_key=api_key,
        model=model,
        progress_callback=progress_callback,
        reasoning_callback=reasoning_callback,
        tool_progress_callback=tool_progress_callback,
    )


def effective_system_prompt(agent) -> str:
    """Hermes system prompt plus any ephemeral overlay."""
    prompt = getattr(agent, "_cached_system_prompt", None) or ""
    ephemeral = getattr(agent, "ephemeral_system_prompt", None)
    if ephemeral:
        prompt = f"{prompt}\n\n{ephemeral}".strip()
    return prompt


def compose_cursor_user_input(
    agent,
    user_message: str,
    *,
    inject_system: bool,
) -> str:
    """Build the user input sent to Cursor SDK.

    Cursor has no separate system-role channel, so the Hermes system prompt
    is prepended to the first turn only (once per ``CursorSDKSession``).
    """
    text = user_message or ""
    if not inject_system:
        return text
    system = effective_system_prompt(agent)
    if not system.strip():
        return text
    return (
        "The following are your operating instructions (Hermes system prompt). "
        "Follow them for this entire session.\n\n"
        f"{system}"
        f"{_CURSOR_TURN_SEPARATOR}"
        f"{text}"
    ).strip()


def run_cursor_sdk_turn(
    agent,
    *,
    user_message: str,
    original_user_message: Any,
    messages: List[Dict[str, Any]],
    effective_task_id: str,
    should_review_memory: bool = False,
) -> Dict[str, Any]:
    """Cursor SDK runtime path. Called when ``agent.api_mode == cursor_sdk_runtime``."""
    from agent.transports.cursor_sdk_session import CursorSDKSession, preflight_cursor_sdk

    progress_callback = getattr(agent, "thinking_callback", None)
    tool_progress_callback = getattr(agent, "tool_progress_callback", None)

    try:
        preflight_cursor_sdk(progress_callback=progress_callback)
    except (ImportError, RuntimeError) as exc:
        logger.warning("cursor SDK preflight failed: %s", exc)
        return {
            "final_response": str(exc),
            "messages": messages,
            "api_calls": 0,
            "completed": False,
            "partial": True,
            "error": str(exc),
            "interrupted": False,
        }

    _ensure_cursor_sdk_session(
        agent,
        progress_callback=progress_callback,
        tool_progress_callback=tool_progress_callback,
    )

    turn = None
    for attempt in range(_CURSOR_TURN_MAX_ATTEMPTS):
        session = agent._cursor_session
        if session.should_proactively_retire():
            logger.info(
                "cursor SDK session past max age (%.0fs), retiring before turn",
                session.session_age_seconds(),
            )
            _retire_cursor_session(agent)
            _ensure_cursor_sdk_session(
                agent,
                progress_callback=progress_callback,
                tool_progress_callback=tool_progress_callback,
            )
            session = agent._cursor_session

        # Cursor SDK has no system-role channel. The Hermes system prompt (skills,
        # kanban lifecycle, tool guidance) is prepended on the first turn of each
        # CursorSDKSession so workers see the same contract as chat-completions
        # runtimes. Subsequent turns on the same session omit it to avoid bloat.
        inject_system = getattr(session, "_turns_sent", 0) == 0
        prompt = compose_cursor_user_input(
            agent,
            user_message,
            inject_system=inject_system,
        )
        logger.info(
            "cursor SDK turn starting session=%s model=%s inject_system=%s attempt=%d",
            getattr(agent, "session_id", None) or "none",
            getattr(agent, "model", None) or "composer-2.5",
            inject_system,
            attempt + 1,
        )
        try:
            turn = session.run_turn(user_input=prompt)
            session._turns_sent = getattr(session, "_turns_sent", 0) + 1
        except Exception as exc:
            logger.exception("cursor SDK turn failed")
            _retire_cursor_session(agent)
            if attempt + 1 < _CURSOR_TURN_MAX_ATTEMPTS:
                logger.warning(
                    "cursor SDK turn crashed, retrying with fresh session: %s", exc
                )
                _ensure_cursor_sdk_session(
                    agent,
                    progress_callback=progress_callback,
                    tool_progress_callback=tool_progress_callback,
                )
                continue
            return {
                "final_response": (
                    f"Cursor SDK turn failed: {exc}. "
                    "Check CURSOR_API_KEY and pip install cursor-sdk."
                ),
                "messages": messages,
                "api_calls": 0,
                "completed": False,
                "partial": True,
                "error": str(exc),
                "interrupted": bool(
                    getattr(agent, "_interrupt_requested", False)
                ),
            }

        if getattr(turn, "should_retire", False):
            logger.warning("cursor SDK session retired (error: %s)", turn.error)
            _retire_cursor_session(agent)
            if (
                attempt + 1 < _CURSOR_TURN_MAX_ATTEMPTS
                and turn.error
                and not turn.interrupted
            ):
                logger.warning(
                    "cursor SDK turn failed, retrying with fresh session: %s",
                    turn.error,
                )
                _ensure_cursor_sdk_session(
                    agent,
                    progress_callback=progress_callback,
                    tool_progress_callback=tool_progress_callback,
                )
                continue
        break

    if turn is None:
        return {
            "final_response": "Cursor SDK turn failed (no result).",
            "messages": messages,
            "api_calls": 0,
            "completed": False,
            "partial": True,
            "error": "cursor_sdk_no_turn_result",
            "interrupted": bool(getattr(agent, "_interrupt_requested", False)),
        }

    if turn.projected_messages:
        messages.extend(turn.projected_messages)

    agent._iters_since_skill = (
        getattr(agent, "_iters_since_skill", 0) + turn.tool_iterations
    )

    should_review_skills = False
    if (
        agent._skill_nudge_interval > 0
        and agent._iters_since_skill >= agent._skill_nudge_interval
        and "skill_manage" in agent.valid_tool_names
    ):
        should_review_skills = True
        agent._iters_since_skill = 0

    if not turn.interrupted and turn.error is None:
        try:
            agent._sync_external_memory_for_turn(
                original_user_message=original_user_message,
                final_response=turn.final_text,
                interrupted=False,
            )
        except Exception:
            logger.debug("external memory sync raised", exc_info=True)

    if (
        turn.final_text
        and not turn.interrupted
        and (should_review_memory or should_review_skills)
    ):
        try:
            agent._spawn_background_review(
                messages_snapshot=list(messages),
                review_memory=should_review_memory,
                review_skills=should_review_skills,
            )
        except Exception:
            logger.debug("background review spawn raised", exc_info=True)

    interrupted = turn.interrupted or bool(getattr(agent, "_interrupt_requested", False))

    return {
        "final_response": turn.final_text,
        "messages": messages,
        "api_calls": 1,
        "completed": not interrupted and turn.error is None,
        "partial": interrupted or turn.error is not None,
        "error": turn.error,
        "interrupted": interrupted,
        "cursor_agent_id": turn.agent_id,
        "cursor_run_id": turn.run_id,
    }
