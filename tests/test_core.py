from __future__ import annotations

from cc_compact.lib import core
from cc_compact.lib.transcript import Message, TodoItem


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
    assert "## Open Todos" in md
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
    # Truncated bullets end with a single-char ellipsis so readers see it was clipped.
    expected_bullet = "- " + "a" * (core.MAX_BULLET_LEN - 1) + "…"
    assert expected_bullet in md
    # Bullet length (without "- " prefix) must not exceed MAX_BULLET_LEN chars.
    bullet_line = next(ln for ln in md.splitlines() if ln.startswith("- a"))
    assert len(bullet_line) <= core.MAX_BULLET_LEN + 2


def test_compose_short_in_flight_line_not_truncated():
    shortline = "a" * 50
    in_flight = [_msg("assistant", shortline, 1)]
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=in_flight,
        todos=[],
        existing_preferences_section=None,
    )
    assert "- " + shortline in md
    assert "…" not in md


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
    assert "_(none yet)_" not in tail


def test_prompt_pointer_has_session_id_and_size():
    text = core.prompt_pointer_text("abc-123", 2048)
    assert "abc-123" in text
    assert "compact-memory" in text
    assert "KB" in text or "bytes" in text
    assert "## Preferences" in text


def test_compose_renders_tool_use_as_bullet():
    blocks = [{"type": "tool_use", "name": "Bash", "input": {}}]
    in_flight = [
        Message(
            role="assistant",
            content="",
            raw={"content": blocks},
            index=1,
            content_blocks=blocks,
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


def test_compose_renders_tool_use_with_signature():
    """tool_use bullets should show the key input arg (bash command, file path, etc.)."""
    blocks = [
        {"type": "tool_use", "name": "Bash", "input": {"command": "git push origin main"}},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/app.py"}},
        {"type": "tool_use", "name": "Grep", "input": {"pattern": "TODO"}},
    ]
    in_flight = [
        Message(role="assistant", content="", raw={}, index=i, content_blocks=[b])
        for i, b in enumerate(blocks)
    ]
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=in_flight,
        todos=[],
        existing_preferences_section=None,
    )
    assert "- tool: Bash (git push origin main)" in md
    assert "- tool: Edit (src/app.py)" in md
    assert "- tool: Grep (TODO)" in md


def test_compose_renders_multiline_bash_first_line_only():
    blocks = [{"type": "tool_use", "name": "Bash", "input": {"command": "echo a\necho b"}}]
    in_flight = [
        Message(role="assistant", content="", raw={}, index=1, content_blocks=blocks)
    ]
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=in_flight,
        todos=[],
        existing_preferences_section=None,
    )
    assert "- tool: Bash (echo a)" in md
    assert "echo b" not in md


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


def test_render_in_flight_caps_bullets_at_max():
    msgs = [_msg("assistant", f"turn {i}", i) for i in range(50)]
    rendered = core._render_in_flight(msgs)
    lines = rendered.split("\n")
    assert lines[0] == "- _(… 20 older in-flight turns trimmed)_"
    assert len(lines) == 31


def test_render_in_flight_no_truncation_marker_when_under_cap():
    msgs = [_msg("assistant", f"turn {i}", i) for i in range(10)]
    rendered = core._render_in_flight(msgs)
    assert "older in-flight turns trimmed" not in rendered


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
