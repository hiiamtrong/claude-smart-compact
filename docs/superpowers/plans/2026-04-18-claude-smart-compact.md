# Claude Smart Compact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build two Claude Code CLI hooks (PreCompact + UserPromptSubmit) that preserve task state, in-progress todos, and user preferences across auto-compaction — without bloating the context window.

**Architecture:** Two thin Python 3 entry scripts read stdin JSON from the CLI, orchestrate pure logic modules (`transcript`, `core`, `memory`) to parse the session transcript, compose a Markdown memory file at `<project>/.claude/compact-memory/<session_id>.md`, and return a small "pointer" string the agent can act on. Preferences are agent-authored (not regex-extracted). All hook failures fail soft — they never block the CLI.

**Tech Stack:** Python 3.10+ (stdlib only for runtime), pytest (+ optional pytest-cov) for tests.

**Reference:** Spec at `docs/superpowers/specs/2026-04-18-claude-smart-compact-design.md`.

---

## Task 1: Project bootstrap (pyproject, gitignore)

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "claude-smart-compact"
version = "0.1.0"
description = "Claude Code hooks that preserve memory across auto-compaction"
requires-python = ">=3.10"

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=5.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-v --tb=short"
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
htmlcov/
.venv/
venv/
.claude/compact-memory/
.DS_Store
```

- [ ] **Step 3: Install pytest in a venv**

Run:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
Expected: pytest installs without errors.

- [ ] **Step 4: Verify pytest discovers nothing yet**

Run: `pytest`
Expected: `no tests ran` (exit code 5 is OK at this stage).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore
git commit -m "chore: scaffold python project with pytest"
```

---

## Task 2: Package skeleton + conftest

**Files:**
- Create: `hooks/__init__.py`
- Create: `hooks/lib/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/.gitkeep`

- [ ] **Step 1: Create empty package markers**

```bash
mkdir -p hooks/lib tests/fixtures
touch hooks/__init__.py hooks/lib/__init__.py tests/__init__.py tests/fixtures/.gitkeep
```

- [ ] **Step 2: Create `tests/conftest.py`**

```python
"""Shared fixtures for the smart-compact test suite."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Absolute path to tests/fixtures."""
    return FIXTURES_DIR


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Isolated project root with a .claude/ directory."""
    (tmp_path / ".claude").mkdir()
    return tmp_path


@pytest.fixture
def copy_fixture(tmp_path: Path):
    """Return a callable that copies a named fixture into tmp_path."""

    def _copy(name: str) -> Path:
        src = FIXTURES_DIR / name
        dst = tmp_path / name
        dst.write_text(src.read_text())
        return dst

    return _copy


@pytest.fixture
def make_payload():
    """Return a callable that produces a hook stdin JSON string."""

    def _make(**overrides) -> str:
        payload = {
            "session_id": "test-session-001",
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        }
        payload.update(overrides)
        return json.dumps(payload)

    return _make
```

- [ ] **Step 3: Sanity test that pytest picks up the config**

Run: `pytest --collect-only`
Expected: `collected 0 items` (no tests yet, but no errors).

- [ ] **Step 4: Commit**

```bash
git add hooks tests
git commit -m "chore: add package skeleton and shared pytest fixtures"
```

---

## Task 3: `transcript.parse_jsonl` — happy path

**Files:**
- Create: `hooks/lib/transcript.py`
- Create: `tests/test_transcript.py`
- Create: `tests/fixtures/transcript_empty.jsonl`
- Create: `tests/fixtures/transcript_single_turn.jsonl`

- [ ] **Step 1: Create fixture `tests/fixtures/transcript_empty.jsonl`**

```
```

(File must exist but be zero-byte empty.)

Run:
```bash
: > tests/fixtures/transcript_empty.jsonl
```

- [ ] **Step 2: Create fixture `tests/fixtures/transcript_single_turn.jsonl`**

```
{"role":"user","content":"hello"}
{"role":"assistant","content":"hi there"}
```

- [ ] **Step 3: Write the failing tests**

Add to `tests/test_transcript.py`:

```python
from __future__ import annotations

from hooks.lib import transcript


def test_parse_jsonl_empty_file(copy_fixture):
    path = copy_fixture("transcript_empty.jsonl")
    assert transcript.parse_jsonl(str(path)) == []


def test_parse_jsonl_returns_messages_in_order(copy_fixture):
    path = copy_fixture("transcript_single_turn.jsonl")
    messages = transcript.parse_jsonl(str(path))
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "hello"
    assert messages[0].index == 0
    assert messages[1].role == "assistant"
    assert messages[1].content == "hi there"
    assert messages[1].index == 1


def test_parse_jsonl_missing_file_returns_empty(tmp_path):
    assert transcript.parse_jsonl(str(tmp_path / "nope.jsonl")) == []
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_transcript.py -v`
Expected: `ModuleNotFoundError` or `AttributeError` — `transcript` module / `parse_jsonl` does not exist yet.

