"""Tests for per-column ``status_entered_at`` (when a task entered its status)."""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb


def _load_set_status_direct():
    repo_root = Path(__file__).resolve().parents[2]
    plugin_file = repo_root / "plugins" / "kanban" / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location(
        "hermes_kanban_plugin_status_entered_test", plugin_file,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod._set_status_direct


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def test_status_entered_at_uses_latest_column_transition(kanban_home):
    set_status = _load_set_status_direct()
    with kb.connect() as conn:
        tid = kb.create_task(conn, title="sort by column entry")
        created_at = int(kb.get_task(conn, tid).created_at or 0)
        entered_ready = kb.status_entered_at_by_task_id(
            conn, [kb.get_task(conn, tid)],
        )[tid]
        assert entered_ready == created_at

        time.sleep(1.05)
        assert set_status(conn, tid, "todo") is True
        entered_todo = kb.status_entered_at_by_task_id(
            conn, [kb.get_task(conn, tid)],
        )[tid]
        assert entered_todo > created_at


def test_board_payload_includes_status_entered_at(kanban_home):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    set_status = _load_set_status_direct()
    repo_root = Path(__file__).resolve().parents[2]
    plugin_file = repo_root / "plugins" / "kanban" / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location(
        "hermes_kanban_board_status_entered_test", plugin_file,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with kb.connect() as conn:
        tid = kb.create_task(conn, title="board field")
        created_at = int(kb.get_task(conn, tid).created_at or 0)
        time.sleep(1.05)
        assert set_status(conn, tid, "blocked") is True

    app = FastAPI()
    app.include_router(mod.router, prefix="/api/plugins/kanban")
    client = TestClient(app)
    data = client.get("/api/plugins/kanban/board").json()
    blocked_col = next(c for c in data["columns"] if c["name"] == "blocked")
    card = next(t for t in blocked_col["tasks"] if t["id"] == tid)
    assert card["status_entered_at"] > created_at
