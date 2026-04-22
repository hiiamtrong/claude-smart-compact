"""In-process tests for cc_compact.pre_compact.main — fills coverage that
subprocess tests in test_pre_compact.py can't reach."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from cc_compact import pre_compact
from cc_compact.lib import memory


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))


def test_main_writes_memory_and_traces(project_root, fixtures_dir, monkeypatch, capsys):
    monkeypatch.chdir(project_root)
    payload = {
        "session_id": "sid-inproc",
        "transcript_path": str(fixtures_dir / "transcript_with_todos.jsonl"),
        "trigger": "auto",
    }
    pre_compact.main(payload)

    assert json.loads(capsys.readouterr().out) == {}
    mem = memory.find_memory_path(project_root, "sid-inproc")
    assert mem is not None
    body = mem.read_text()
    assert "## Active Task" in body
    assert "## Open Todos" in body

    trace = project_root / ".claude" / "compact-memory" / "sid-inproc.trace.jsonl"
    event = json.loads(trace.read_text().strip().splitlines()[0])
    assert event["hook"] == "PreCompact"
    assert event["trigger"] == "auto"
    assert event["preserved_preferences"] is False


def test_main_skips_write_when_no_user_message(project_root, fixtures_dir, monkeypatch, capsys):
    monkeypatch.chdir(project_root)
    payload = {
        "session_id": "sid-empty",
        "transcript_path": str(fixtures_dir / "transcript_no_user.jsonl"),
        "trigger": "manual",
    }
    pre_compact.main(payload)

    assert json.loads(capsys.readouterr().out) == {}
    assert memory.find_memory_path(project_root, "sid-empty") is None

    trace = project_root / ".claude" / "compact-memory" / "sid-empty.trace.jsonl"
    event = json.loads(trace.read_text().strip().splitlines()[0])
    assert event["skipped_reason"] == "no user message"
    assert event["last_user_index"] is None


def test_main_via_run_hook_entry(project_root, fixtures_dir, monkeypatch, capsys):
    """Cover the `if __name__ == '__main__'` dispatch path by calling run_hook
    with pre_compact.main — same code path the CLI uses."""
    monkeypatch.chdir(project_root)
    payload = {
        "session_id": "sid-hook",
        "transcript_path": str(fixtures_dir / "transcript_with_todos.jsonl"),
        "trigger": "auto",
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    pre_compact.hook_runner.run_hook(pre_compact.main, "PreCompact")
    assert json.loads(capsys.readouterr().out) == {}
    assert memory.find_memory_path(project_root, "sid-hook") is not None