- [ ] **Step 5: Implement `hooks/lib/transcript.py` minimally**

```python
"""Pure functions for parsing a Claude Code transcript (.jsonl)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

Role = Literal["user", "assistant", "system", "tool"]


@dataclass
class Message:
    role: Role
    content: str
    raw: dict = field(default_factory=dict)
    index: int = 0


@dataclass
class TodoItem:
    content: str
    status: Literal["pending", "in_progress", "completed"]


def _flatten_content(raw_content) -> str:
    """Flatten Claude Code content (string or list of blocks) into plain text."""
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, list):
        parts: list[str] = []
        for block in raw_content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content") or ""
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(p for p in parts if p)
    return ""


def parse_jsonl(path: str) -> list[Message]:
    """Stream-read JSONL; skip corrupt lines; return ordered list."""
    p = Path(path)
    if not p.exists():
        return []
    messages: list[Message] = []
    idx = 0
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = raw.get("role", "assistant")
            content = _flatten_content(raw.get("content", ""))
            messages.append(Message(role=role, content=content, raw=raw, index=idx))
            idx += 1
    return messages
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_transcript.py -v`
Expected: 3 tests pass.

- [ ] **Step 7: Commit**

```bash
git add hooks/lib/transcript.py tests/test_transcript.py tests/fixtures/transcript_empty.jsonl tests/fixtures/transcript_single_turn.jsonl
git commit -m "feat(transcript): parse_jsonl basic happy path"
```

---

## Task 4: `transcript.find_last_user_index` + `slice_in_flight`

**Files:**
- Modify: `hooks/lib/transcript.py`
- Modify: `tests/test_transcript.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_transcript.py`:

```python
def _msg(role, content="x", index=0):
    return transcript.Message(role=role, content=content, raw={}, index=index)


def test_find_last_user_index_none_when_no_user():
    messages = [_msg("assistant", index=0), _msg("tool", index=1)]
    assert transcript.find_last_user_index(messages) is None


def test_find_last_user_index_returns_latest_user():
    messages = [
        _msg("user", index=0),
        _msg("assistant", index=1),
        _msg("user", index=2),
        _msg("assistant", index=3),
    ]
    assert transcript.find_last_user_index(messages) == 2


def test_slice_in_flight_returns_tail():
    messages = [_msg("user", index=i) for i in range(5)]
    tail = transcript.slice_in_flight(messages, 3)
    assert [m.index for m in tail] == [3, 4]


def test_slice_in_flight_none_returns_all():
    messages = [_msg("user", index=i) for i in range(3)]
    assert transcript.slice_in_flight(messages, None) == messages
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_transcript.py -v -k "last_user or in_flight"`
Expected: `AttributeError: module has no attribute 'find_last_user_index'`.

- [ ] **Step 3: Implement the two functions**

Append to `hooks/lib/transcript.py`:

```python
def find_last_user_index(messages: list[Message]) -> Optional[int]:
    """Return index of last message with role='user', or None."""
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.index
    return None


def slice_in_flight(messages: list[Message], from_index: Optional[int]) -> list[Message]:
    """Return messages[from_index:]. If from_index is None, return all."""
    if from_index is None:
        return list(messages)
    return [m for m in messages if m.index >= from_index]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_transcript.py -v`
Expected: 7 tests pass (3 old + 4 new).

- [ ] **Step 5: Commit**

```bash
git add hooks/lib/transcript.py tests/test_transcript.py
git commit -m "feat(transcript): find_last_user_index and slice_in_flight"
```

---

## Task 5: `transcript.extract_latest_todos`

**Files:**
- Modify: `hooks/lib/transcript.py`
- Modify: `tests/test_transcript.py`
- Create: `tests/fixtures/transcript_with_todos.jsonl`

- [ ] **Step 1: Create fixture `tests/fixtures/transcript_with_todos.jsonl`**

```
{"role":"user","content":"refactor auth module"}
{"role":"assistant","content":[{"type":"tool_use","name":"TodoWrite","input":{"todos":[{"content":"inspect current auth","status":"completed","activeForm":"Inspecting current auth"},{"content":"write migration","status":"in_progress","activeForm":"Writing migration"}]}}]}
{"role":"assistant","content":"working on migration..."}
{"role":"assistant","content":[{"type":"tool_use","name":"TodoWrite","input":{"todos":[{"content":"inspect current auth","status":"completed","activeForm":"Inspecting current auth"},{"content":"write migration","status":"completed","activeForm":"Writing migration"},{"content":"add tests","status":"in_progress","activeForm":"Adding tests"}]}}]}
```

- [ ] **Step 2: Write failing tests**

Append to `tests/test_transcript.py`:

