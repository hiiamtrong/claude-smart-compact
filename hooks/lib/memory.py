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
