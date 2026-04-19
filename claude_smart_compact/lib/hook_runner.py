"""Shared entry-point scaffolding for hook scripts.

Both hook scripts (`pre_compact.py`, `user_prompt.py`) share:
  * a `safe_trace` helper that appends one JSONL event to the session trace
    file (and silently drops the event if no session_id is known), and
  * an outer `try/except/exit 0` wrapper that records the error to the trace,
    writes `{}` to stdout, and never propagates a non-zero exit code.

This module owns both pieces so new hooks do not duplicate them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Optional

from . import memory


def safe_trace(project_root: Path, session_id: Optional[str], event: dict) -> None:
    """Append one trace event for `session_id`, swallowing any I/O error."""
    if not session_id:
        return
    try:
        memory.append_trace(memory.trace_path(project_root, session_id), event)
    except Exception:
        pass


def run_hook(payload_fn: Callable[[dict], None], hook_name: str) -> None:
    """Read stdin as JSON and dispatch to `payload_fn(payload)`.

    On any exception (including a malformed-JSON stdin), record the error to
    the session trace (best-effort), write `{}` to stdout, and exit 0. Claude
    Code's hook contract requires a soft-fail: a non-zero exit would abort the
    host session.
    """
    payload: dict = {}
    try:
        payload = json.load(sys.stdin)
        payload_fn(payload)
    except Exception as e:
        try:
            root = memory.find_project_root(Path.cwd())
            session_id = payload.get("session_id") if isinstance(payload, dict) else None
            safe_trace(root, session_id, {
                "hook": hook_name,
                "error": str(e),
                "error_type": type(e).__name__,
            })
        except Exception:
            pass
        json.dump({}, sys.stdout)
        sys.exit(0)
