"""File-system helpers for the smart-compact memory store."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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


def _memory_filename(session_id: str, ts: str) -> str:
    """Return a sortable filename: <ts>_<session_id>.md (ts in compact ISO form)."""
    return f"{ts}_{session_id}.md"


def memory_path(project_root: Path, session_id: str) -> Path:
    """Return the path for a new memory file with a UTC timestamp prefix."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return memory_dir(project_root) / _memory_filename(session_id, ts)


def find_memory_path(project_root: Path, session_id: str) -> Optional[Path]:
    """Find an existing memory file for session_id (any timestamp prefix or legacy name)."""
    d = memory_dir(project_root)
    # New format: <datetime>_<session_id>.md (sorted alphabetically = chronologically)
    matches = sorted(d.glob(f"*_{session_id}.md"))
    if matches:
        return matches[-1]
    # Legacy format: <session_id>.md
    legacy = d / f"{session_id}.md"
    if legacy.exists():
        return legacy
    return None


def trace_path(project_root: Path, session_id: str) -> Path:
    return memory_dir(project_root) / f"{session_id}.trace.jsonl"


def write_atomic(path: Path, content: str) -> None:
    """Write `content` to `path` atomically (write to .tmp then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def append_trace(path: Path, event: dict) -> None:
    """Append one JSONL record to `path` with an ISO-8601 UTC timestamp."""
    if os.getenv("CLAUDE_SMART_COMPACT_TRACE", "1") == "0":
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


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
