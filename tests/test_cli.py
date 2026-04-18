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


def test_install_creates_settings_when_missing(tmp_path):
    cli.install(tmp_path, force=False)
    settings = tmp_path / ".claude/settings.json"
    assert settings.exists()
    data = json.loads(settings.read_text())
    assert "PreCompact" in data["hooks"]
    assert "UserPromptSubmit" in data["hooks"]
    assert data["hooks"]["PreCompact"][0]["hooks"][0]["command"] == \
        "python3 .claude/hooks/pre_compact.py"


def test_install_merges_into_existing_settings_preserving_other_keys(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({
        "permissions": {"allow": ["Bash(git:*)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo bye"}]}]},
    }))
    cli.install(tmp_path, force=False)
    data = json.loads(settings.read_text())
    # existing keys preserved
    assert data["permissions"]["allow"] == ["Bash(git:*)"]
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo bye"
    # new hooks added
    assert any(
        h["hooks"][0]["command"] == "python3 .claude/hooks/pre_compact.py"
        for h in data["hooks"]["PreCompact"]
    )
    assert any(
        h["hooks"][0]["command"] == "python3 .claude/hooks/user_prompt.py"
        for h in data["hooks"]["UserPromptSubmit"]
    )


def test_install_is_idempotent_on_settings(tmp_path):
    cli.install(tmp_path, force=False)
    cli.install(tmp_path, force=False)
    data = json.loads((tmp_path / ".claude/settings.json").read_text())
    # Should have exactly 1 entry each, not 2
    assert len(data["hooks"]["PreCompact"]) == 1
    assert len(data["hooks"]["UserPromptSubmit"]) == 1


def test_install_backs_up_existing_settings(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    original = {"permissions": {"allow": ["X"]}}
    settings.write_text(json.dumps(original))
    cli.install(tmp_path, force=False)
    backup = tmp_path / ".claude/settings.json.bak"
    assert backup.exists()
    assert json.loads(backup.read_text()) == original


def test_install_no_settings_flag_skips_merge(tmp_path):
    cli.install(tmp_path, force=False, write_settings=False)
    assert not (tmp_path / ".claude/settings.json").exists()


def test_install_invalid_existing_settings_errors_without_writing(tmp_path, capsys):
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{not valid json")
    before = settings.read_text()
    rc = cli.install(tmp_path, force=False)
    assert rc != 0
    assert settings.read_text() == before  # untouched
    captured = capsys.readouterr()
    assert "invalid" in captured.err.lower() or "parse" in captured.err.lower()


def test_install_force_overwrites(tmp_path):
    cli.install(tmp_path, force=False)
    pre = tmp_path / ".claude/hooks/pre_compact.py"
    pre.write_text("TAMPERED")
    cli.install(tmp_path, force=True)
    assert "TAMPERED" not in pre.read_text()
    assert "PreCompact" in pre.read_text()


def test_install_skips_pycache(tmp_path):
    cli.install(tmp_path, force=False)
    lib_dst = tmp_path / ".claude/hooks/lib"
    assert not (lib_dst / "__pycache__").exists()


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
