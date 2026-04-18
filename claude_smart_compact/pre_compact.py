#!/usr/bin/env python3
"""PreCompact hook entry — persists memory to .claude/compact-memory/<sid>.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `lib` importable when invoked directly by the CLI or deployed to .claude/hooks/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import core, memory, transcript  # noqa: E402


def _safe_trace(project_root: Path, session_id: str | None, event: dict) -> None:
    if not session_id:
        return
    try:
        memory.append_trace(memory.trace_path(project_root, session_id), event)
    except Exception:
        pass


def main() -> None:
    payload = json.load(sys.stdin)
    session_id = payload["session_id"]
    transcript_path = payload.get("transcript_path", "")
    trigger = payload.get("trigger", "unknown")

    root = memory.find_project_root(Path.cwd())
    messages = transcript.parse_jsonl(transcript_path)
    last_user_idx = transcript.find_last_user_index(messages)

    if last_user_idx is None:
        _safe_trace(root, session_id, {
            "hook": "PreCompact",
            "trigger": trigger,
            "messages_count": len(messages),
            "last_user_index": None,
            "skipped_reason": "no user message",
        })
        json.dump({}, sys.stdout)
        return

    in_flight = transcript.slice_in_flight(messages, last_user_idx)
    todos = [
        t for t in transcript.extract_latest_todos(messages)
        if t.status in ("in_progress", "pending")
    ]
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
    _safe_trace(root, session_id, {
        "hook": "PreCompact",
        "trigger": trigger,
        "messages_count": len(messages),
        "last_user_index": last_user_idx,
        "todos_count": len(todos),
        "memory_bytes": len(md.encode("utf-8")),
        "preserved_preferences": existing_prefs is not None,
    })

    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "additionalContext": core.compaction_instructions(),
        }
    }, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            root = memory.find_project_root(Path.cwd())
            session_id = None
            try:
                raw = json.loads(sys.stdin.read() or "{}")
                session_id = raw.get("session_id")
            except Exception:
                pass
            _safe_trace(root, session_id, {
                "hook": "PreCompact",
                "error": str(e),
                "error_type": type(e).__name__,
            })
        except Exception:
            pass
        json.dump({}, sys.stdout)
        sys.exit(0)
