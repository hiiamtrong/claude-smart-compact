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


import json


def test_write_atomic_writes_file(tmp_path):
    target = tmp_path / "out.md"
    memory.write_atomic(target, "hello")
    assert target.read_text() == "hello"


def test_write_atomic_leaves_no_tmp_file(tmp_path):
    target = tmp_path / "out.md"
    memory.write_atomic(target, "hello")
    siblings = list(tmp_path.iterdir())
    assert siblings == [target]


def test_write_atomic_overwrites(tmp_path):
    target = tmp_path / "out.md"
    memory.write_atomic(target, "v1")
    memory.write_atomic(target, "v2")
    assert target.read_text() == "v2"


def test_append_trace_writes_jsonl_with_timestamp(tmp_path):
    trace = tmp_path / "sid.trace.jsonl"
    memory.append_trace(trace, {"hook": "PreCompact", "ok": True})
    memory.append_trace(trace, {"hook": "UserPromptSubmit", "ok": True})
    lines = trace.read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        event = json.loads(line)
        assert "ts" in event
        assert event["ts"].endswith("Z")
        assert "hook" in event
