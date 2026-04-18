from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from claude_smart_compact import cli


def test_install_copies_files_into_target(tmp_path):
    rc = cli.install(tmp_path, force=False)
    assert rc == 0
    hooks_dir = tmp_path / ".claude" / "hooks"
    assert (hooks_dir / "pre_compact.py").exists()
    assert (hooks_dir / "user_prompt.py").exists()
    assert (hooks_dir / "lib" / "core.py").exists()
    assert (hooks_dir / "lib" / "memory.py").exists()
    assert (hooks_dir / "lib" / "transcript.py").exists()


def test_install_is_idempotent_without_force(tmp_path, capsys):
    cli.install(tmp_path, force=False)
    rc = cli.install(tmp_path, force=False)
    assert rc == 0
    captured = capsys.readouterr()
    assert "skip" in captured.err


def test_install_force_overwrites(tmp_path):
    cli.install(tmp_path, force=False)
    pre = tmp_path / ".claude/hooks/pre_compact.py"
    pre.write_text("TAMPERED")
    cli.install(tmp_path, force=True)
    assert "TAMPERED" not in pre.read_text()
    assert "PreCompact" in pre.read_text()


def test_installed_hook_runs_end_to_end(tmp_path):
    """Smoke test: install, then invoke the deployed hook with a valid payload."""
    cli.install(tmp_path, force=False)
    hook = tmp_path / ".claude/hooks/pre_compact.py"
    transcript = (
        Path(__file__).parent / "fixtures" / "transcript_with_todos.jsonl"
    )
    payload = json.dumps({
        "session_id": "smoke",
        "transcript_path": str(transcript),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    })
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=payload, capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "PreCompact"
    assert (tmp_path / ".claude/compact-memory/smoke.md").exists()
