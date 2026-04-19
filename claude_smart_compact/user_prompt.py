#!/usr/bin/env python3
"""UserPromptSubmit hook entry — injects a pointer to the memory file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `lib` importable when invoked directly by the CLI or deployed to .claude/hooks/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import core, memory  # noqa: E402


def _safe_trace(project_root: Path, session_id: str | None, event: dict) -> None:
    if not session_id:
        return
    try:
        memory.append_trace(memory.trace_path(project_root, session_id), event)
    except Exception:
        pass


def main(payload: dict) -> None:
    session_id = payload["session_id"]

    root = memory.find_project_root(Path.cwd())
    mem_file = memory.memory_path(root, session_id)

    if not mem_file.exists():
        json.dump({}, sys.stdout)
        return

    size = mem_file.stat().st_size
    _safe_trace(root, session_id, {
        "hook": "UserPromptSubmit",
        "memory_bytes": size,
        "pointer_injected": True,
    })
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": core.prompt_pointer_text(session_id, size),
        }
    }, sys.stdout)


if __name__ == "__main__":
    payload: dict = {}
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # stdin itself is malformed — no session_id to correlate with.
        json.dump({}, sys.stdout)
        sys.exit(0)
    try:
        main(payload)
    except Exception as e:
        try:
            root = memory.find_project_root(Path.cwd())
            session_id = payload.get("session_id") if isinstance(payload, dict) else None
            _safe_trace(root, session_id, {
                "hook": "UserPromptSubmit",
                "error": str(e),
                "error_type": type(e).__name__,
            })
        except Exception:
            pass
        json.dump({}, sys.stdout)
        sys.exit(0)
