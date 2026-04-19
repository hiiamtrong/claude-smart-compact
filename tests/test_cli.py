from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from claude_smart_compact import cli


# ============== Symlink mode (default) tests ==============

def test_install_default_mode_creates_symlinks(tmp_path):
    rc = cli.install(tmp_path, force=False)
    assert rc == 0
    hooks_dir = tmp_path / ".claude" / "hooks"
    assert (hooks_dir / "pre_compact.py").is_symlink()
    assert (hooks_dir / "user_prompt.py").is_symlink()
    assert (hooks_dir / "lib").is_symlink()


def test_install_symlinks_resolve_to_installed_package(tmp_path):
    cli.install(tmp_path, force=False)
    link = tmp_path / ".claude/hooks/pre_compact.py"
    resolved = link.resolve()
    # resolved path should contain "claude_smart_compact" (either from site-packages or editable install)
    assert "claude_smart_compact" in str(resolved)
    assert resolved.name == "pre_compact.py"


def test_install_symlinked_hook_runs_end_to_end(tmp_path):
    cli.install(tmp_path, force=False)
    hook = tmp_path / ".claude/hooks/pre_compact.py"
    transcript = Path(__file__).parent / "fixtures" / "transcript_with_todos.jsonl"
    payload = json.dumps({
        "session_id": "symlink-smoke",
        "transcript_path": str(transcript),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    })
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=payload, capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    # PreCompact stdout must be `{}`; the real proof of work is the memory file.
    assert json.loads(result.stdout) == {}
    assert (tmp_path / ".claude/compact-memory/symlink-smoke.md").exists()


def test_install_symlink_without_force_skips_existing(tmp_path, capsys):
    cli.install(tmp_path, force=False)
    # capture first install output to clear
    capsys.readouterr()
    rc = cli.install(tmp_path, force=False)
    assert rc == 0
    captured = capsys.readouterr()
    assert "skip" in captured.err


def test_install_symlink_force_replaces_existing_file(tmp_path):
    """--force should work even if the target is a regular file (not a symlink)."""
    hooks_dir = tmp_path / ".claude/hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    # Place a regular file at the target location.
    (hooks_dir / "pre_compact.py").write_text("# stale content")
    cli.install(tmp_path, force=True)
    assert (hooks_dir / "pre_compact.py").is_symlink()
    assert (hooks_dir / "pre_compact.py").resolve().name == "pre_compact.py"


def test_install_symlink_force_replaces_dangling_symlink(tmp_path):
    """--force should repair a dangling symlink."""
    hooks_dir = tmp_path / ".claude/hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    dangling_target = tmp_path / "nonexistent-target.py"
    os.symlink(dangling_target, hooks_dir / "pre_compact.py")
    assert (hooks_dir / "pre_compact.py").is_symlink()
    assert not (hooks_dir / "pre_compact.py").exists()  # dangling
    cli.install(tmp_path, force=True)
    assert (hooks_dir / "pre_compact.py").exists()  # now valid


# ============== Copy mode tests ==============

def test_install_copy_mode_copies_files(tmp_path):
    rc = cli.install(tmp_path, force=False, use_symlink=False)
    assert rc == 0
    hooks_dir = tmp_path / ".claude" / "hooks"
    assert (hooks_dir / "pre_compact.py").is_file() and not (hooks_dir / "pre_compact.py").is_symlink()
    assert (hooks_dir / "lib" / "core.py").is_file()


def test_install_copy_mode_skips_pycache(tmp_path):
    cli.install(tmp_path, force=False, use_symlink=False)
    lib_dst = tmp_path / ".claude/hooks/lib"
    assert not (lib_dst / "__pycache__").exists()


def test_install_copy_mode_force_overwrites(tmp_path):
    cli.install(tmp_path, force=False, use_symlink=False)
    pre = tmp_path / ".claude/hooks/pre_compact.py"
    pre.write_text("TAMPERED")
    cli.install(tmp_path, force=True, use_symlink=False)
    assert "TAMPERED" not in pre.read_text()
    assert "PreCompact" in pre.read_text()


def test_install_copy_mode_cli_flag_invokes_copy(tmp_path):
    """Verify --copy flag in main() routes to copy mode."""
    rc = cli.main(["install", "--dir", str(tmp_path), "--copy"])
    assert rc == 0
    assert (tmp_path / ".claude/hooks/pre_compact.py").is_file()
    assert not (tmp_path / ".claude/hooks/pre_compact.py").is_symlink()


