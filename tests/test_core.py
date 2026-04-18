from __future__ import annotations

from hooks.lib import core
from hooks.lib.transcript import Message, TodoItem


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
