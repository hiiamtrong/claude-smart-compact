"""Pure functions that compose Markdown / string outputs for the hooks."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .transcript import Message, TodoItem, is_skippable_user_turn

MAX_BULLET_LEN = 120
MAX_IN_FLIGHT = 30
DEFAULT_PREFS_BODY = "_(none yet)_\n"

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
        for block in msg.content_blocks:
            if block.get("type") == "tool_use":
                name = block.get("name", "?")
                sig = _tool_signature(block.get("input", {}))
                label = f"tool: {name} ({sig})" if sig else f"tool: {name}"
                bullets.append(f"- {_truncate(label, MAX_BULLET_LEN)}")
                break
    if len(bullets) > MAX_IN_FLIGHT:
        trimmed_count = len(bullets) - MAX_IN_FLIGHT
        bullets = [
            f"- _(… {trimmed_count} older in-flight turns trimmed)_",
            *bullets[-MAX_IN_FLIGHT:],
        ]
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


def prompt_pointer_text(session_id: str, memory_size_bytes: int) -> str:
    """Pointer injected via UserPromptSubmit `additionalContext`."""
    size_kb = max(1, round(memory_size_bytes / 1024))
    return (
        f"Memory: `.claude/compact-memory/{session_id}.md` (~{size_kb}KB). "
        f"Read for prior task/todo/preference context. "
        f"Append preferences to `## Preferences` (Edit tool)."
    )
