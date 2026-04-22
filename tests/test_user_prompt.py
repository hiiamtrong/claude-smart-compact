from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run(payload: dict, cwd: Path):
    return subprocess.run(
        [sys.executable, str(REPO / "cc_compact" / "user_prompt.py")],
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
    (mem_dir / "2026-01-01T00-00-00Z_sid-1.md").write_text("# Session Memory\n\nbody " * 200)

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
    (mem_dir / "2026-01-01T00-00-00Z_sid-2.md").write_text("x")
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
        [sys.executable, str(REPO / "cc_compact" / "user_prompt.py")],
        input="garbage",
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


def test_user_prompt_error_trace_has_session_id(project_root):
    """Regression: when main() raises AFTER the payload is parsed, the error
    trace must correlate with the real session_id (not null)."""
    hook = REPO / "cc_compact" / "user_prompt.py"
    # Patch memory.memory_path (called by main() only, NOT by the error handler)
    # to force main() to raise after the payload is parsed.
    wrapper = (
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(hook.parent)!r})\n"
        "from lib import memory\n"
        "def _boom(*a, **kw):\n"
        "    raise RuntimeError('boom after parse')\n"
        "memory.find_memory_path = _boom\n"
        f"runpy.run_path({str(hook)!r}, run_name='__main__')\n"
    )
    payload = {
        "session_id": "sid-err",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "hi",
    }
    result = subprocess.run(
        [sys.executable, "-c", wrapper],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
    trace = project_root / ".claude" / "compact-memory" / "sid-err.trace.jsonl"
    assert trace.exists(), "error trace must be written under the real session_id"
    event = json.loads(trace.read_text().strip().splitlines()[0])
    assert event["hook"] == "UserPromptSubmit"
    assert event["error_type"] == "RuntimeError"
    assert event["error"] == "boom after parse"


def test_user_prompt_creates_claude_dir_if_missing(tmp_path):
    # No .claude/ dir pre-created — hook must not crash.
    payload = {
        "session_id": "sid-fresh",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "hi",
    }
    result = subprocess.run(
        [sys.executable, str(REPO / "cc_compact" / "user_prompt.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