# ============== Settings merge tests (unchanged behavior) ==============

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
    assert data["permissions"]["allow"] == ["Bash(git:*)"]
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo bye"
    assert any(
        h["hooks"][0]["command"] == "python3 .claude/hooks/pre_compact.py"
        for h in data["hooks"]["PreCompact"]
    )


def test_install_is_idempotent_on_settings(tmp_path):
    cli.install(tmp_path, force=False)
    cli.install(tmp_path, force=False)
    data = json.loads((tmp_path / ".claude/settings.json").read_text())
    assert len(data["hooks"]["PreCompact"]) == 1
    assert len(data["hooks"]["UserPromptSubmit"]) == 1


def test_install_deduplicates_hook_entries_across_interpreter_variants(tmp_path):
    """Pre-existing entry using `python` (not `python3`) must not yield a duplicate."""
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    existing_cmd = "python .claude/hooks/pre_compact.py"
    settings.write_text(json.dumps({
        "hooks": {
            "PreCompact": [{"hooks": [{"type": "command", "command": existing_cmd}]}],
        },
    }))
    cli.install(tmp_path, force=False)
    data = json.loads(settings.read_text())
    assert len(data["hooks"]["PreCompact"]) == 1
    # Existing entry should be preserved, not overwritten.
    assert data["hooks"]["PreCompact"][0]["hooks"][0]["command"] == existing_cmd


def test_install_backs_up_existing_settings(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    original = {"permissions": {"allow": ["X"]}}
    settings.write_text(json.dumps(original))
    cli.install(tmp_path, force=False)
    backup = tmp_path / ".claude/settings.json.bak"
    assert backup.exists()
    assert json.loads(backup.read_text()) == original


def test_install_second_run_does_not_rewrite_backup(tmp_path):
    """Re-running install when settings already contain the hooks must not touch .bak."""
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    original = {"permissions": {"allow": ["X"]}}
    settings.write_text(json.dumps(original))

    cli.install(tmp_path, force=False)
    backup = tmp_path / ".claude/settings.json.bak"
    assert backup.exists()
    first_mtime = os.stat(backup).st_mtime_ns

    cli.install(tmp_path, force=False)
    assert os.stat(backup).st_mtime_ns == first_mtime


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
    assert settings.read_text() == before
    captured = capsys.readouterr()
    assert "invalid" in captured.err.lower() or "parse" in captured.err.lower()


# ============== Package re-export ==============

def test_install_importable_from_package_root():
    from claude_smart_compact import install as pkg_install
    assert callable(pkg_install)
    assert pkg_install is cli.install


# ============== --dry-run tests ==============

def test_install_dry_run(tmp_path):
    rc = cli.install(tmp_path, force=False, write_settings=True, use_symlink=True, dry_run=True)
    assert rc == 0
    hooks_dir = tmp_path / ".claude" / "hooks"
    # Nothing should have been written.
    assert not (hooks_dir / "pre_compact.py").exists()
    assert not (hooks_dir / "user_prompt.py").exists()
    assert not (hooks_dir / "lib").exists()
    assert not (tmp_path / ".claude" / "settings.json").exists()


def test_install_dry_run_cli_flag(tmp_path, capsys):
    rc = cli.main(["install", "--dir", str(tmp_path), "--dry-run", "--no-settings"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "[dry-run]" in captured.out
    assert not (tmp_path / ".claude/hooks/pre_compact.py").exists()


# ============== Windows fallback (mocked) ==============

def test_install_on_windows_falls_back_to_copy(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "IS_WINDOWS", True)
    cli.install(tmp_path, force=False)
    captured = capsys.readouterr()
    assert "windows" in captured.err.lower()
    # Files should be regular copies, not symlinks.
    assert not (tmp_path / ".claude/hooks/pre_compact.py").is_symlink()
    assert (tmp_path / ".claude/hooks/pre_compact.py").is_file()


# ============== Interpreter selection ==============

def test_python_bin_uses_python3_on_non_windows(monkeypatch):
    monkeypatch.setattr(cli, "IS_WINDOWS", False)
    assert cli._python_bin() == "python3"


def test_python_bin_uses_python_on_windows(monkeypatch):
    monkeypatch.setattr(cli, "IS_WINDOWS", True)
    assert cli._python_bin() == "python"


def test_install_on_windows_writes_python_not_python3_in_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "IS_WINDOWS", True)
    cli.install(tmp_path, force=False)
    data = json.loads((tmp_path / ".claude/settings.json").read_text())
    pre_cmd = data["hooks"]["PreCompact"][0]["hooks"][0]["command"]
    user_cmd = data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    assert pre_cmd == "python .claude/hooks/pre_compact.py"
    assert user_cmd == "python .claude/hooks/user_prompt.py"
