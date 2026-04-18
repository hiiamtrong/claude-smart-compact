from __future__ import annotations

from pathlib import Path

from hooks.lib import memory


def test_find_project_root_walks_up_to_claude_dir(tmp_path):
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    nested = root / "src" / "deep"
    nested.mkdir(parents=True)
    assert memory.find_project_root(nested) == root


def test_find_project_root_falls_back_to_start(tmp_path):
    assert memory.find_project_root(tmp_path) == tmp_path


def test_memory_dir_is_created_on_first_access(project_root):
    d = memory.memory_dir(project_root)
    assert d == project_root / ".claude" / "compact-memory"
    assert d.is_dir()


def test_memory_path_and_trace_path(project_root):
    assert (
        memory.memory_path(project_root, "sid-x")
        == project_root / ".claude" / "compact-memory" / "sid-x.md"
    )
    assert (
        memory.trace_path(project_root, "sid-x")
        == project_root / ".claude" / "compact-memory" / "sid-x.trace.jsonl"
    )
