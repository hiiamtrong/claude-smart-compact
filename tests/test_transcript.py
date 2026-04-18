from __future__ import annotations

from claude_smart_compact.lib import transcript


def test_parse_jsonl_empty_file(copy_fixture):
    path = copy_fixture("transcript_empty.jsonl")
    assert transcript.parse_jsonl(str(path)) == []


def test_parse_jsonl_returns_messages_in_order(copy_fixture):
    path = copy_fixture("transcript_single_turn.jsonl")
    messages = transcript.parse_jsonl(str(path))
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "hello"
    assert messages[0].index == 0
    assert messages[1].role == "assistant"
    assert messages[1].content == "hi there"
    assert messages[1].index == 1


def test_parse_jsonl_missing_file_returns_empty(tmp_path):
    assert transcript.parse_jsonl(str(tmp_path / "nope.jsonl")) == []


def _msg(role, content="x", index=0):
    return transcript.Message(role=role, content=content, raw={}, index=index)


def test_find_last_user_index_none_when_no_user():
    messages = [_msg("assistant", index=0), _msg("tool", index=1)]
    assert transcript.find_last_user_index(messages) is None


def test_find_last_user_index_returns_latest_user():
    messages = [
        _msg("user", index=0),
        _msg("assistant", index=1),
        _msg("user", index=2),
        _msg("assistant", index=3),
    ]
    assert transcript.find_last_user_index(messages) == 2


def test_slice_in_flight_returns_tail():
    messages = [_msg("user", index=i) for i in range(5)]
    tail = transcript.slice_in_flight(messages, 3)
    assert [m.index for m in tail] == [3, 4]


def test_slice_in_flight_none_returns_all():
    messages = [_msg("user", index=i) for i in range(3)]
    assert transcript.slice_in_flight(messages, None) == messages


def test_extract_latest_todos_empty_when_none(copy_fixture):
    path = copy_fixture("transcript_single_turn.jsonl")
    messages = transcript.parse_jsonl(str(path))
    assert transcript.extract_latest_todos(messages) == []


def test_extract_latest_todos_returns_most_recent_snapshot(copy_fixture):
    path = copy_fixture("transcript_with_todos.jsonl")
    messages = transcript.parse_jsonl(str(path))
    todos = transcript.extract_latest_todos(messages)
    # The second TodoWrite wins — not the first.
    assert len(todos) == 3
    assert todos[0].content == "inspect current auth"
    assert todos[0].status == "completed"
    assert todos[2].content == "add tests"
    assert todos[2].status == "in_progress"


def test_parse_jsonl_skips_corrupt_lines(copy_fixture):
    path = copy_fixture("transcript_corrupt_lines.jsonl")
    messages = transcript.parse_jsonl(str(path))
    assert [m.content for m in messages] == ["first", "second", "third"]


def test_find_last_user_on_multi_user_transcript(copy_fixture):
    path = copy_fixture("transcript_multi_user_turns.jsonl")
    messages = transcript.parse_jsonl(str(path))
    idx = transcript.find_last_user_index(messages)
    assert idx is not None
    assert messages[idx].content == "final: wrap up"


def test_find_last_user_is_none_when_transcript_has_none(copy_fixture):
    path = copy_fixture("transcript_no_user.jsonl")
    messages = transcript.parse_jsonl(str(path))
    assert transcript.find_last_user_index(messages) is None


def test_parse_jsonl_real_cli_format_skips_metadata(copy_fixture):
    path = copy_fixture("transcript_real_cli_format.jsonl")
    messages = transcript.parse_jsonl(str(path))
    # 2 user + 3 assistant = 5 messages (metadata types skipped)
    assert len(messages) == 5
    roles = [m.role for m in messages]
    assert roles == ["user", "assistant", "assistant", "user", "assistant"]


def test_parse_jsonl_real_cli_format_reads_nested_role_and_content(copy_fixture):
    path = copy_fixture("transcript_real_cli_format.jsonl")
    messages = transcript.parse_jsonl(str(path))
    assert messages[0].content == "refactor the auth module"
    assert messages[3].content == "continue please"


def test_find_last_user_index_on_real_cli_format(copy_fixture):
    path = copy_fixture("transcript_real_cli_format.jsonl")
    messages = transcript.parse_jsonl(str(path))
    idx = transcript.find_last_user_index(messages)
    assert idx is not None
    assert messages[idx].content == "continue please"


def test_extract_latest_todos_on_real_cli_format(copy_fixture):
    path = copy_fixture("transcript_real_cli_format.jsonl")
    messages = transcript.parse_jsonl(str(path))
    todos = transcript.extract_latest_todos(messages)
    assert len(todos) == 1
    assert todos[0].content == "understand auth"
    assert todos[0].status == "in_progress"
