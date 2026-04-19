#!/usr/bin/env python3
"""PreCompact hook entry — persists memory to .claude/compact-memory/<sid>.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `lib` importable when invoked directly by the CLI or deployed to .claude/hooks/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import core, hook_runner, memory, transcript  # noqa: E402


def main(payload: dict) -> None:
    session_id = payload["session_id"]
    transcript_path = payload.get("transcript_path", "")
    trigger = payload.get("trigger", "unknown")

    root = memory.find_project_root(Path.cwd())
    messages = transcript.parse_jsonl(transcript_path)
    scan = transcript.scan_transcript(messages)
    last_user_idx = scan.last_user_idx

    if last_user_idx is None:
        hook_runner.safe_trace(root, session_id, {
            "hook": "PreCompact",
            "trigger": trigger,
            "messages_count": len(messages),
            "last_user_index": None,
            "skipped_reason": "no user message",
        })
        json.dump({}, sys.stdout)
        return

    in_flight = scan.in_flight
    todos = [t for t in scan.todos if t.status in ("in_progress", "pending")]
    active_task_msg = transcript.active_task_text(messages[last_user_idx]) if messages else ""

    mem_file = memory.memory_path(root, session_id)
    existing_prefs = memory.read_preferences_section(mem_file)

    md = core.compose_memory_markdown(
        session_id=session_id,
        active_task_user_msg=active_task_msg,
        in_flight=in_flight,
        todos=todos,
        existing_preferences_section=existing_prefs,
    )
    memory.write_atomic(mem_file, md)
    hook_runner.safe_trace(root, session_id, {
        "hook": "PreCompact",
        "trigger": trigger,
        "messages_count": len(messages),
        "last_user_index": last_user_idx,
        "todos_count": len(todos),
        "memory_bytes": len(md.encode("utf-8")),
        "preserved_preferences": existing_prefs is not None,
    })

    # PreCompact stdout must be empty: Claude Code's schema does not accept
    # `hookSpecificOutput` for PreCompact. Compaction guidance rides the
    # UserPromptSubmit pointer on the next turn instead.
    json.dump({}, sys.stdout)


if __name__ == "__main__":
    hook_runner.run_hook(main, "PreCompact")
