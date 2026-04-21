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

# IDE/system envelope wrappers Claude Code injects into user turns. When
# anchored at the start or end of a user's prompt they are telemetry rather
# than intent, so strip them before the text is rendered as the Active Task.
# Wrappers quoted mid-sentence ("what does <ide_opened_file> mean?") are
# intentionally left alone.
_ENVELOPE_WRAPPER_TAGS = (
    "ide_opened_file",
    "ide_selection",
    "system-reminder",
    "user-prompt-submit-hook",
)
_WRAPPER_BODY = (
    r"<(?:" + "|".join(_ENVELOPE_WRAPPER_TAGS) + r")\b[^>]*>.*?</(?:"
    + "|".join(_ENVELOPE_WRAPPER_TAGS) + r")>"
)
_LEADING_WRAPPERS_PATTERN = re.compile(
    r"\A(?:\s*" + _WRAPPER_BODY + r")+", re.DOTALL,
)
_TRAILING_WRAPPERS_PATTERN = re.compile(
    r"(?:" + _WRAPPER_BODY + r"\s*)+\Z", re.DOTALL,
)


def _strip_envelope_wrappers(text: str) -> str:
    """Strip envelope wrapper blocks anchored at start/end of `text`.

    If stripping leaves an empty string, returns the original text — we prefer
    a slightly noisy Active Task over silently erasing the user's prompt.
    """
    if not text:
        return text
    stripped = _LEADING_WRAPPERS_PATTERN.sub("", text)
    stripped = _TRAILING_WRAPPERS_PATTERN.sub("", stripped)
    stripped = stripped.strip()
    return stripped if stripped else text


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

    - For plain user text: returns msg.content with envelope wrappers stripped.
    - For a slash-command with args: returns the args body (wrappers stripped).
    - For a slash-command with empty args: returns '' (caller handles placeholder).
    """
    args = _slash_command_args(msg.content)
    body = msg.content if args is None else args
    return _strip_envelope_wrappers(body)


@dataclass
class Message:
    role: Role
    content: str
    raw: dict = field(default_factory=dict)
    index: int = 0
    content_blocks: list[dict] = field(default_factory=list)


@dataclass
class TodoItem:
    content: str
    status: Literal["pending", "in_progress", "completed"]


def _flatten_content(raw_content) -> str:
    """Flatten Claude Code content (string or list of blocks) into plain text.

    Image blocks are rendered as `[Image]` placeholders so callers know a visual
    was attached without embedding base64 data into memory files.
    """
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, list):
        parts: list[str] = []
        for block in raw_content:
            if isinstance(block, dict):
                if block.get("type") == "image":
                    parts.append("[Image]")
                    continue
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
            content_blocks = (
                [b for b in raw_content if isinstance(b, dict)]
                if isinstance(raw_content, list)
                else []
            )
            messages.append(
                Message(
                    role=role,
                    content=content,
                    raw=raw,
                    index=idx,
                    content_blocks=content_blocks,
                )
            )
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
    (tool results, command stdout, caveats, compact summary) rather than a
    real user prompt.
    """
    raw = msg.raw
    # Signal 1: top-level toolUseResult key
    if isinstance(raw, dict) and "toolUseResult" in raw:
        return True
    # Signal 2: content is a list of tool_result blocks only
    blocks = msg.content_blocks
    if blocks and all(b.get("type") == "tool_result" for b in blocks):
        return True
    # Signal 3: plain-string content wrapped in local-command markers.
    text = msg.content or ""
    stripped = text.lstrip()
    if any(stripped.startswith(marker) for marker in _LOCAL_COMMAND_MARKERS):
        return True
    # Signal 4: Claude Code's post-compact continuation record. After /compact,
    # the CLI injects a "user" turn containing the prior-conversation summary
    # with isCompactSummary: true. It is not a user prompt.
    if isinstance(raw, dict) and raw.get("isCompactSummary") is True:
        return True
    return False


def is_skippable_user_turn(msg: "Message") -> bool:
    """True if this user turn is NOT a real user prompt.

    Combines:
      - CLI-injected envelopes (tool results, local-command stdout/stderr/caveat)
      - Meta slash commands (those with empty <command-args>)

    A slash command WITH non-empty args is NOT skippable — the args are the task intent.
    """
    if _is_cli_injected_message(msg):
        return True
    args = _slash_command_args(msg.content)
    if args == "":  # has <command-name>...<command-args></command-args> empty
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
        if is_skippable_user_turn(msg):
            continue
        return msg.index
    return None


def slice_in_flight(messages: list[Message], from_index: Optional[int]) -> list[Message]:
    """Return messages[from_index:]. If from_index is None, return all."""
    if from_index is None:
        return list(messages)
    return [m for m in messages if m.index >= from_index]


def _message_content_blocks(msg: Message) -> list[dict]:
    """Return cached list content blocks from a Message."""
    return msg.content_blocks


def _has_todowrite_block(msg: Message) -> bool:
    """True if msg has any TodoWrite tool_use block (even with empty todos list)."""
    for block in _message_content_blocks(msg):
        if block.get("type") == "tool_use" and block.get("name") == "TodoWrite":
            return True
    return False


def _parse_todowrite_from_message(msg: Message) -> list[TodoItem]:
    """Return parsed TodoItems from any TodoWrite tool_use blocks in msg.

    Returns [] if msg has no TodoWrite block or its todos list is empty.
    """
    parsed: list[TodoItem] = []
    for block in _message_content_blocks(msg):
        if block.get("type") != "tool_use" or block.get("name") != "TodoWrite":
            continue
        input_val = block.get("input", {})
        if not isinstance(input_val, dict):
            continue
        for t in input_val.get("todos", []):
            if not isinstance(t, dict):
                continue
            content = t.get("content") or ""
            status = t.get("status") or "pending"
            if status not in ("pending", "in_progress", "completed"):
                status = "pending"
            parsed.append(TodoItem(content=content, status=status))
    return parsed


def extract_latest_todos(messages: list[Message]) -> list[TodoItem]:
    """Find the most recent TodoWrite tool_use call and parse its todo list."""
    latest: list[TodoItem] = []
    for msg in messages:
        if _has_todowrite_block(msg):
            latest = _parse_todowrite_from_message(msg)  # later wins (empty clears)
    return latest


@dataclass
class TranscriptScan:
    last_user_idx: Optional[int]
    in_flight: list[Message]
    todos: list[TodoItem]


def scan_transcript(messages: list[Message]) -> TranscriptScan:
    """Single forward pass computing last_user_idx, in_flight, and todos.

    Replaces three separate O(n) passes (find_last_user_index, slice_in_flight,
    extract_latest_todos) with one.
    """
    last_user_idx: Optional[int] = None
    in_flight_accum: list[Message] = []
    todos: list[TodoItem] = []

    for msg in messages:
        if msg.role == "user" and not is_skippable_user_turn(msg):
            last_user_idx = msg.index
            in_flight_accum = [msg]
        elif last_user_idx is not None:
            in_flight_accum.append(msg)

        if _has_todowrite_block(msg):
            todos = _parse_todowrite_from_message(msg)  # later wins (empty clears)

    in_flight = in_flight_accum if last_user_idx is not None else list(messages)
    return TranscriptScan(last_user_idx=last_user_idx, in_flight=in_flight, todos=todos)