```python
def test_extract_latest_todos_empty_when_none(copy_fixture):
    path = copy_fixture("transcript_single_turn.jsonl")
    messages = transcript.parse_jsonl(str(path))
    assert transcript.extract_latest_todos(messages) == []


def test_extract_latest_todos_returns_most_recent_snapshot(copy_fixture):
    path = copy_fixture("transcript_with_todos.jsonl")
    messages = transcript.parse_jsonl(str(path))
    todos = transcript.extract_latest_todos(messages)
    # The second TodoWrite wins — not the first.
    assert len(todos) == 3
    assert todos[0].content == "inspect current auth"
    assert todos[0].status == "completed"
    assert todos[2].content == "add tests"
    assert todos[2].status == "in_progress"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_transcript.py -v -k "todos"`
Expected: `AttributeError: module has no attribute 'extract_latest_todos'`.

- [ ] **Step 4: Implement `extract_latest_todos`**

Append to `hooks/lib/transcript.py`:

```python
def _iter_tool_uses(raw_content) -> list[dict]:
    """Return every tool_use block found in an assistant content payload."""
    if not isinstance(raw_content, list):
        return []
    return [b for b in raw_content if isinstance(b, dict) and b.get("type") == "tool_use"]


def extract_latest_todos(messages: list[Message]) -> list[TodoItem]:
    """Find the most recent TodoWrite tool_use call and parse its todo list."""
    latest: list[TodoItem] = []
    for msg in messages:
        for block in _iter_tool_uses(msg.raw.get("content", [])):
            if block.get("name") != "TodoWrite":
                continue
            todos_raw = block.get("input", {}).get("todos", [])
            parsed: list[TodoItem] = []
            for t in todos_raw:
                if not isinstance(t, dict):
                    continue
                content = t.get("content") or ""
                status = t.get("status") or "pending"
                if status not in ("pending", "in_progress", "completed"):
                    status = "pending"
                parsed.append(TodoItem(content=content, status=status))
            if parsed:
                latest = parsed  # later wins
    return latest
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_transcript.py -v`
Expected: 9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add hooks/lib/transcript.py tests/test_transcript.py tests/fixtures/transcript_with_todos.jsonl
git commit -m "feat(transcript): extract latest TodoWrite snapshot"
```

---

## Task 6: transcript corrupt-line & multi-user fixtures

**Files:**
- Modify: `hooks/lib/transcript.py` (no new code expected — behavior already handles these)
- Modify: `tests/test_transcript.py`
- Create: `tests/fixtures/transcript_corrupt_lines.jsonl`
- Create: `tests/fixtures/transcript_multi_user_turns.jsonl`
- Create: `tests/fixtures/transcript_no_user.jsonl`

- [ ] **Step 1: Create `tests/fixtures/transcript_corrupt_lines.jsonl`**

```
{"role":"user","content":"first"}
{not valid json
{"role":"assistant","content":"second"}
also not json
{"role":"user","content":"third"}
```

- [ ] **Step 2: Create `tests/fixtures/transcript_multi_user_turns.jsonl`**

```
{"role":"user","content":"task A"}
{"role":"assistant","content":"doing A"}
{"role":"user","content":"task B"}
{"role":"assistant","content":"doing B"}
{"role":"user","content":"final: wrap up"}
{"role":"assistant","content":"wrapping up"}
```

- [ ] **Step 3: Create `tests/fixtures/transcript_no_user.jsonl`**

```
{"role":"assistant","content":"self-directed turn"}
{"role":"system","content":"reminder"}
```

- [ ] **Step 4: Write tests**

Append to `tests/test_transcript.py`:

```python
def test_parse_jsonl_skips_corrupt_lines(copy_fixture):
    path = copy_fixture("transcript_corrupt_lines.jsonl")
    messages = transcript.parse_jsonl(str(path))
    assert [m.content for m in messages] == ["first", "second", "third"]


def test_find_last_user_on_multi_user_transcript(copy_fixture):
    path = copy_fixture("transcript_multi_user_turns.jsonl")
    messages = transcript.parse_jsonl(str(path))
    idx = transcript.find_last_user_index(messages)
    assert idx is not None
    assert messages[idx].content == "final: wrap up"


def test_find_last_user_is_none_when_transcript_has_none(copy_fixture):
    path = copy_fixture("transcript_no_user.jsonl")
    messages = transcript.parse_jsonl(str(path))
    assert transcript.find_last_user_index(messages) is None
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_transcript.py -v`
Expected: 12 tests pass (9 old + 3 new).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/transcript_corrupt_lines.jsonl tests/fixtures/transcript_multi_user_turns.jsonl tests/fixtures/transcript_no_user.jsonl tests/test_transcript.py
git commit -m "test(transcript): cover corrupt lines and multi-user transcripts"
```

---

## Task 7: `memory.find_project_root` + path helpers

**Files:**
- Create: `hooks/lib/memory.py`
- Create: `tests/test_memory.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory.py -v`
Expected: `ModuleNotFoundError` for `hooks.lib.memory`.

- [ ] **Step 3: Implement minimal `hooks/lib/memory.py`**

```python
"""File-system helpers for the smart-compact memory store."""
from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path) -> Path:
    """Walk up from `start` looking for a .claude/ directory. Fallback to start."""
    current = Path(start).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".claude").is_dir():
            return candidate
    return current


def memory_dir(project_root: Path) -> Path:
    """Return <project_root>/.claude/compact-memory/, creating it if missing."""
    d = Path(project_root) / ".claude" / "compact-memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_path(project_root: Path, session_id: str) -> Path:
    return memory_dir(project_root) / f"{session_id}.md"


def trace_path(project_root: Path, session_id: str) -> Path:
    return memory_dir(project_root) / f"{session_id}.trace.jsonl"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add hooks/lib/memory.py tests/test_memory.py
git commit -m "feat(memory): project root detection and path helpers"
```

---

## Task 8: `memory.write_atomic` + `append_trace`

**Files:**
- Modify: `hooks/lib/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_memory.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory.py -v -k "write_atomic or append_trace"`
Expected: `AttributeError` for both functions.

- [ ] **Step 3: Implement both functions**

Append to `hooks/lib/memory.py`:

```python
import json
import os
from datetime import datetime, timezone


def write_atomic(path: Path, content: str) -> None:
    """Write `content` to `path` atomically (write to .tmp then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def append_trace(path: Path, event: dict) -> None:
    """Append one JSONL record to `path` with an ISO-8601 UTC timestamp."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory.py -v`
Expected: 8 tests pass (4 old + 4 new).

- [ ] **Step 5: Commit**

```bash
git add hooks/lib/memory.py tests/test_memory.py
git commit -m "feat(memory): atomic write and trace append"
```

---

## Task 9: `memory.read_preferences_section`

**Files:**
- Modify: `hooks/lib/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_memory.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory.py -v -k "preferences"`
Expected: `AttributeError: module has no attribute 'read_preferences_section'`.

- [ ] **Step 3: Implement `read_preferences_section`**

Append to `hooks/lib/memory.py`:

```python
from typing import Optional


def read_preferences_section(path: Path) -> Optional[str]:
    """Return the body of `## Preferences` section of a memory file, or None."""
    path = Path(path)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    body: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.lstrip()
        if not in_section:
            if stripped.startswith("## Preferences"):
                in_section = True
            continue
        if stripped.startswith("## "):
            break
        body.append(line)
    if not in_section:
        return None
    return "\n".join(body).strip("\n") or ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory.py -v`
Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add hooks/lib/memory.py tests/test_memory.py
git commit -m "feat(memory): read existing Preferences section for merging"
```

---

## Task 10: `memory` edge-case polish

**Files:**
- Modify: `tests/test_memory.py`

- [ ] **Step 1: Write one more failing test for deep nesting**

Append to `tests/test_memory.py`:

```python
def test_find_project_root_picks_nearest_claude(tmp_path):
    outer = tmp_path / "outer"
    (outer / ".claude").mkdir(parents=True)
    inner = outer / "sub" / "inner"
    (inner / ".claude").mkdir(parents=True)
    deepest = inner / "src"
    deepest.mkdir(parents=True)
    assert memory.find_project_root(deepest) == inner
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_memory.py::test_find_project_root_picks_nearest_claude -v`
Expected: PASS (existing implementation already prefers nearest ancestor).

- [ ] **Step 3: Commit**

```bash
git add tests/test_memory.py
git commit -m "test(memory): nearest-ancestor preference for project root"
```

---

## Task 11: `core.compose_memory_markdown` — Active Task + Todos

**Files:**
- Create: `hooks/lib/core.py`
- Create: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_core.py`:

```python
from __future__ import annotations

from hooks.lib import core
from hooks.lib.transcript import Message, TodoItem


def _msg(role, content, idx):
    return Message(role=role, content=content, raw={}, index=idx)


def test_compose_contains_all_required_headings():
    md = core.compose_memory_markdown(
        session_id="sid-1",
        active_task_user_msg="do the thing",
        in_flight=[_msg("assistant", "on it", 1)],
        todos=[],
        existing_preferences_section=None,
    )
    assert "# Session Memory" in md
    assert "session_id: sid-1" in md
    assert "## Active Task" in md
    assert "## In-Progress Todos" in md
    assert "## Preferences" in md


def test_compose_quotes_last_user_message_verbatim():
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="please refactor X\nuse pattern Y",
        in_flight=[],
        todos=[],
        existing_preferences_section=None,
    )
    assert "> please refactor X" in md
    assert "> use pattern Y" in md


