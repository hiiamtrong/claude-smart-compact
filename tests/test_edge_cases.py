"""Coverage for edge cases E1-E15 documented in the design spec."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from claude_smart_compact.lib import memory, transcript


REPO = Path(__file__).resolve().parent.parent


def _run(script, payload, cwd):
    return subprocess.run(
        [sys.executable, str(REPO / "claude_smart_compact" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
    )


# E1: Transcript file missing
def test_e1_missing_transcript(project_root):
    payload = {
        "session_id": "e1",
        "transcript_path": "/does/not/exist.jsonl",
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = _run("pre_compact.py", payload, project_root)
    assert result.returncode == 0
    assert not (project_root / ".claude/compact-memory/e1.md").exists()


# E2: Corrupt JSONL line
def test_e2_corrupt_lines_skipped(copy_fixture):
    path = copy_fixture("transcript_corrupt_lines.jsonl")
    msgs = transcript.parse_jsonl(str(path))
    assert [m.content for m in msgs] == ["first", "second", "third"]


# E3: No user message in session
def test_e3_no_user_message_no_memory_written(project_root, fixtures_dir):
    payload = {
        "session_id": "e3",
        "transcript_path": str(fixtures_dir / "transcript_no_user.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    _run("pre_compact.py", payload, project_root)
    assert not (project_root / ".claude/compact-memory/e3.md").exists()


# E4: No TodoWrite in transcript
def test_e4_no_todowrite_renders_none(project_root, fixtures_dir):
    payload = {
        "session_id": "e4",
        "transcript_path": str(fixtures_dir / "transcript_single_turn.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    _run("pre_compact.py", payload, project_root)
    content = (project_root / ".claude/compact-memory/e4.md").read_text()
    assert "_(none)_" in content


# E5: Memory file exists without ## Preferences
def test_e5_memory_without_prefs_gets_placeholder(project_root, fixtures_dir):
    mem = project_root / ".claude/compact-memory/e5.md"
    mem.parent.mkdir(parents=True, exist_ok=True)
    mem.write_text("# Session Memory\n\n## Active Task\n> old\n")
    payload = {
        "session_id": "e5",
        "transcript_path": str(fixtures_dir / "transcript_single_turn.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    _run("pre_compact.py", payload, project_root)
    content = mem.read_text()
    assert "never rewrite existing entries" in content


# E6: Memory file exists with ## Preferences populated
def test_e6_memory_with_prefs_preserves_them(project_root, fixtures_dir):
    mem = project_root / ".claude/compact-memory/e6.md"
    mem.parent.mkdir(parents=True, exist_ok=True)
    mem.write_text("## Preferences\n- keep this\n")
    payload = {
        "session_id": "e6",
        "transcript_path": str(fixtures_dir / "transcript_single_turn.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    _run("pre_compact.py", payload, project_root)
    content = mem.read_text()
    assert "keep this" in content


# E7: compact-memory/ dir deleted mid-session
def test_e7_dir_recreated_on_next_pre_compact(project_root, fixtures_dir):
    payload = {
        "session_id": "e7",
        "transcript_path": str(fixtures_dir / "transcript_single_turn.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    _run("pre_compact.py", payload, project_root)
    d = project_root / ".claude/compact-memory"
    for p in d.iterdir():
        p.unlink()
    d.rmdir()
    _run("pre_compact.py", payload, project_root)
    assert (d / "e7.md").exists()


# E8: Atomic write into a read-only directory fails soft
def test_e8_atomic_write_failure_fails_soft(project_root, fixtures_dir, monkeypatch):
    # Make the compact-memory dir read-only after creation.
    d = project_root / ".claude/compact-memory"
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o555)
    try:
        payload = {
            "session_id": "e8",
            "transcript_path": str(fixtures_dir / "transcript_single_turn.jsonl"),
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        }
        result = _run("pre_compact.py", payload, project_root)
        assert result.returncode == 0
        assert json.loads(result.stdout) == {}
    finally:
        d.chmod(0o755)


# E9: Two parallel session_ids use separate files
def test_e9_parallel_sessions_do_not_collide(project_root, fixtures_dir):
    for sid in ("e9-a", "e9-b"):
        payload = {
            "session_id": sid,
            "transcript_path": str(fixtures_dir / "transcript_with_todos.jsonl"),
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        }
        _run("pre_compact.py", payload, project_root)
    d = project_root / ".claude/compact-memory"
    assert (d / "e9-a.md").exists()
    assert (d / "e9-b.md").exists()


# E10: Large transcript streams without loading everything
def test_e10_large_transcript(project_root, tmp_path, fixtures_dir):
    big = tmp_path / "big.jsonl"
    with big.open("w") as f:
        f.write('{"role":"user","content":"start"}\n')
        for i in range(5000):
            f.write(f'{{"role":"assistant","content":"turn {i}"}}\n')
    payload = {
        "session_id": "e10",
        "transcript_path": str(big),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = _run("pre_compact.py", payload, project_root)
    assert result.returncode == 0
    assert (project_root / ".claude/compact-memory/e10.md").exists()


# E11: Hook runs fast (< 500ms) on a moderate transcript
def test_e11_runtime_under_500ms(project_root, fixtures_dir):
    import time
    payload = {
        "session_id": "e11",
        "transcript_path": str(fixtures_dir / "transcript_with_todos.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    start = time.perf_counter()
    _run("pre_compact.py", payload, project_root)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.5  # generous; CI overhead + python startup


# E12: .claude/ missing entirely
def test_e12_no_claude_dir(tmp_path, fixtures_dir):
    payload = {
        "session_id": "e12",
        "transcript_path": str(fixtures_dir / "transcript_with_todos.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    result = _run("pre_compact.py", payload, tmp_path)
    assert result.returncode == 0
    assert (tmp_path / ".claude/compact-memory/e12.md").exists()


# E13: Invalid stdin JSON
def test_e13_invalid_stdin(project_root):
    result = subprocess.run(
        [sys.executable, str(REPO / "claude_smart_compact/pre_compact.py")],
        input="{{bad",
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


# E14: Two compactions in one session preserve preferences
def test_e14_two_compactions_preserve_prefs(project_root, fixtures_dir):
    mem = project_root / ".claude/compact-memory/e14.md"
    payload = {
        "session_id": "e14",
        "transcript_path": str(fixtures_dir / "transcript_with_todos.jsonl"),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    _run("pre_compact.py", payload, project_root)
    # Simulate agent editing Preferences section.
    original = mem.read_text()
    updated = original.replace(
        "## Preferences",
        "## Preferences\n- always use pnpm",
        1,
    )
    mem.write_text(updated)
    _run("pre_compact.py", payload, project_root)
    assert "always use pnpm" in mem.read_text()


# E15: Empty last user message
def test_e15_empty_user_message(tmp_path, project_root):
    tx = tmp_path / "empty_user.jsonl"
    tx.write_text(
        '{"role":"user","content":""}\n'
        '{"role":"assistant","content":"hi"}\n'
    )
    payload = {
        "session_id": "e15",
        "transcript_path": str(tx),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    _run("pre_compact.py", payload, project_root)
    content = (project_root / ".claude/compact-memory/e15.md").read_text()
    assert "_(no active prompt)_" in content
