#!/usr/bin/env python3
"""Manual end-to-end verification script.

Usage:
    python3 tests/trace_run.py <path-to-real-transcript.jsonl>

Pipes a fake stdin payload through each hook in sequence against a real
transcript file, printing all JSON I/O and the resulting memory file.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def main(transcript_path: str) -> None:
    tx = Path(transcript_path).resolve()
    if not tx.exists():
        sys.exit(f"error: transcript not found: {tx}")

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        (cwd / ".claude").mkdir()
        sid = "trace-run-session"

        # 1. PreCompact
        pre_payload = json.dumps({
            "session_id": sid,
            "transcript_path": str(tx),
            "hook_event_name": "PreCompact",
            "trigger": "manual",
        })
        print("=== PreCompact stdin ===")
        print(pre_payload)
        pre = subprocess.run(
            [sys.executable, str(REPO / "hooks/pre_compact.py")],
            input=pre_payload, capture_output=True, text=True, cwd=cwd,
        )
        print("=== PreCompact stdout ===")
        print(pre.stdout or "<empty>")
        print("=== PreCompact stderr ===")
        print(pre.stderr or "<empty>")

        mem_file = cwd / ".claude/compact-memory" / f"{sid}.md"
        if mem_file.exists():
            print("=== memory file ===")
            print(mem_file.read_text())
        else:
            print("(no memory file written)")

        # 2. UserPromptSubmit
        up_payload = json.dumps({
            "session_id": sid,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "continue the task",
        })
        print("=== UserPromptSubmit stdin ===")
        print(up_payload)
        up = subprocess.run(
            [sys.executable, str(REPO / "hooks/user_prompt.py")],
            input=up_payload, capture_output=True, text=True, cwd=cwd,
        )
        print("=== UserPromptSubmit stdout ===")
        print(up.stdout or "<empty>")

        trace = cwd / ".claude/compact-memory" / f"{sid}.trace.jsonl"
        if trace.exists():
            print("=== trace.jsonl ===")
            print(trace.read_text())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: trace_run.py <path-to-transcript.jsonl>")
    main(sys.argv[1])