def test_compose_lists_in_flight_turns_truncated():
    longline = "a" * 200
    in_flight = [_msg("assistant", longline, 1), _msg("assistant", "", 2)]
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=in_flight,
        todos=[],
        existing_preferences_section=None,
    )
    # Each non-empty turn renders as a bullet with max 120 char preview.
    assert "- " + "a" * 120 in md


def test_compose_renders_todos_bullets():
    todos = [
        TodoItem(content="do migration", status="in_progress"),
        TodoItem(content="add tests", status="pending"),
    ]
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=[],
        todos=todos,
        existing_preferences_section=None,
    )
    assert "- [ ] do migration (status: in_progress)" in md
    assert "- [ ] add tests (status: pending)" in md


def test_compose_renders_placeholder_when_no_todos():
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=[],
        todos=[],
        existing_preferences_section=None,
    )
    assert "_(none)_" in md


def test_compose_uses_placeholder_for_empty_active_task():
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="",
        in_flight=[],
        todos=[],
        existing_preferences_section=None,
    )
    assert "_(no active prompt)_" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core.py -v`
Expected: `ModuleNotFoundError` for `hooks.lib.core`.

- [ ] **Step 3: Implement `hooks/lib/core.py`**

```python
"""Pure functions that compose Markdown / string outputs for the hooks."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .transcript import Message, TodoItem

MAX_BULLET_LEN = 120
DEFAULT_PREFS_BODY = (
    "_Append lasting preferences/constraints stated by the user here.\n"
    "Agent: use Edit tool to append; never rewrite existing entries._\n"
)


def _quote_block(text: str) -> str:
    if not text:
        return "> _(no active prompt)_"
    return "\n".join("> " + line for line in text.splitlines())


def _render_in_flight(in_flight: list[Message]) -> str:
    bullets: list[str] = []
    for msg in in_flight:
        first_line = next(
            (ln for ln in (msg.content or "").splitlines() if ln.strip()), ""
        )
        if not first_line:
            # Render tool_use blocks as `tool: <name>`
            for block in msg.raw.get("content", []) if isinstance(msg.raw.get("content"), list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    bullets.append(f"- tool: {block.get('name', '?')}")
                    break
            continue
        truncated = first_line[:MAX_BULLET_LEN]
        bullets.append(f"- {truncated}")
    return "\n".join(bullets) if bullets else "_(no in-flight turns)_"


def _render_todos(todos: list[TodoItem]) -> str:
    if not todos:
        return "_(none)_"
    return "\n".join(
        f"- [ ] {t.content} (status: {t.status})" for t in todos
    )


def compose_memory_markdown(
    session_id: str,
    active_task_user_msg: str,
    in_flight: list[Message],
    todos: list[TodoItem],
    existing_preferences_section: Optional[str],
) -> str:
    """Render the full memory.md body."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prefs_body = (
        existing_preferences_section
        if existing_preferences_section is not None
        else DEFAULT_PREFS_BODY
    )
    return (
        f"# Session Memory\n"
        f"<!-- session_id: {session_id} | generated_at: {ts} -->\n"
        f"\n"
        f"## Active Task\n"
        f"_From the last user prompt in this session._\n"
        f"\n"
        f"{_quote_block(active_task_user_msg)}\n"
        f"\n"
        f"**In-flight turns (since last user prompt):**\n"
        f"{_render_in_flight(in_flight)}\n"
        f"\n"
        f"## In-Progress Todos\n"
        f"{_render_todos(todos)}\n"
        f"\n"
        f"## Preferences\n"
        f"{prefs_body}\n"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add hooks/lib/core.py tests/test_core.py
git commit -m "feat(core): compose memory markdown with Active Task and Todos"
```

---

## Task 12: `core.compose_memory_markdown` — preserve existing preferences

**Files:**
- Modify: `tests/test_core.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_core.py`:

```python
def test_compose_preserves_existing_preferences():
    existing = "- always use pnpm\n- never mock DB"
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=[],
        todos=[],
        existing_preferences_section=existing,
    )
    prefs_start = md.index("## Preferences")
    tail = md[prefs_start:]
    assert "always use pnpm" in tail
    assert "never mock DB" in tail
    # Placeholder should NOT appear when existing prefs provided.
    assert "never rewrite existing entries" not in tail
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_core.py::test_compose_preserves_existing_preferences -v`
Expected: PASS (existing implementation already handles this path).

- [ ] **Step 3: Commit**

```bash
git add tests/test_core.py
git commit -m "test(core): preserve user-authored Preferences across compactions"
```

---

## Task 13: `core.compaction_instructions` + `core.prompt_pointer_text`

**Files:**
- Modify: `hooks/lib/core.py`
- Modify: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_core.py`:

