from __future__ import annotations

from claude_smart_compact.lib import core
from claude_smart_compact.lib.transcript import Message, TodoItem


def _msg(role, content, idx):
    return Message(role=role, content=content, raw={}, index=idx)


def test_compose_contains_all_required_headings():
    md = core.compose_memory_markdown(
        session_id="sid-1",
        active_task_user_msg="do the thing",
        in_flight=[_msg("assistant", "on it", 1)],
        todos=[],
        existing_preferences_section=None,
    )
    assert "# Session Memory" in md
    assert "session_id: sid-1" in md
    assert "## Active Task" in md
    assert "## In-Progress Todos" in md
    assert "## Preferences" in md


def test_compose_quotes_last_user_message_verbatim():
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="please refactor X\nuse pattern Y",
        in_flight=[],
        todos=[],
        existing_preferences_section=None,
    )
    assert "> please refactor X" in md
    assert "> use pattern Y" in md


def test_compose_lists_in_flight_turns_truncated():
    longline = "a" * 200
    in_flight = [_msg("assistant", longline, 1), _msg("assistant", "", 2)]
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=in_flight,
        todos=[],
        existing_preferences_section=None,
    )
    # Each non-empty turn renders as a bullet with max 120 char preview.
    assert "- " + "a" * 120 in md


def test_compose_renders_todos_bullets():
    todos = [
        TodoItem(content="do migration", status="in_progress"),
        TodoItem(content="add tests", status="pending"),
    ]
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=[],
        todos=todos,
        existing_preferences_section=None,
    )
    assert "- [ ] do migration (status: in_progress)" in md
    assert "- [ ] add tests (status: pending)" in md


def test_compose_renders_placeholder_when_no_todos():
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=[],
        todos=[],
        existing_preferences_section=None,
    )
    assert "_(none)_" in md


def test_compose_uses_placeholder_for_empty_active_task():
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="",
        in_flight=[],
        todos=[],
        existing_preferences_section=None,
    )
    assert "_(no active prompt)_" in md


def test_compose_preserves_existing_preferences():
    existing = "- always use pnpm\n- never mock DB"
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=[],
        todos=[],
        existing_preferences_section=existing,
    )
    prefs_start = md.index("## Preferences")
    tail = md[prefs_start:]
    assert "always use pnpm" in tail
    assert "never mock DB" in tail
    # Placeholder should NOT appear when existing prefs provided.
    assert "never rewrite existing entries" not in tail


def test_compaction_instructions_mentions_key_concerns():
    text = core.compaction_instructions()
    for needle in ["last user message", "in_progress", "preferences", "memory file"]:
        assert needle.lower() in text.lower()


def test_prompt_pointer_has_session_id_and_size():
    text = core.prompt_pointer_text("abc-123", 2048)
    assert "abc-123" in text
    assert "compact-memory" in text
    assert "KB" in text or "bytes" in text
    assert "## Preferences" in text


def test_compose_renders_tool_use_as_bullet():
    in_flight = [
        Message(
            role="assistant",
            content="",
            raw={"content": [{"type": "tool_use", "name": "Bash", "input": {}}]},
            index=1,
        )
    ]
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=in_flight,
        todos=[],
        existing_preferences_section=None,
    )
    assert "- tool: Bash" in md


def test_render_in_flight_filters_cli_injected_user_turns():
    """In-flight rendering should drop CLI-injected bullets (local-command, tool-result, /compact)."""
    # Real assistant turn (keep)
    m1 = Message(role="assistant", content="looking at the code", raw={}, index=1)
    # /compact meta (drop)
    m2 = Message(
        role="user",
        content="<command-name>/compact</command-name>\n<command-message>compact</command-message>\n<command-args></command-args>",
        raw={"message": {"role": "user", "content": "<command-name>/compact</command-name>\n<command-args></command-args>"}},
        index=2,
    )
    # local-command-stdout (drop)
    m3 = Message(
        role="user",
        content="<local-command-stdout>done</local-command-stdout>",
        raw={"message": {"role": "user", "content": "<local-command-stdout>done</local-command-stdout>"}},
        index=3,
    )
    # tool-result envelope (drop)
    m4 = Message(
        role="user",
        content="tool result output",
        raw={
            "toolUseResult": {"exitCode": 0},
            "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
        },
        index=4,
    )
    # Normal user prompt (keep)
    m5 = Message(role="user", content="please continue", raw={"message": {"role": "user", "content": "please continue"}}, index=5)
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=[m1, m2, m3, m4, m5],
        todos=[],
        existing_preferences_section=None,
    )
    assert "- looking at the code" in md
    assert "- please continue" in md
    assert "<command-name>" not in md  # filtered
    assert "<local-command-stdout>" not in md  # filtered
    assert "tool result output" not in md  # filtered


def test_render_in_flight_keeps_slash_command_with_args():
    """Slash commands WITH args carry task intent — keep them in bullets."""
    m = Message(
        role="user",
        content="<command-name>/ultrareview</command-name>\n<command-args>fix nulls</command-args>",
        raw={"message": {"role": "user", "content": "<command-name>/ultrareview</command-name>\n<command-args>fix nulls</command-args>"}},
        index=0,
    )
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=[m],
        todos=[],
        existing_preferences_section=None,
    )
    # Main assertion: it's NOT filtered out.
    assert "ultrareview" in md or "<command-name>" in md  # content still rendered
