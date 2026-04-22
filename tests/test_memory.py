from __future__ import annotations

from pathlib import Path

from cc_compact.lib import memory


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


def test_memory_path_has_datetime_prefix(project_root):
    path = memory.memory_path(project_root, "sid-x")
    name = path.name
    # Format: <YYYY-MM-DDTHH-MM-SSZ>_<session_id>.md
    assert name.endswith("_sid-x.md")
    prefix = name[: name.index("_sid-x.md")]
    assert len(prefix) == len("2026-04-22T10-30-45Z")
    assert prefix[4] == "-" and prefix[7] == "-" and prefix[10] == "T"


def test_find_memory_path_returns_none_when_missing(project_root):
    assert memory.find_memory_path(project_root, "no-such-sid") is None


def test_find_memory_path_finds_new_format(project_root):
    d = memory.memory_dir(project_root)
    f = d / "2026-04-22T10-00-00Z_sid-y.md"
    f.write_text("hello")
    assert memory.find_memory_path(project_root, "sid-y") == f


def test_find_memory_path_returns_latest_when_multiple(project_root):
    d = memory.memory_dir(project_root)
    old = d / "2026-04-22T09-00-00Z_sid-z.md"
    new = d / "2026-04-22T10-00-00Z_sid-z.md"
    old.write_text("old")
    new.write_text("new")
    assert memory.find_memory_path(project_root, "sid-z") == new


def test_find_memory_path_falls_back_to_legacy(project_root):
    d = memory.memory_dir(project_root)
    legacy = d / "sid-legacy.md"
    legacy.write_text("legacy")
    assert memory.find_memory_path(project_root, "sid-legacy") == legacy


def test_trace_path(project_root):
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


def test_append_trace_disabled_by_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_SMART_COMPACT_TRACE", "0")
    trace = tmp_path / "trace.jsonl"
    memory.append_trace(trace, {"hook": "Test"})
    assert not trace.exists()


def test_read_preferences_returns_none_when_file_missing(tmp_path):
    assert memory.read_preferences_section(tmp_path / "nope.md") is None


def test_read_preferences_returns_none_when_section_missing(tmp_path):
    p = tmp_path / "mem.md"
    p.write_text("# Session Memory\n\n## Active Task\n> foo\n")
    assert memory.read_preferences_section(p) is None


def test_read_preferences_returns_body_of_section(tmp_path):
    p = tmp_path / "mem.md"
    p.write_text(
        "# Session Memory\n\n"
        "## Active Task\n> foo\n\n"
        "## Preferences\n"
        "_instructions_\n\n"
        "- use pnpm\n"
        "- never mock DB\n"
    )
    body = memory.read_preferences_section(p)
    assert body is not None
    assert "use pnpm" in body
    assert "never mock DB" in body


def test_read_preferences_stops_at_next_h2(tmp_path):
    p = tmp_path / "mem.md"
    p.write_text(
        "## Preferences\n- x\n\n## Trailing\n- should not leak\n"
    )
    body = memory.read_preferences_section(p)
    assert body is not None
    assert "- x" in body
    assert "should not leak" not in body


def test_find_project_root_picks_nearest_claude(tmp_path):
    outer = tmp_path / "outer"
    (outer / ".claude").mkdir(parents=True)
    inner = outer / "sub" / "inner"
    (inner / ".claude").mkdir(parents=True)
    deepest = inner / "src"
    deepest.mkdir(parents=True)
    assert memory.find_project_root(deepest) == inner