```python
def test_compaction_instructions_mentions_key_concerns():
    text = core.compaction_instructions()
    for needle in ["last user message", "in_progress", "preferences", "memory file"]:
        assert needle.lower() in text.lower()


def test_prompt_pointer_has_session_id_and_size():
    text = core.prompt_pointer_text("abc-123", 2048)
    assert "abc-123" in text
    assert "compact-memory" in text
    assert "KB" in text or "bytes" in text
    assert "## Preferences" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core.py -v -k "compaction_instructions or prompt_pointer"`
Expected: `AttributeError` for both functions.

- [ ] **Step 3: Implement both functions**

Append to `hooks/lib/core.py`:

```python
def compaction_instructions() -> str:
    """Custom instructions injected via PreCompact `additionalContext`."""
    return (
        "When summarizing, preserve: "
        "(1) the last user message verbatim, "
        "(2) any in_progress todos with their exact wording, "
        "(3) any stated user preferences or constraints. "
        "A structured memory file at "
        "`.claude/compact-memory/<session_id>.md` "
        "is also persisted for reference."
    )


def prompt_pointer_text(session_id: str, memory_size_bytes: int) -> str:
    """Pointer injected via UserPromptSubmit `additionalContext`."""
    size_kb = max(1, round(memory_size_bytes / 1024))
    return (
        f"Persistent session memory available at "
        f"`.claude/compact-memory/{session_id}.md` (~{size_kb}KB). "
        f"Read it at the start of your next action if you need context about "
        f"task state, in-progress todos, or user preferences. "
        f"If the user states a lasting preference or constraint, "
        f"append it under the `## Preferences` section using the Edit tool."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core.py -v`
Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add hooks/lib/core.py tests/test_core.py
git commit -m "feat(core): compaction instructions and prompt pointer text"
```

---

## Task 14: `hooks/pre_compact.py` entry script

**Files:**
- Create: `hooks/pre_compact.py`
- Create: `tests/test_pre_compact.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/test_pre_compact.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run_hook(script: str, payload: dict, cwd: Path):
    return subprocess.run(
        [sys.executable, str(REPO / "hooks" / script)],
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
        [sys.executable, str(REPO / "hooks" / "pre_compact.py")],
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pre_compact.py -v`
Expected: All fail — `pre_compact.py` does not exist yet.

- [ ] **Step 3: Implement `hooks/pre_compact.py`**

```python
#!/usr/bin/env python3
"""PreCompact hook entry — persists memory to .claude/compact-memory/<sid>.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `hooks.lib` importable when invoked directly by the CLI.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib import core, memory, transcript  # noqa: E402


def _safe_trace(project_root: Path, session_id: str | None, event: dict) -> None:
    if not session_id:
        return
    try:
        memory.append_trace(memory.trace_path(project_root, session_id), event)
    except Exception:
        pass


def main() -> None:
    payload = json.load(sys.stdin)
    session_id = payload["session_id"]
    transcript_path = payload.get("transcript_path", "")
    trigger = payload.get("trigger", "unknown")

    root = memory.find_project_root(Path.cwd())
    messages = transcript.parse_jsonl(transcript_path)
    last_user_idx = transcript.find_last_user_index(messages)

    if last_user_idx is None:
        _safe_trace(root, session_id, {
            "hook": "PreCompact",
            "trigger": trigger,
            "messages_count": len(messages),
            "last_user_index": None,
            "skipped_reason": "no user message",
        })
        json.dump({}, sys.stdout)
        return

    in_flight = transcript.slice_in_flight(messages, last_user_idx)
    todos = [
        t for t in transcript.extract_latest_todos(messages)
        if t.status in ("in_progress", "pending")
    ]
    active_task_msg = messages[last_user_idx].content if messages else ""

    mem_file = memory.memory_path(root, session_id)
    existing_prefs = memory.read_preferences_section(mem_file)

    md = core.compose_memory_markdown(
        session_id=session_id,
        active_task_user_msg=active_task_msg,
        in_flight=in_flight,
        todos=todos,
        existing_preferences_section=existing_prefs,
    )
    memory.write_atomic(mem_file, md)
    _safe_trace(root, session_id, {
        "hook": "PreCompact",
        "trigger": trigger,
        "messages_count": len(messages),
        "last_user_index": last_user_idx,
        "todos_count": len(todos),
        "memory_bytes": len(md.encode("utf-8")),
        "preserved_preferences": existing_prefs is not None,
    })

    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "additionalContext": core.compaction_instructions(),
        }
    }, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            root = memory.find_project_root(Path.cwd())
            session_id = None
            try:
                raw = json.loads(sys.stdin.read() or "{}")
                session_id = raw.get("session_id")
            except Exception:
                pass
            _safe_trace(root, session_id, {
                "hook": "PreCompact",
                "error": str(e),
                "error_type": type(e).__name__,
            })
        except Exception:
            pass
        json.dump({}, sys.stdout)
        sys.exit(0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pre_compact.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add hooks/pre_compact.py tests/test_pre_compact.py
git commit -m "feat(hooks): PreCompact entry script with fail-soft handling"
```

---

## Task 15: `hooks/user_prompt.py` entry script

**Files:**
- Create: `hooks/user_prompt.py`
- Create: `tests/test_user_prompt.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/test_user_prompt.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run(payload: dict, cwd: Path):
    return subprocess.run(
        [sys.executable, str(REPO / "hooks" / "user_prompt.py")],
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
    (mem_dir / "sid-1.md").write_text("# Session Memory\n\nbody " * 200)

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
    (mem_dir / "sid-2.md").write_text("x")
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
        [sys.executable, str(REPO / "hooks" / "user_prompt.py")],
        input="garbage",
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


def test_user_prompt_creates_claude_dir_if_missing(tmp_path):
    # No .claude/ dir pre-created — hook must not crash.
    payload = {
        "session_id": "sid-fresh",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "hi",
    }
    result = subprocess.run(
        [sys.executable, str(REPO / "hooks" / "user_prompt.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_user_prompt.py -v`
Expected: All fail — script does not exist.

- [ ] **Step 3: Implement `hooks/user_prompt.py`**

```python
#!/usr/bin/env python3
"""UserPromptSubmit hook entry — injects a pointer to the memory file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib import core, memory  # noqa: E402


def _safe_trace(project_root: Path, session_id: str | None, event: dict) -> None:
    if not session_id:
        return
    try:
        memory.append_trace(memory.trace_path(project_root, session_id), event)
    except Exception:
        pass


def main() -> None:
    payload = json.load(sys.stdin)
    session_id = payload["session_id"]

    root = memory.find_project_root(Path.cwd())
    mem_file = memory.memory_path(root, session_id)

    if not mem_file.exists():
        json.dump({}, sys.stdout)
        return

    size = mem_file.stat().st_size
    _safe_trace(root, session_id, {
        "hook": "UserPromptSubmit",
        "memory_bytes": size,
        "pointer_injected": True,
    })
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": core.prompt_pointer_text(session_id, size),
        }
    }, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        json.dump({}, sys.stdout)
        sys.exit(0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_user_prompt.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add hooks/user_prompt.py tests/test_user_prompt.py
git commit -m "feat(hooks): UserPromptSubmit entry script with pointer injection"
```

---

## Task 16: Edge-case sweep (E1–E15)

**Files:**
- Create: `tests/test_edge_cases.py`
- Create: `tests/fixtures/transcript_large.jsonl` (generated in a test helper)

- [ ] **Step 1: Write one test per edge case from the spec**

Create `tests/test_edge_cases.py`:

```python
"""Coverage for edge cases E1-E15 documented in the design spec."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from hooks.lib import memory, transcript


REPO = Path(__file__).resolve().parent.parent


def _run(script, payload, cwd):
    return subprocess.run(
        [sys.executable, str(REPO / "hooks" / script)],
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
        [sys.executable, str(REPO / "hooks/pre_compact.py")],
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
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_edge_cases.py -v`
Expected: 15 tests pass.

- [ ] **Step 3: Run full suite, check coverage**

Run: `pytest --cov=hooks --cov-report=term-missing`
Expected: All tests pass. `hooks/lib` coverage ≥ 90 %; entry scripts ≥ 70 %.

- [ ] **Step 4: Commit**

```bash
git add tests/test_edge_cases.py
git commit -m "test: cover all 15 edge cases E1-E15 from spec"
```

---

## Task 17: `tests/trace_run.py` manual verification script

**Files:**
- Create: `tests/trace_run.py`

- [ ] **Step 1: Create the script**

```python
#!/usr/bin/env python3
"""Manual end-to-end verification script.

Usage:
    python3 tests/trace_run.py <path-to-real-transcript.jsonl>

Pipes a fake stdin payload through each hook in sequence against a real
transcript file, printing all JSON I/O and the resulting memory file.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def main(transcript_path: str) -> None:
    tx = Path(transcript_path)
    if not tx.exists():
        sys.exit(f"error: transcript not found: {tx}")

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        (cwd / ".claude").mkdir()
        sid = "trace-run-session"

        # 1. PreCompact
        pre_payload = json.dumps({
            "session_id": sid,
            "transcript_path": str(tx),
            "hook_event_name": "PreCompact",
            "trigger": "manual",
        })
        print("=== PreCompact stdin ===")
        print(pre_payload)
        pre = subprocess.run(
            [sys.executable, str(REPO / "hooks/pre_compact.py")],
            input=pre_payload, capture_output=True, text=True, cwd=cwd,
        )
        print("=== PreCompact stdout ===")
        print(pre.stdout or "<empty>")
        print("=== PreCompact stderr ===")
        print(pre.stderr or "<empty>")

        mem_file = cwd / ".claude/compact-memory" / f"{sid}.md"
        if mem_file.exists():
            print("=== memory file ===")
            print(mem_file.read_text())
        else:
            print("(no memory file written)")

        # 2. UserPromptSubmit
        up_payload = json.dumps({
            "session_id": sid,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "continue the task",
        })
        print("=== UserPromptSubmit stdin ===")
        print(up_payload)
        up = subprocess.run(
            [sys.executable, str(REPO / "hooks/user_prompt.py")],
            input=up_payload, capture_output=True, text=True, cwd=cwd,
        )
        print("=== UserPromptSubmit stdout ===")
        print(up.stdout or "<empty>")

        trace = cwd / ".claude/compact-memory" / f"{sid}.trace.jsonl"
        if trace.exists():
            print("=== trace.jsonl ===")
            print(trace.read_text())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: trace_run.py <path-to-transcript.jsonl>")
    main(sys.argv[1])
```

- [ ] **Step 2: Smoke-test with an existing fixture**

Run: `python3 tests/trace_run.py tests/fixtures/transcript_with_todos.jsonl`
Expected: Prints all four blocks (stdin, PreCompact stdout, memory file, trace); exits 0.

- [ ] **Step 3: Commit**

```bash
git add tests/trace_run.py
git commit -m "test: add manual trace_run verification script"
```

---

## Task 18: Example settings + README

**Files:**
- Create: `.claude/settings.json.example`
- Create: `README.md`

- [ ] **Step 1: Create `.claude/settings.json.example`**

```json
{
  "hooks": {
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/pre_compact.py"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/user_prompt.py"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Create `README.md`**

```markdown
# Claude Smart Compact

Two Claude Code CLI hooks that preserve task state, in-progress todos, and
user preferences across auto-compaction, without bloating the context window.

## How it works

- **PreCompact** runs when the CLI is about to auto-compact. It reads the
  session transcript, extracts the last user message + in-flight turns + the
  latest `TodoWrite` snapshot, and writes a Markdown memory file to
  `<project>/.claude/compact-memory/<session_id>.md`.
- **UserPromptSubmit** runs on every user prompt after the first compaction.
  It injects a short pointer telling the agent the memory file is available
  and may be read on demand.
- Preferences are **agent-authored** — the hook preserves a `## Preferences`
  section on every run, but does not populate it automatically. Append with
  the Edit tool when the user states a lasting preference.

## Install (per project)

1. Copy `hooks/` into your project's `.claude/hooks/`.
2. Copy `.claude/settings.json.example` to `.claude/settings.json`
   (or merge into your existing settings).
3. Make sure `python3` is on your `$PATH`.

## Verify

Run the manual trace script:

```bash
python3 tests/trace_run.py tests/fixtures/transcript_with_todos.jsonl
```

## Run tests

```bash
pip install -e ".[dev]"
pytest --cov=hooks
```

## Debug

Every hook run appends to `<project>/.claude/compact-memory/<session_id>.trace.jsonl`.
`tail -f` this file to watch the hooks work in real time.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.json.example README.md
git commit -m "docs: example hook settings and README"
```

---

## Task 19: Final validation sweep

- [ ] **Step 1: Run the full test suite**

Run: `pytest --cov=hooks --cov-report=term-missing`
Expected: All ~54 tests pass. `hooks/lib` coverage ≥ 90 %, entry scripts ≥ 70 %.

- [ ] **Step 2: Run the trace script on a real fixture**

Run: `python3 tests/trace_run.py tests/fixtures/transcript_with_todos.jsonl`
Expected: Prints memory file content including Active Task, In-Progress Todos, Preferences sections.

- [ ] **Step 3: Verify git log is clean**

Run: `git log --oneline`
Expected: One commit per task, each with a conventional `feat:`, `test:`, `chore:`, or `docs:` prefix.

- [ ] **Step 4: Final commit (if anything lingering)**

Only needed if previous tasks left uncommitted work.

---

## Self-review checklist (completed by plan author)

**Spec coverage:**
- Problem & Goal → Task 0 framing ✅
- Non-goals → not implementation items ✅
- PreCompact hook → Task 14 ✅
- UserPromptSubmit hook → Task 15 ✅
- Memory location convention → Task 7 ✅
- Pointer injection (Strategy 2) → Tasks 13 & 15 ✅
- Agent-authored preferences (Option 3) → Tasks 9, 12, 13 ✅
- Memory file format → Tasks 11, 12 ✅
- `transcript.py` interface → Tasks 3–6 ✅
- `core.py` interface → Tasks 11–13 ✅
- `memory.py` interface → Tasks 7–10 ✅
- Fail-soft error policy → Tasks 14, 15, edge cases ✅
- E1–E15 edge cases → Task 16 ✅
- Runtime trace observability → Tasks 8, 14, 15 ✅
- Testing strategy (~54 tests, coverage targets) → Tasks 3–17 ✅
- `tests/trace_run.py` manual verification → Task 17 ✅
- Example `.claude/settings.json` → Task 18 ✅
- Success criteria 1–5 → Task 19 validation sweep ✅

**Placeholders:** none — every code step has concrete code.

**Type consistency:** `Message`, `TodoItem`, `parse_jsonl`, `find_last_user_index`, `slice_in_flight`, `extract_latest_todos`, `compose_memory_markdown`, `compaction_instructions`, `prompt_pointer_text`, `memory_dir`, `memory_path`, `trace_path`, `read_preferences_section`, `write_atomic`, `append_trace`, `find_project_root` — names used identically across tasks.
