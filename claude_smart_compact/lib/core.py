"""Pure functions that compose Markdown / string outputs for the hooks."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .transcript import Message, TodoItem, is_skippable_user_turn

MAX_BULLET_LEN = 120
DEFAULT_PREFS_BODY = "_(none yet)_\n"


def _quote_block(text: str) -> str:
    if not text:
        return "> _(no active prompt)_"
    return "\n".join("> " + line for line in text.splitlines())


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _render_in_flight(in_flight: list[Message]) -> str:
    bullets: list[str] = []
    for msg in in_flight:
        # Skip CLI-injected user messages (they're noise in the timeline).
        if msg.role == "user" and is_skippable_user_turn(msg):
            continue
        first_line = next(
            (ln for ln in (msg.content or "").splitlines() if ln.strip()), ""
        )
        if first_line:
            bullets.append(f"- {_truncate(first_line, MAX_BULLET_LEN)}")
            continue
        # No text content — try to render a tool_use bullet
        raw = msg.raw
        content = None
        if isinstance(raw.get("message"), dict):
            content = raw["message"].get("content")
        if content is None:
            content = raw.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    bullets.append(f"- tool: {block.get('name', '?')}")
                    break
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


def prompt_pointer_text(session_id: str, memory_size_bytes: int) -> str:
    """Pointer injected via UserPromptSubmit `additionalContext`."""
    size_kb = max(1, round(memory_size_bytes / 1024))
    return (
        f"Memory: `.claude/compact-memory/{session_id}.md` (~{size_kb}KB). "
        f"Read for prior task/todo/preference context. "
        f"Append preferences to `## Preferences` (Edit tool)."
    )
