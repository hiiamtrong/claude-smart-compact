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


def main() -> None:
    payload = json.load(sys.stdin)
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
                "hook": "UserPromptSubmit",
                "error": str(e),
                "error_type": type(e).__name__,
            })
        except Exception:
            pass
        json.dump({}, sys.stdout)
        sys.exit(0)
