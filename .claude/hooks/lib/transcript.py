"""Pure functions for parsing a Claude Code transcript (.jsonl)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

Role = Literal["user", "assistant", "system", "tool"]

VALID_ROLES = {"user", "assistant", "system", "tool"}

# Detect slash-command messages by the envelope Claude Code wraps them in.
_SLASH_NAME_PATTERN = re.compile(
    r"<command-name>/[a-zA-Z0-9_\-]+</command-name>",
    re.DOTALL,
)
_SLASH_ARGS_PATTERN = re.compile(
    r"<command-args>(.*?)</command-args>",
    re.DOTALL,
)


def _slash_command_args(content: str) -> Optional[str]:
    """If `content` is a slash-command user turn, return the args body.

    Returns:
      - None if `content` is NOT a slash-command message (plain user text).
      - The <command-args> body (possibly empty string) if it is.
    """
    if not content or not _SLASH_NAME_PATTERN.search(content):
        return None
    m = _SLASH_ARGS_PATTERN.search(content)
    return m.group(1).strip() if m else ""


def active_task_text(msg: "Message") -> str:
    """Return the human-readable 'active task' body for a user Message.

    - For plain user text: returns msg.content unchanged.
    - For a slash-command with args: returns the args body only.
    - For a slash-command with empty args: returns '' (caller handles placeholder).
    """
    args = _slash_command_args(msg.content)
    if args is None:
        return msg.content
    return args


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
    """Stream-read JSONL; skip corrupt lines and metadata; return ordered list."""
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
            if not isinstance(raw, dict):
                continue

            # Real CLI format: role is nested in message.role
            # Synthetic test format: role is at top level
            msg_obj = raw.get("message") if isinstance(raw.get("message"), dict) else None
            role = None
            if msg_obj is not None:
                role = msg_obj.get("role")
            if role is None:
                role = raw.get("role")

            # Skip metadata lines that aren't real messages
            if role not in VALID_ROLES:
                continue

            # Content: prefer nested, fall back to top-level
            if msg_obj is not None and "content" in msg_obj:
                raw_content = msg_obj.get("content")
            else:
                raw_content = raw.get("content", "")

            content = _flatten_content(raw_content)
            messages.append(Message(role=role, content=content, raw=raw, index=idx))
            idx += 1
    return messages


# Markers that Claude Code uses to inject non-prompt text as user messages.
_LOCAL_COMMAND_MARKERS = (
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<local-command-caveat>",
)


def _is_cli_injected_message(msg: "Message") -> bool:
    """True if this 'user' message is actually CLI-injected metadata
    (tool results, command stdout, caveats) rather than a real user prompt.
    """
    raw = msg.raw
    # Signal 1: top-level toolUseResult key
    if isinstance(raw, dict) and "toolUseResult" in raw:
        return True
    # Signal 2: content is a list of tool_result blocks only
    msg_obj = raw.get("message") if isinstance(raw, dict) else None
    content = None
    if isinstance(msg_obj, dict):
        content = msg_obj.get("content")
    if content is None and isinstance(raw, dict):
        content = raw.get("content")
    if isinstance(content, list) and len(content) > 0:
        if all(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in content
        ):
            return True
    # Signal 3: plain-string content wrapped in local-command markers.
    text = msg.content or ""
    stripped = text.lstrip()
    if any(stripped.startswith(marker) for marker in _LOCAL_COMMAND_MARKERS):
        return True
    return False


def find_last_user_index(messages: list[Message]) -> Optional[int]:
    """Return index of last user message representing actual intent.

    Skips:
      - slash-command meta turns (empty <command-args>)
      - tool-result envelopes injected as user messages
    """
    for msg in reversed(messages):
        if msg.role != "user":
            continue
        if _is_cli_injected_message(msg):
            continue
        args = _slash_command_args(msg.content)
        if args is None:
            return msg.index  # plain user text
        if args:
            return msg.index  # slash command with real args
        continue  # slash command with empty args (meta)
    return None


def slice_in_flight(messages: list[Message], from_index: Optional[int]) -> list[Message]:
    """Return messages[from_index:]. If from_index is None, return all."""
    if from_index is None:
        return list(messages)
    return [m for m in messages if m.index >= from_index]


def _message_content_blocks(msg: Message) -> list[dict]:
    """Return list content blocks from a Message's raw payload (handles both formats)."""
    raw = msg.raw
    # Real CLI format: content is nested in message.content
    if isinstance(raw.get("message"), dict):
        content = raw["message"].get("content")
        if isinstance(content, list):
            return [b for b in content if isinstance(b, dict)]
    # Synthetic test format: content is at top level
    content = raw.get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def extract_latest_todos(messages: list[Message]) -> list[TodoItem]:
    """Find the most recent TodoWrite tool_use call and parse its todo list."""
    latest: list[TodoItem] = []
    for msg in messages:
        for block in _message_content_blocks(msg):
            if block.get("type") != "tool_use":
                continue
            if block.get("name") != "TodoWrite":
                continue
            input_val = block.get("input", {})
            if not isinstance(input_val, dict):
                continue
            todos_raw = input_val.get("todos", [])
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
