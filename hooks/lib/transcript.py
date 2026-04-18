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
