from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run(payload: dict, cwd: Path):
    return subprocess.run(
        [sys.executable, str(REPO / "hooks" / "user_prompt.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_user_prompt_noop_when_no_memory(project_root):
    payload = {
        "session_id": "sid-none",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "hi",
    }
    result = _run(payload, project_root)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}


def test_user_prompt_injects_pointer_when_memory_exists(project_root):
    mem_dir = project_root / ".claude" / "compact-memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "sid-1.md").write_text("# Session Memory\n\nbody " * 200)

    payload = {
        "session_id": "sid-1",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "continue",
    }
    result = _run(payload, project_root)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "sid-1" in ctx
    assert "compact-memory" in ctx


def test_user_prompt_trace_records_pointer_injected(project_root):
    mem_dir = project_root / ".claude" / "compact-memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "sid-2.md").write_text("x")
    payload = {
        "session_id": "sid-2",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "continue",
    }
    _run(payload, project_root)
    trace = mem_dir / "sid-2.trace.jsonl"
    assert trace.exists()
    event = json.loads(trace.read_text().strip().splitlines()[0])
    assert event["hook"] == "UserPromptSubmit"
    assert event["pointer_injected"] is True
    assert event["memory_bytes"] == 1


def test_user_prompt_invalid_stdin_fails_soft(project_root):
    result = subprocess.run(
        [sys.executable, str(REPO / "hooks" / "user_prompt.py")],
        input="garbage",
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


def test_user_prompt_creates_claude_dir_if_missing(tmp_path):
    # No .claude/ dir pre-created — hook must not crash.
    payload = {
        "session_id": "sid-fresh",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "hi",
    }
    result = subprocess.run(
        [sys.executable, str(REPO / "hooks" / "user_prompt.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
