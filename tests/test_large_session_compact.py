"""End-to-end compaction test on a synthetic ~1M-token session.

Simulates a real long-running CLI session (huge transcript, many assistant
turns, multiple TodoWrite snapshots with an in-flight todo) and drives both
hooks through subprocess — same entry points Claude Code would invoke.

Asserts:
  * PreCompact tolerates a multi-MB transcript (no OOM, finishes in seconds).
  * Memory file stays small regardless of transcript size (summary, not copy).
  * Active Task = the real last user prompt (not tool-result noise).
  * Latest TodoWrite's in-progress / pending todos are preserved.
  * UserPromptSubmit injects the pointer with the expected session id.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# ~1M tokens ≈ 4MB of UTF-8 text (≈4 chars/token for English).
TARGET_TRANSCRIPT_BYTES = 4 * 1024 * 1024

# 400-byte payload per assistant turn → ~10k turns to hit 4MB.
FILLER_CHUNK = (
    "Reading file contents and analyzing the call graph. "
    "Checked imports, traced the dataflow across the module boundary, "
    "and cross-referenced the test fixtures against the production code path. "
) * 2  # ≈ 400 bytes


def _write_large_transcript(path: Path, target_bytes: int) -> dict:
    """Write a realistic CLI-format JSONL with the structure:

        real user prompt
        (many) assistant turns (text + tool_use mix)
        TodoWrite snapshot #1 (one in_progress)
        more assistant work
        TodoWrite snapshot #2 (two in_progress, one pending, one completed)
        tool-result user turns (CLI-injected; must be skipped)
        final assistant turn

    Returns a summary dict with the invariants the test will assert on.
    """
    active_task = "refactor the payments module to support idempotency keys"
    latest_todos = [
        {"content": "audit existing retry logic", "status": "completed",
         "activeForm": "Auditing retry logic"},
        {"content": "design idempotency key schema", "status": "in_progress",
         "activeForm": "Designing idempotency key schema"},
        {"content": "wire key into charge endpoint", "status": "in_progress",
         "activeForm": "Wiring key into charge endpoint"},
        {"content": "add integration tests", "status": "pending",
         "activeForm": "Adding integration tests"},
    ]

    written = 0
    lines: list[str] = []

    def emit(obj: dict) -> None:
        nonlocal written
        s = json.dumps(obj, ensure_ascii=False) + "\n"
        lines.append(s)
        written += len(s.encode("utf-8"))

    # Harness metadata (parser must skip these).
    emit({"type": "permission-mode", "permissionMode": "default",
          "sessionId": "large"})
    emit({"type": "file-history-snapshot", "messageId": "m0",
          "snapshot": {"trackedFileBackups": {}, "timestamp": "2026-04-19T00:00:00Z"},
          "isSnapshotUpdate": False})

    # Real user prompt (the Active Task we expect to extract).
    emit({
        "type": "user",
        "message": {"role": "user", "content": active_task},
        "uuid": "u-real", "timestamp": "2026-04-19T00:00:01Z",
    })

    # First TodoWrite (older snapshot — should be overwritten by the later one).
    emit({
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "td1", "name": "TodoWrite",
             "input": {"todos": [
                 {"content": "audit existing retry logic",
                  "status": "in_progress",
                  "activeForm": "Auditing retry logic"},
             ]}},
        ]},
        "uuid": "a-todo1", "timestamp": "2026-04-19T00:00:02Z",
    })

    # Bulk of the transcript: alternating text + tool_use + tool_result envelopes.
    i = 0
    while written < target_bytes - 8_000:  # leave headroom for closing turns
        i += 1
        # assistant text
        emit({
            "type": "assistant",
            "message": {"role": "assistant", "content": FILLER_CHUNK + f" [step {i}]"},
            "uuid": f"a{i}",
        })
        # assistant tool_use (Bash)
        emit({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"t{i}", "name": "Bash",
                 "input": {"command": f"pytest -q tests/module_{i % 50}.py"}},
            ]},
            "uuid": f"a{i}-t",
        })
        # CLI-injected tool result (role=user, but must be skipped by the hook)
        emit({
            "type": "user",
            "toolUseResult": {"stdout": "ok", "exitCode": 0},
            "message": {"role": "user", "content": [
                {"tool_use_id": f"t{i}", "type": "tool_result",
                 "content": FILLER_CHUNK},
            ]},
            "uuid": f"u{i}-tr",
        })

    # Final, authoritative TodoWrite snapshot (the one the hook must pick up).
    emit({
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "td-final", "name": "TodoWrite",
             "input": {"todos": latest_todos}},
        ]},
        "uuid": "a-todo-final",
    })
    # A closing assistant text turn so in-flight isn't empty.
    emit({
        "type": "assistant",
        "message": {"role": "assistant",
                    "content": "about to hit context limit — compacting"},
        "uuid": "a-final",
    })

    path.write_text("".join(lines), encoding="utf-8")
    return {
        "active_task": active_task,
        "latest_todos": latest_todos,
        "bytes": written,
        "assistant_loops": i,
    }


def _run(script: str, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "cc_compact" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
    )


@pytest.mark.slow
def test_compact_on_simulated_1m_token_session(project_root, tmp_path):
    transcript = tmp_path / "huge_session.jsonl"
    summary = _write_large_transcript(transcript, TARGET_TRANSCRIPT_BYTES)

    assert summary["bytes"] >= TARGET_TRANSCRIPT_BYTES - 1_000_000, (
        f"transcript only {summary['bytes']} bytes, expected ~{TARGET_TRANSCRIPT_BYTES}"
    )

    session_id = "sim-1m-tokens"

    # --- PreCompact -------------------------------------------------------
    pre_start = time.monotonic()
    pre = _run("pre_compact.py", {
        "session_id": session_id,
        "transcript_path": str(transcript),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }, project_root)
    pre_elapsed = time.monotonic() - pre_start

    assert pre.returncode == 0, pre.stderr
    assert json.loads(pre.stdout) == {}, "PreCompact stdout must be empty JSON"
    assert pre_elapsed < 30, f"PreCompact too slow on 4MB transcript: {pre_elapsed:.2f}s"

    mem_file = project_root / ".claude" / "compact-memory" / f"{session_id}.md"
    assert mem_file.exists(), "memory file must be written"

    md = mem_file.read_text(encoding="utf-8")

    # Memory file must be a summary, not a blow-up of the transcript.
    assert mem_file.stat().st_size < 100_000, (
        f"memory file too large ({mem_file.stat().st_size} B) — "
        f"should summarize, not copy the transcript"
    )

    # Active Task extracted from the real user prompt.
    assert "## Active Task" in md
    assert summary["active_task"] in md
    quoted = [ln for ln in md.splitlines() if ln.startswith("> ")]
    assert quoted and quoted[0] == f"> {summary['active_task']}"

    # Latest todos (not the stale first snapshot) must be preserved.
    assert "## Open Todos" in md
    assert "design idempotency key schema" in md
    assert "wire key into charge endpoint" in md
    assert "add integration tests" in md
    # Completed-only todos must NOT be rendered (pre_compact filters them).
    assert "audit existing retry logic" not in md

    # Preferences section exists with the default placeholder on first run.
    assert "## Preferences" in md

    # --- Trace record ----------------------------------------------------
    trace = project_root / ".claude" / "compact-memory" / f"{session_id}.trace.jsonl"
    assert trace.exists()
    trace_events = [json.loads(ln) for ln in trace.read_text().splitlines() if ln.strip()]
    assert len(trace_events) == 1
    ev = trace_events[0]
    assert ev["hook"] == "PreCompact"
    assert ev["trigger"] == "auto"
    # last_user_index must point at the real prompt we injected (index 0 in our
    # parsed stream, since harness-metadata lines are skipped by parse_jsonl).
    assert ev["last_user_index"] == 0
    assert ev["todos_count"] == 3  # 2 in_progress + 1 pending
    assert ev["preserved_preferences"] is False
    # messages_count counts only the VALID role messages (harness metadata skipped).
    # assistant loops × 2 (text + tool_use) + CLI-injected user tool_results
    # + 1 real user + 2 TodoWrite snapshots + 1 closing assistant.
    expected_min = summary["assistant_loops"] * 3 + 4
    assert ev["messages_count"] >= expected_min - 5

    # --- UserPromptSubmit (post-compaction) ------------------------------
    up = _run("user_prompt.py", {
        "session_id": session_id,
        "hook_event_name": "UserPromptSubmit",
        "prompt": "continue",
    }, project_root)
    assert up.returncode == 0, up.stderr
    out = json.loads(up.stdout)
    hook_out = out["hookSpecificOutput"]
    assert hook_out["hookEventName"] == "UserPromptSubmit"
    ctx = hook_out["additionalContext"]
    assert session_id in ctx
    assert ".claude/compact-memory" in ctx

    # A second trace event got appended by UserPromptSubmit.
    trace_events = [json.loads(ln) for ln in trace.read_text().splitlines() if ln.strip()]
    assert len(trace_events) == 2
    assert trace_events[1]["hook"] == "UserPromptSubmit"
    assert trace_events[1]["pointer_injected"] is True


def _write_post_compact_transcript(path: Path, target_bytes: int) -> dict:
    """Simulate the transcript state AFTER a first auto-compact: the old
    conversation is replaced with a short synthetic summary message, then the
    session continues with a brand-new user prompt, new work, and a new
    TodoWrite snapshot.

    This is how Claude Code's auto-compact leaves the transcript — earlier
    turns collapse into a summary, session_id persists, and new activity gets
    appended to the same file.
    """
    new_active_task = "now add rate limiting to the /charge endpoint"
    new_todos = [
        {"content": "identify hot paths in charge handler", "status": "completed",
         "activeForm": "Identifying hot paths"},
        {"content": "pick rate-limit algorithm (token bucket vs. sliding window)",
         "status": "in_progress",
         "activeForm": "Picking rate-limit algorithm"},
        {"content": "wire redis-backed limiter middleware",
         "status": "pending",
         "activeForm": "Wiring redis-backed limiter middleware"},
    ]

    written = 0
    lines: list[str] = []

    def emit(obj: dict) -> None:
        nonlocal written
        s = json.dumps(obj, ensure_ascii=False) + "\n"
        lines.append(s)
        written += len(s.encode("utf-8"))

    # 1. Post-compact synthetic summary (what CC injects after auto-compact).
    emit({
        "type": "user",
        "message": {"role": "user", "content":
            "[compact-summary] Earlier: refactored payments for idempotency; "
            "schema + charge endpoint done; integration tests pending."},
        "uuid": "u-summary",
    })
    # Assistant acknowledges the compact
    emit({
        "type": "assistant",
        "message": {"role": "assistant", "content":
            "Resuming from compact. Read memory file for prior todos + prefs."},
        "uuid": "a-resume",
    })

    # 2. The new user prompt (the new Active Task).
    emit({
        "type": "user",
        "message": {"role": "user", "content": new_active_task},
        "uuid": "u-new",
    })

    # 3. New assistant work — bulk filler until we cross target_bytes again.
    i = 0
    while written < target_bytes - 8_000:
        i += 1
        emit({
            "type": "assistant",
            "message": {"role": "assistant",
                        "content": FILLER_CHUNK + f" [rl step {i}]"},
            "uuid": f"rl-a{i}",
        })
        emit({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"rl-t{i}", "name": "Bash",
                 "input": {"command": f"redis-cli INFO memory | grep peak_{i % 10}"}},
            ]},
            "uuid": f"rl-a{i}-t",
        })
        emit({
            "type": "user",
            "toolUseResult": {"stdout": "ok", "exitCode": 0},
            "message": {"role": "user", "content": [
                {"tool_use_id": f"rl-t{i}", "type": "tool_result",
                 "content": "used_memory_peak: 12MB"},
            ]},
            "uuid": f"rl-u{i}-tr",
        })

    # 4. New TodoWrite snapshot — the one the 2nd compact must pick up.
    emit({
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "rl-td", "name": "TodoWrite",
             "input": {"todos": new_todos}},
        ]},
        "uuid": "rl-a-todo",
    })
    emit({
        "type": "assistant",
        "message": {"role": "assistant",
                    "content": "context limit hit again — recompacting"},
        "uuid": "rl-a-final",
    })

    path.write_text("".join(lines), encoding="utf-8")
    return {
        "new_active_task": new_active_task,
        "new_todos": new_todos,
        "bytes": written,
        "assistant_loops": i,
    }


@pytest.mark.slow
def test_compact_twice_in_same_session_persists_across_both_rounds(project_root, tmp_path):
    """Simulate two full compact cycles in the same session.

    Timeline:
      1. Session A runs to ~4MB transcript with 'refactor payments' active task.
      2. PreCompact #1 writes memory.md v1.
      3. Agent appends a user preference (agent-authored behavior).
      4. UserPromptSubmit fires on next user turn — pointer injected.
      5. Session continues (compact summary + new prompt + new TodoWrite + more work)
         until hitting context limit again (~4MB again).
      6. PreCompact #2 writes memory.md v2 — OVERWRITING the snapshot fields
         but keeping the agent-authored Preferences line.

    Asserts that each round captures the correct Active Task + todos, and
    that cross-round state (preferences, trace ledger) accumulates correctly.
    """
    session_id = "two-compact-sim"
    mem_file = project_root / ".claude" / "compact-memory" / f"{session_id}.md"
    trace_file = project_root / ".claude" / "compact-memory" / f"{session_id}.trace.jsonl"

    # --- Round 1: first compact ------------------------------------------
    tx1 = tmp_path / "round1.jsonl"
    r1 = _write_large_transcript(tx1, TARGET_TRANSCRIPT_BYTES)

    r1_result = _run("pre_compact.py", {
        "session_id": session_id,
        "transcript_path": str(tx1),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }, project_root)
    assert r1_result.returncode == 0, r1_result.stderr
    assert mem_file.exists()

    v1 = mem_file.read_text(encoding="utf-8")
    assert r1["active_task"] in v1
    assert "design idempotency key schema" in v1
    assert "wire key into charge endpoint" in v1
    assert "add integration tests" in v1
    v1_size = mem_file.stat().st_size
    assert v1_size < 100_000

    # --- Agent appends a preference between compacts ---------------------
    v1_with_pref = v1.replace(
        "## Preferences\n_(none yet)_",
        "## Preferences\n- always run `pytest --cov` before commit\n"
        "- feature-flag any new middleware",
    )
    mem_file.write_text(v1_with_pref, encoding="utf-8")

    # --- UserPromptSubmit fires on the first prompt post-compact ---------
    up = _run("user_prompt.py", {
        "session_id": session_id,
        "hook_event_name": "UserPromptSubmit",
        "prompt": "now add rate limiting",
    }, project_root)
    assert up.returncode == 0
    assert session_id in json.loads(up.stdout)["hookSpecificOutput"]["additionalContext"]

    # --- Round 2: session continued, hit limit again ---------------------
    tx2 = tmp_path / "round2.jsonl"
    r2 = _write_post_compact_transcript(tx2, TARGET_TRANSCRIPT_BYTES)
    assert r2["bytes"] >= TARGET_TRANSCRIPT_BYTES - 1_000_000

    r2_result = _run("pre_compact.py", {
        "session_id": session_id,
        "transcript_path": str(tx2),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }, project_root)
    assert r2_result.returncode == 0, r2_result.stderr

    v2 = mem_file.read_text(encoding="utf-8")

    # Active Task refreshed to the NEW prompt (old one is gone from snapshot fields).
    assert r2["new_active_task"] in v2
    assert r1["active_task"] not in v2, (
        "v2 still references round-1 active task — snapshot fields not refreshed"
    )

    # Todos refreshed to the new snapshot; old round-1 todos are NOT in v2.
    assert "pick rate-limit algorithm" in v2
    assert "wire redis-backed limiter middleware" in v2
    assert "design idempotency key schema" not in v2
    assert "wire key into charge endpoint" not in v2

    # Preferences the agent authored between rounds SURVIVE.
    assert "always run `pytest --cov` before commit" in v2
    assert "feature-flag any new middleware" in v2

    # Memory size stays bounded across rounds (doesn't accumulate transcripts).
    assert mem_file.stat().st_size < 100_000, (
        f"memory file ballooned to {mem_file.stat().st_size} B across rounds"
    )

    # --- Trace ledger accumulates all three hook runs --------------------
    events = [json.loads(ln) for ln in trace_file.read_text().splitlines() if ln.strip()]
    assert [e["hook"] for e in events] == [
        "PreCompact",
        "UserPromptSubmit",
        "PreCompact",
    ]
    # Round 1 wrote first snapshot; round 2 saw the preserved preferences.
    assert events[0]["preserved_preferences"] is False
    assert events[2]["preserved_preferences"] is True
    # Todos_count reflects in_progress + pending per round.
    assert events[0]["todos_count"] == 3  # round 1: 2 in_progress + 1 pending
    assert events[2]["todos_count"] == 2  # round 2: 1 in_progress + 1 pending


@pytest.mark.slow
def test_compact_preserves_preferences_across_1m_session(project_root, tmp_path):
    """Re-running PreCompact on the same session must keep a user-authored
    `## Preferences` section — even when the transcript is huge."""
    transcript = tmp_path / "huge_session_prefs.jsonl"
    _write_large_transcript(transcript, TARGET_TRANSCRIPT_BYTES // 2)

    session_id = "sim-1m-prefs"
    mem_dir = project_root / ".claude" / "compact-memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / f"{session_id}.md").write_text(
        "# Session Memory\n\n## Active Task\n> old\n\n"
        "## Open Todos\n_(none)_\n\n"
        "## Preferences\n- never run migrations on prod without approval\n"
        "- prefer pytest over unittest\n",
        encoding="utf-8",
    )

    result = _run("pre_compact.py", {
        "session_id": session_id,
        "transcript_path": str(transcript),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }, project_root)
    assert result.returncode == 0, result.stderr

    md = (mem_dir / f"{session_id}.md").read_text(encoding="utf-8")
    assert "never run migrations on prod without approval" in md
    assert "prefer pytest over unittest" in md
    # Active Task was refreshed from the new transcript.
    assert "refactor the payments module" in md
