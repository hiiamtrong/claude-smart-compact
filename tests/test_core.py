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


def test_prompt_pointer_has_filename_and_size():
    text = core.prompt_pointer_text("2026-04-22T10-30-45Z_abc-123.md", 2048)
    assert "2026-04-22T10-30-45Z_abc-123.md" in text
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


def test_render_in_flight_filters_all_user_turns():
    """In-flight bullets focus on assistant activity: user turns are skipped
    (the anchor prompt is in Active Task, envelopes are noise)."""
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
    # Anchor user prompt (drop — already in Active Task)
    m5 = Message(role="user", content="please continue", raw={"message": {"role": "user", "content": "please continue"}}, index=5)
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="task",
        in_flight=[m1, m2, m3, m4, m5],
        todos=[],
        existing_preferences_section=None,
    )
    assert "- looking at the code" in md
    # All user-role content drops out of in-flight.
    # (Active Task blockquote shows it instead — tested elsewhere.)
    in_flight_section = md.split("**In-flight turns")[1].split("## Open Todos")[0]
    assert "please continue" not in in_flight_section
    assert "<command-name>" not in in_flight_section
    assert "<local-command-stdout>" not in in_flight_section
    assert "tool result output" not in in_flight_section


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


def test_render_in_flight_collapses_duplicate_bullets():
    """Identical bullets (text or tool_use) collapse into one line tagged ×N."""
    msgs = [_msg("assistant", "Reading file contents", i) for i in range(5)]
    rendered = core._render_in_flight(msgs)
    # Single bullet with count, not five separate lines.
    assert rendered.count("Reading file contents") == 1
    assert "(×5)" in rendered


def test_render_in_flight_preserves_first_occurrence_order_after_dedup():
    msgs = [
        _msg("assistant", "A", 0),
        _msg("assistant", "B", 1),
        _msg("assistant", "A", 2),
        _msg("assistant", "C", 3),
        _msg("assistant", "B", 4),
    ]
    rendered = core._render_in_flight(msgs)
    a_pos = rendered.index("- A")
    b_pos = rendered.index("- B")
    c_pos = rendered.index("- C")
    assert a_pos < b_pos < c_pos
    assert "- A (×2)" in rendered
    assert "- B (×2)" in rendered
    assert "- C" in rendered and "C (×" not in rendered


def test_render_in_flight_trim_note_mentions_raw_turn_count_when_deduped():
    """When dedup + trim both fire, the note should surface the raw turn count."""
    # 40 unique bullets + 20 copies of one of them → 60 raw turns, 40 unique.
    msgs = [_msg("assistant", f"turn {i}", i) for i in range(40)]
    msgs += [_msg("assistant", "turn 0", 100 + i) for i in range(20)]
    rendered = core._render_in_flight(msgs)
    lines = rendered.split("\n")
    # 40 unique > MAX_IN_FLIGHT (30) → trimmed_count = 10, and dedup happened.
    assert "collapsed from 60 turns" in lines[0]
    assert "10 older in-flight bullets trimmed" in lines[0]


def test_render_in_flight_drops_slash_command_user_turn():
    """Slash commands WITH args become the Active Task; in-flight bullets
    should not duplicate them (all user-role turns are skipped there)."""
    m = Message(
        role="user",
        content="<command-name>/ultrareview</command-name>\n<command-args>fix nulls</command-args>",
        raw={"message": {"role": "user", "content": "<command-name>/ultrareview</command-name>\n<command-args>fix nulls</command-args>"}},
        index=0,
    )
    md = core.compose_memory_markdown(
        session_id="sid",
        active_task_user_msg="fix nulls",
        in_flight=[m],
        todos=[],
        existing_preferences_section=None,
    )
    in_flight_section = md.split("**In-flight turns")[1].split("## Open Todos")[0]
    assert "ultrareview" not in in_flight_section
    assert "<command-name>" not in in_flight_section
    # Active Task still carries the real intent.
    assert "> fix nulls" in md
