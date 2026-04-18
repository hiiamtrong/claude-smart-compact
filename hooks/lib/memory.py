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
