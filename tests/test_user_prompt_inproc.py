"""In-process tests for cc_compact.user_prompt.main — fills coverage that
subprocess tests in test_user_prompt.py can't reach."""
from __future__ import annotations

import json

import pytest

from cc_compact import user_prompt


def test_main_noop_when_no_memory(project_root, monkeypatch, capsys):
    monkeypatch.chdir(project_root)
    user_prompt.main({"session_id": "sid-none"})
    assert json.loads(capsys.readouterr().out) == {}
    # No trace written either — hook exits before safe_trace.
    assert not (project_root / ".claude/compact-memory/sid-none.trace.jsonl").exists()


def test_main_injects_pointer_when_memory_exists(project_root, monkeypatch, capsys):
    monkeypatch.chdir(project_root)
    mem_dir = project_root / ".claude" / "compact-memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    mem_file = mem_dir / "2026-04-22T10-00-00Z_sid-1.md"
    mem_file.write_text("x" * 1024)

    user_prompt.main({"session_id": "sid-1"})
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "2026-04-22T10-00-00Z_sid-1.md" in ctx

    event = json.loads((mem_dir / "sid-1.trace.jsonl").read_text().strip())
    assert event["pointer_injected"] is True
    assert event["memory_bytes"] == 1024


def test_main_missing_session_id_raises(project_root, monkeypatch):
    """main() does payload['session_id'] directly — a missing key must raise
    so run_hook's outer handler can soft-fail the process."""
    monkeypatch.chdir(project_root)
    with pytest.raises(KeyError):
        user_prompt.main({})
