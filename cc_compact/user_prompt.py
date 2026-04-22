#!/usr/bin/env python3
"""UserPromptSubmit hook entry — injects a pointer to the memory file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `lib` importable when invoked directly by the CLI or deployed to .claude/hooks/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import core, hook_runner, memory  # noqa: E402


def main(payload: dict) -> None:
    session_id = payload["session_id"]

    root = memory.find_project_root(Path.cwd())
    mem_file = memory.find_memory_path(root, session_id)

    if mem_file is None:
        json.dump({}, sys.stdout)
        return

    size = mem_file.stat().st_size
    hook_runner.safe_trace(root, session_id, {
        "hook": "UserPromptSubmit",
        "memory_bytes": size,
        "pointer_injected": True,
    })
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": core.prompt_pointer_text(mem_file.name, size),
        }
    }, sys.stdout)


if __name__ == "__main__":
    hook_runner.run_hook(main, "UserPromptSubmit")
