"""Pure functions that compose Markdown / string outputs for the hooks."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from .transcript import Message, TodoItem, is_skippable_user_turn

MAX_BULLET_LEN = 120
MAX_IN_FLIGHT = 30
DEFAULT_PREFS_BODY = "_(none yet)_\n"

# Decorative-line detection for in-flight bullet selection.
# Two independent signals mark a line as decoration rather than content:
#   1. No word characters at all (pure separator row).
#   2. Contains a run of ≥ 5 separator characters (banners like
#      "★ Insight ─────────" where the word is just a label for the banner).
_WORD_CHAR_PATTERN = re.compile(r"[^\W_]", re.UNICODE)
_SEPARATOR_RUN_PATTERN = re.compile(r"[─═━\-=*#·•]{5,}")


def _is_decorative_only(line: str) -> bool:
    """True if `line` is decorative: either has no word characters, or
    contains a long run of separator characters marking it as a banner/rule.
    """
    if _WORD_CHAR_PATTERN.search(line) is None:
        return True
    if _SEPARATOR_RUN_PATTERN.search(line):
        return True
    return False

# Priority order of input keys likely to summarize a tool call.
# Works across built-in tools, MCP tools, and plugin tools that follow
# common naming conventions. Falls back to the first short string value.
_SIGNATURE_KEY_PRIORITY = (
    "command", "file_path", "path", "pattern",
    "url", "query", "description", "prompt",
)


def _tool_signature(tool_input: dict) -> str:
    """Return a short summary of a tool_use call (e.g. 'git push origin main')."""
    if not isinstance(tool_input, dict):
        return ""
    for key in _SIGNATURE_KEY_PRIORITY:
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().splitlines()[0]
    for val in tool_input.values():
        if isinstance(val, str) and val.strip() and len(val) < 200:
            return val.strip().splitlines()[0]
    return ""


def _quote_block(text: str) -> str:
    if not text:
        return "> _(no active prompt)_"
    return "\n".join("> " + line for line in text.splitlines())


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _collapse_duplicates(bullets: list[str]) -> list[str]:
    """Merge repeated bullets; tag the first occurrence with ` (×N)` when N>1.

    Order of first occurrence is preserved so the timeline still reads
    forward. Used to cut the noise when an agent loops through many
    identical-looking turns (e.g. 3000× "Reading file contents …").
    """
    counts: dict[str, int] = {}
    order: list[str] = []
    for b in bullets:
        if b in counts:
            counts[b] += 1
        else:
            counts[b] = 1
            order.append(b)
    return [b if counts[b] == 1 else f"{b} (×{counts[b]})" for b in order]


def _render_in_flight(in_flight: list[Message]) -> str:
    bullets: list[str] = []
    for msg in in_flight:
        # User turns: the anchor prompt is already quoted in `## Active Task`
        # above, and CLI-injected envelopes (tool_result, local-command) are
        # noise. Either way, skip — keep bullets focused on assistant activity.
        if msg.role == "user":
            continue
        non_empty = [ln for ln in (msg.content or "").splitlines() if ln.strip()]
        first_line = next(
            (ln for ln in non_empty if not _is_decorative_only(ln)),
            non_empty[0] if non_empty else "",
        )
        if first_line:
            bullets.append(f"- {_truncate(first_line, MAX_BULLET_LEN)}")
            continue
        # No text content — try to render a tool_use bullet
        for block in msg.content_blocks:
            if block.get("type") == "tool_use":
                name = block.get("name", "?")
                sig = _tool_signature(block.get("input", {}))
                label = f"tool: {name} ({sig})" if sig else f"tool: {name}"
                bullets.append(f"- {_truncate(label, MAX_BULLET_LEN)}")
                break
    raw_turn_count = len(bullets)
    bullets = _collapse_duplicates(bullets)
    if len(bullets) > MAX_IN_FLIGHT:
        trimmed_count = len(bullets) - MAX_IN_FLIGHT
        if raw_turn_count > len(bullets):
            note = (
                f"- _(… {trimmed_count} older in-flight bullets trimmed; "
                f"collapsed from {raw_turn_count} turns)_"
            )
        else:
            note = f"- _(… {trimmed_count} older in-flight turns trimmed)_"
        bullets = [note, *bullets[-MAX_IN_FLIGHT:]]
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
        f"## Open Todos\n"
        f"{_render_todos(todos)}\n"
        f"\n"
        f"## Preferences\n"
        f"{prefs_body}\n"
    )


def prompt_pointer_text(mem_filename: str, memory_size_bytes: int) -> str:
    """Pointer injected via UserPromptSubmit `additionalContext`."""
    size_kb = max(1, round(memory_size_bytes / 1024))
    return (
        f"Memory: `.claude/compact-memory/{mem_filename}` (~{size_kb}KB). "
        f"Read for prior task/todo/preference context. "
        f"Append preferences to `## Preferences` (Edit tool)."
    )
