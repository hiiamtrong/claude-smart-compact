"""End-to-end Claude Code plugin install simulation.

Verifies the ship-to-user path works:

  * Manifest (`.claude-plugin/plugin.json`) is valid and declares hooks.
  * `hooks/hooks.json` registers the two events with commands that resolve
    via `${CLAUDE_PLUGIN_ROOT}` to executable scripts with proper shebangs.
  * Invoking each registered command exactly the way Claude Code would
    (plugin root as env var, fresh cwd, JSON on stdin) produces the same
    side effects as the already-tested pip-install path.
  * Hooks are self-contained — they don't silently rely on the
    `cc_compact` package being on `PYTHONPATH`.

These tests don't spin up Claude Code itself; they exercise the plugin's
contract (manifest + hooks.json + scripts) the same way the harness does.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from cc_compact.lib import memory as mem_lib


REPO = Path(__file__).resolve().parent.parent


def _load_manifest() -> dict:
    return json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())


def _load_hooks_config() -> dict:
    manifest = _load_manifest()
    hooks_rel = manifest["hooks"].lstrip("./")
    return json.loads((REPO / hooks_rel).read_text())


def _resolve(command: str, plugin_root: Path) -> Path:
    """Substitute `${CLAUDE_PLUGIN_ROOT}` the way Claude Code does."""
    return Path(command.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root)))


def _invoke(command: str, payload: dict, *, cwd: Path, plugin_root: Path,
            extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    env.pop("PYTHONPATH", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(_resolve(command, plugin_root))],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=30,
    )


# --- Manifest + hooks.json integrity ----------------------------------------


def test_manifest_has_required_fields():
    m = _load_manifest()
    assert m["name"] == "cc-compact"
    assert m["version"]
    assert m["hooks"], "manifest must declare a hooks pointer"


def test_hooks_config_registers_precompact_and_user_prompt_submit():
    cfg = _load_hooks_config()
    assert set(cfg["hooks"]) == {"PreCompact", "UserPromptSubmit"}
    for event, entries in cfg["hooks"].items():
        assert entries, f"{event} has no registrations"
        for entry in entries:
            for hook in entry["hooks"]:
                assert hook["type"] == "command"
                assert "${CLAUDE_PLUGIN_ROOT}" in hook["command"], (
                    f"{event}: command must use ${{CLAUDE_PLUGIN_ROOT}} for "
                    f"plugin portability (got: {hook['command']!r})"
                )


def test_every_registered_hook_script_is_executable_with_shebang():
    cfg = _load_hooks_config()
    for event, entries in cfg["hooks"].items():
        for entry in entries:
            for hook in entry["hooks"]:
                path = _resolve(hook["command"], REPO)
                assert path.exists(), f"{event}: hook script missing: {path}"
                assert os.access(path, os.X_OK), (
                    f"{event}: hook script not executable (run `chmod +x`): {path}"
                )
                first_line = path.read_text(encoding="utf-8").splitlines()[0]
                assert first_line.startswith("#!"), (
                    f"{event}: hook script missing shebang: {first_line!r}"
                )


# --- End-to-end plugin install flow -----------------------------------------


@pytest.fixture
def user_project(tmp_path: Path) -> Path:
    """A fresh user project (separate from the plugin root)."""
    proj = tmp_path / "user-project"
    proj.mkdir()
    (proj / ".claude").mkdir()
    return proj


def test_install_precompact_hook_writes_memory_under_user_project(user_project):
    """A user installs the plugin, runs Claude Code in their project, and
    auto-compact fires. The hook must write memory under the USER project
    (not the plugin root)."""
    cfg = _load_hooks_config()
    cmd = cfg["hooks"]["PreCompact"][0]["hooks"][0]["command"]

    result = _invoke(
        cmd,
        payload={
            "session_id": "install-e2e",
            "transcript_path": str(REPO / "tests/fixtures/transcript_with_todos.jsonl"),
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        },
        cwd=user_project,
        plugin_root=REPO,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}

    mem = mem_lib.find_memory_path(user_project, "install-e2e")
    assert mem is not None, "memory.md should land under the user's project, not the plugin root"
    content = mem.read_text()
    assert "## Active Task" in content
    assert "refactor auth module" in content
    assert "## Open Todos" in content

    # Plugin root must not have been polluted with compaction state.
    assert mem_lib.find_memory_path(REPO, "install-e2e") is None


def test_install_user_prompt_hook_injects_pointer_when_memory_exists(user_project):
    """Second half of the pair: once PreCompact has written memory.md,
    UserPromptSubmit must inject a pointer via `additionalContext`."""
    mem_dir = user_project / ".claude/compact-memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "2026-01-01T00-00-00Z_install-e2e.md").write_text(
        "# Session Memory\n\n## Active Task\n> test prompt\n"
    )

    cfg = _load_hooks_config()
    cmd = cfg["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]

    result = _invoke(
        cmd,
        payload={
            "session_id": "install-e2e",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "continue",
        },
        cwd=user_project,
        plugin_root=REPO,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    hook_out = output["hookSpecificOutput"]
    assert hook_out["hookEventName"] == "UserPromptSubmit"
    ctx = hook_out["additionalContext"]
    assert "install-e2e" in ctx
    assert ".claude/compact-memory" in ctx


def test_install_user_prompt_hook_is_noop_before_first_compact(user_project):
    """If no memory file exists yet, UserPromptSubmit must stay silent."""
    cfg = _load_hooks_config()
    cmd = cfg["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]

    result = _invoke(
        cmd,
        payload={
            "session_id": "install-e2e-noop",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "hello",
        },
        cwd=user_project,
        plugin_root=REPO,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}


def test_install_hooks_work_without_cc_compact_on_pythonpath(user_project):
    """Plugin must be self-contained — no hidden dependency on a
    pip-installed `cc_compact` package. We invoke with a minimal env
    (no PYTHONPATH, no conftest-injected sys.path) and assert the
    PreCompact hook still works purely via the scripts shipped in the plugin.
    """
    cfg = _load_hooks_config()
    cmd = cfg["hooks"]["PreCompact"][0]["hooks"][0]["command"]
    resolved = _resolve(cmd, REPO)

    minimal_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
    }
    result = subprocess.run(
        [str(resolved)],
        input=json.dumps({
            "session_id": "no-pythonpath",
            "transcript_path": str(REPO / "tests/fixtures/transcript_with_todos.jsonl"),
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        }),
        capture_output=True, text=True, cwd=user_project, env=minimal_env,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"plugin hook failed with minimal env — is there a hidden "
        f"PYTHONPATH dependency?\nstderr: {result.stderr}"
    )
    assert mem_lib.find_memory_path(user_project, "no-pythonpath") is not None
