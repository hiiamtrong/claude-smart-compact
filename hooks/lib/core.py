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
