from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run_hook(script: str, payload: dict, cwd: Path):
    return subprocess.run(
        [sys.executable, str(REPO / "claude_smart_compact" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_pre_compact_happy_path(project_root, fixtures_dir):
    transcript = fixtures_dir / "transcript_with_todos.jsonl"
    payload = {
        "session_id": "sid-happy",
        "transcript_path": str(transcript),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = _run_hook("pre_compact.py", payload, project_root)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert "hookSpecificOutput" in out
    assert out["hookSpecificOutput"]["hookEventName"] == "PreCompact"
    assert "additionalContext" in out["hookSpecificOutput"]

    mem = project_root / ".claude" / "compact-memory" / "sid-happy.md"
    assert mem.exists()
    content = mem.read_text()
    assert "## Active Task" in content
    assert "refactor auth module" in content
    assert "## In-Progress Todos" in content
    assert "add tests" in content

    trace = project_root / ".claude" / "compact-memory" / "sid-happy.trace.jsonl"
    lines = trace.read_text().strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["hook"] == "PreCompact"
    assert event["messages_count"] == 4
    assert event["todos_count"] == 1


def test_pre_compact_without_user_message_skips_write(project_root, fixtures_dir):
    payload = {
        "session_id": "sid-no-user",
        "transcript_path": str(fixtures_dir / "transcript_no_user.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = _run_hook("pre_compact.py", payload, project_root)
    assert result.returncode == 0, result.stderr
    mem = project_root / ".claude" / "compact-memory" / "sid-no-user.md"
    assert not mem.exists()


def test_pre_compact_preserves_preferences_on_second_run(project_root, fixtures_dir):
    mem_dir = project_root / ".claude" / "compact-memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "sid-x.md").write_text(
        "# Session Memory\n\n## Active Task\n> old\n\n"
        "## In-Progress Todos\n_(none)_\n\n"
        "## Preferences\n- never mock DB\n"
    )
    payload = {
        "session_id": "sid-x",
        "transcript_path": str(fixtures_dir / "transcript_with_todos.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = _run_hook("pre_compact.py", payload, project_root)
    assert result.returncode == 0, result.stderr
    content = (mem_dir / "sid-x.md").read_text()
    assert "never mock DB" in content


def test_pre_compact_invalid_stdin_fails_soft(project_root):
    result = subprocess.run(
        [sys.executable, str(REPO / "claude_smart_compact" / "pre_compact.py")],
        input="not json",
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


def test_pre_compact_missing_transcript_fails_soft(project_root):
    payload = {
        "session_id": "sid-missing",
        "transcript_path": "/nonexistent/path.jsonl",
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = _run_hook("pre_compact.py", payload, project_root)
    assert result.returncode == 0, result.stderr
    # No memory file should be written.
    assert not (project_root / ".claude" / "compact-memory" / "sid-missing.md").exists()


def test_pre_compact_on_real_cli_format(project_root, fixtures_dir):
    """Regression test: the real CLI transcript format with `type` and nested
    `message.role`/`message.content` must produce a memory file with the
    expected sections."""
    payload = {
        "session_id": "real-cli",
        "transcript_path": str(fixtures_dir / "transcript_real_cli_format.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = subprocess.run(
        [sys.executable, str(REPO / "claude_smart_compact" / "pre_compact.py")],
        input=json.dumps(payload), capture_output=True, text=True, cwd=project_root,
    )
    assert result.returncode == 0, result.stderr
    mem = project_root / ".claude/compact-memory/real-cli.md"
    assert mem.exists(), "memory file must be written for real CLI format"
    content = mem.read_text()
    assert "continue please" in content  # last user message
    assert "understand auth" in content  # in_progress todo


def test_pre_compact_skips_compact_slash_command(project_root, tmp_path):
    """If the last user turn is /compact, hook should use the PREVIOUS user turn as active task."""
    tx = tmp_path / "with-compact.jsonl"
    tx.write_text(
        '{"type":"user","message":{"role":"user","content":"refactor the service"},"uuid":"u1"}\n'
        '{"type":"assistant","message":{"role":"assistant","content":"working..."},"uuid":"a1"}\n'
        '{"type":"user","message":{"role":"user","content":"<command-name>/compact</command-name>\\n<command-message>compact</command-message>\\n<command-args></command-args>"},"uuid":"u2"}\n'
    )
    payload = {
        "session_id": "compact-skip",
        "transcript_path": str(tx),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = subprocess.run(
        [sys.executable, str(REPO / "claude_smart_compact" / "pre_compact.py")],
        input=json.dumps(payload), capture_output=True, text=True, cwd=project_root,
    )
    assert result.returncode == 0, result.stderr
    mem = project_root / ".claude/compact-memory/compact-skip.md"
    assert mem.exists()
    content = mem.read_text()
    assert "refactor the service" in content
    # The blockquoted active task line must be "refactor the service", not the /compact command.
    # (The in-flight turn summary may still mention /compact — that's fine.)
    import re as _re
    quoted_lines = [ln for ln in content.splitlines() if ln.startswith("> ")]
    assert quoted_lines, "No blockquoted active task line found"
    assert quoted_lines[0] == "> refactor the service"
    assert "<command-name>/compact</command-name>" not in quoted_lines[0]


def test_pre_compact_extracts_args_from_slash_command(project_root, tmp_path):
    """A slash-command user turn with args should be treated as a task,
    and the memory file's Active Task should contain the ARGS (not the wrapper)."""
    tx = tmp_path / "with-args.jsonl"
    tx.write_text(
        '{"type":"user","message":{"role":"user","content":"<command-name>/ultrareview</command-name>\\n<command-message>ultrareview</command-message>\\n<command-args>@app/foo.py please fix null handling</command-args>"},"uuid":"u1"}\n'
        '{"type":"assistant","message":{"role":"assistant","content":"looking"},"uuid":"a1"}\n'
    )
    payload = {
        "session_id": "with-args",
        "transcript_path": str(tx),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = subprocess.run(
        [sys.executable, str(REPO / "claude_smart_compact" / "pre_compact.py")],
        input=json.dumps(payload), capture_output=True, text=True, cwd=project_root,
    )
    assert result.returncode == 0, result.stderr
    mem = project_root / ".claude/compact-memory/with-args.md"
    assert mem.exists()
    content = mem.read_text()
    assert "@app/foo.py please fix null handling" in content
    # The XML wrapper should NOT appear in the Active Task blockquote line.
    quoted_lines = [ln for ln in content.splitlines() if ln.startswith("> ")]
    assert quoted_lines, "No blockquoted active task line found"
    assert "<command-name>" not in quoted_lines[0]
    assert quoted_lines[0] == "> @app/foo.py please fix null handling"


def test_pre_compact_trace_records_preserved_preferences_flag(project_root, fixtures_dir):
    mem_dir = project_root / ".claude" / "compact-memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "sid-p.md").write_text(
        "## Preferences\n- keep me\n"
    )
    payload = {
        "session_id": "sid-p",
        "transcript_path": str(fixtures_dir / "transcript_with_todos.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = _run_hook("pre_compact.py", payload, project_root)
    assert result.returncode == 0, result.stderr
    trace_lines = (mem_dir / "sid-p.trace.jsonl").read_text().strip().splitlines()
    event = json.loads(trace_lines[0])
    assert event["preserved_preferences"] is True
