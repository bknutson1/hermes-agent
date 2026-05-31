"""Human-review deferral for decomposed Kanban subtasks."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def _decompose_two_children(conn, root_assignee="orchestrator"):
    tid = kb.create_task(conn, title="epic", triage=True)
    kb.update_task_workspace(
        conn,
        tid,
        workspace_kind="worktree",
        workspace_path="/tmp/epic-wt",
        branch_name="wt/epic",
    )
    child_ids = kb.decompose_triage_task(
        conn,
        tid,
        root_assignee=root_assignee,
        children=[
            {"title": "child a", "assignee": "worker-a", "parents": []},
            {"title": "child b", "assignee": "worker-b", "parents": [0]},
        ],
        author="test",
    )
    assert child_ids is not None
    return tid, child_ids


def test_decomposed_child_skips_human_review_gate(kanban_home):
    with kb.connect() as conn:
        _root, child_ids = _decompose_two_children(conn)
        child = child_ids[0]
        assert kb.task_is_decomposed_child(conn, child)
        assert kb.task_requires_human_review_after_sdlc(conn, child) is False
        assert kb.task_requires_human_review_after_sdlc(conn, _root) is True


def test_review_agent_can_complete_decomposed_child_from_review(kanban_home):
    with kb.connect() as conn:
        _root, child_ids = _decompose_two_children(conn)
        child = child_ids[0]
        kb.claim_task(conn, child)
        kb.complete_task(
            conn,
            child,
            summary="implemented",
            enforce_review=True,
        )
        assert kb.get_task(conn, child).status == "review"

        kb.claim_review_task(conn, child)
        ok = kb.complete_task(
            conn,
            child,
            summary="SDLC approved — tests pass",
            allow_from_review=True,
        )
        assert ok is True
        task = kb.get_task(conn, child)
        assert task.status == "done"
        run = kb.latest_run(conn, child)
        assert run.outcome == "review_approved"


def test_standalone_worktree_still_requires_human_review(kanban_home):
    with kb.connect() as conn:
        tid = kb.create_task(
            conn,
            title="solo",
            assignee="worker",
            workspace_kind="worktree",
            workspace_path="/tmp/wt",
        )
        assert kb.task_requires_human_review_after_sdlc(conn, tid) is True


def test_defer_disabled_restores_human_review_on_children(kanban_home, monkeypatch):
    monkeypatch.setattr(
        kb,
        "_kanban_config",
        lambda: {"defer_human_review_to_decompose_root": False},
    )
    with kb.connect() as conn:
        _root, child_ids = _decompose_two_children(conn)
        assert kb.task_requires_human_review_after_sdlc(conn, child_ids[0]) is True
