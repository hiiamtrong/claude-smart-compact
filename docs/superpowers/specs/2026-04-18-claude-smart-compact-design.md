# Claude Smart Compact — Design

**Date:** 2026-04-18
**Status:** Approved for implementation planning
**Target environment:** Claude Code CLI (not Claude API / Agent SDK)

## Problem

When Claude Code's context window fills and auto-compaction runs, the built-in summarizer can lose or blur task state and stated user preferences. The agent may wake up after compaction confused about what it was doing or which constraints the user set earlier.

## Goal

Build a pair of Claude Code hooks that preserve **task state**, **user preferences/constraints**, and **in-flight work** across auto-compaction, without bloating the context window.

## Non-goals

- Preserving raw tool results (Bash/Read/Grep outputs) — those live in git or disk; compaction summary is fine for them.
- Preserving every file edit ever made — the working tree is authoritative.
- Supporting Claude API / Agent SDK compaction (a separate system with no hook extension point).
- Cross-session memory or long-term knowledge base — scope is within a single session.

## Key design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Environment | Claude Code CLI `PreCompact` + `UserPromptSubmit` hooks | Real hook extension points exist in the CLI |
| Memory content | Task state (A) + conversation facts (C) + recent in-flight work | User's explicit choice |
| In-flight window | Hybrid: all messages since last user turn (D) + latest `TodoWrite` snapshot (C) | Natural checkpoint + task state without regex heuristics |
| Memory location | `<project_root>/.claude/compact-memory/<session_id>.md` | Per-session scope, per-project isolation, travels with project |
| Re-injection | UserPromptSubmit injects a short **pointer** to the memory file; agent reads file on demand | Pointer is ~100 tokens; full memory (kBs) stays off context window until needed |
| Preferences capture | Agent-authored via `## Preferences` section (Option 3) | Zero-cost, high-quality; avoids regex false positives and extra API calls |
| Language | Python 3 (stdlib only) | Available on macOS by default, good test tooling, no deps |
| Error policy | Fail soft, never block CLI | Hooks run in CLI hot path; must not crash user's session |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Claude Code CLI                                              │
│                                                               │
│   ┌─ triggers ──────────┐         ┌─ triggers ─────────┐     │
│   │  PreCompact hook    │         │ UserPromptSubmit    │     │
│   │  (auto-compact)     │         │ (every user prompt) │     │
│   └──────┬──────────────┘         └──────┬──────────────┘     │
│          │                                │                    │
└──────────┼────────────────────────────────┼────────────────────┘
           │ stdin: JSON                    │ stdin: JSON
           ▼                                ▼
    ┌──────────────────┐          ┌──────────────────────┐
    │ pre_compact.py   │          │ user_prompt.py       │
    │                  │          │                      │
    │ Read transcript  │          │ If memory exists →   │
    │ Extract memory   │          │   inject pointer     │
    │ Merge prefs      │          │ Else → no-op         │
    │ Write .md        │          │                      │
    │ Return custom    │          │                      │
    │ compaction       │          │                      │
    │ instructions     │          │                      │
    └────────┬─────────┘          └──────────┬───────────┘
             │                                │
             ▼                                ▼
    ┌──────────────────────────────────────────────┐
    │  <project>/.claude/compact-memory/           │
    │    <session_id>.md        ← memory file      │
    │    <session_id>.trace.jsonl ← hook log       │
    └──────────────────────────────────────────────┘
             ▲
             │ imports
    ┌──────────────────┐
    │ hooks/lib/       │
    │   transcript.py  │
    │   core.py        │
    │   memory.py      │
    └──────────────────┘
```

**Configuration in `<project>/.claude/settings.json`:**

```json
{
  "hooks": {
    "PreCompact": [{
      "hooks": [{"type": "command", "command": "python3 .claude/hooks/pre_compact.py"}]
    }],
    "UserPromptSubmit": [{
      "hooks": [{"type": "command", "command": "python3 .claude/hooks/user_prompt.py"}]
    }]
  }
}
```

## Data flow

### Flow A — PreCompact (fires when CLI decides to compact)

Input via stdin:
```json
{"session_id":"abc123",
 "transcript_path":"/path/to/transcript.jsonl",
 "hook_event_name":"PreCompact",
 "trigger":"auto"}
```

Steps:
1. Parse stdin JSON.
2. `transcript.parse_jsonl(transcript_path)` → `list[Message]`.
3. Extract memory:
   - `last_user_idx = find_last_user_index(messages)`.
   - `in_flight = messages[last_user_idx:]` — Tier 1 (D).
   - `todos = extract_latest_todos(messages)` where `status in (in_progress, pending)` — Tier 2 (C).
4. `existing_prefs = read_preferences_section(memory_file)` — preserve across compactions.
5. `md = compose_memory_markdown(...)` — render Markdown with 4 sections.
6. `write_atomic(memory_file, md)`.
7. `append_trace(...)` — one JSONL event.
8. stdout:
   ```json
   {"hookSpecificOutput": {
     "hookEventName": "PreCompact",
     "additionalContext": "<custom compaction instructions>"
   }}
   ```

**Custom compaction instructions** injected:
> "When summarizing, preserve: (1) the last user message verbatim, (2) any in_progress todos with their exact wording, (3) any stated user preferences or constraints. A structured memory file at `.claude/compact-memory/<session_id>.md` is also persisted for reference."

### Flow B — UserPromptSubmit (fires every user prompt)

Input via stdin:
```json
{"session_id":"abc123",
 "hook_event_name":"UserPromptSubmit",
 "prompt":"..."}
```

Steps:
1. Parse stdin JSON.
2. `mem_file = memory_path(root, session_id)`.
3. If file does not exist → stdout `{}`, exit 0. (No-op before first compact.)
4. If file exists:
   - Read size.
   - `append_trace(...)`.
   - stdout:
     ```json
     {"hookSpecificOutput": {
       "hookEventName": "UserPromptSubmit",
       "additionalContext": "Persistent session memory available at `.claude/compact-memory/<sid>.md` (~{size}KB). Read it at the start of your next action if you need context about task state, in-progress todos, or user preferences. If the user states a lasting preference or constraint, append it under the `## Preferences` section using the Edit tool."
     }}
     ```

### Flow state diagram

| Stage | PreCompact run count | Memory file | UserPromptSubmit behavior |
|-------|----------------------|-------------|---------------------------|
| Fresh session, before compact | 0 | Does not exist | No-op (stdout `{}`) |
| After first compact | 1 | Exists (Active Task + Todos + empty Preferences) | Inject pointer |
| After second compact | 2 | Overwritten; Preferences section preserved | Inject pointer |
| Agent appends preference via Edit | N | Preferences section grows | Next PreCompact preserves it |

## Memory file format

```markdown
# Session Memory
<!-- session_id: abc123 | generated_at: 2026-04-18T10:23:11Z -->

## Active Task
_From the last user prompt in this session._

> {last user message verbatim}

**In-flight turns (since last user prompt):**
- {for each turn: first non-empty line of content, truncated to 120 chars; tool calls rendered as `tool: <name>`}
- ...

## Open Todos
- [ ] {todo.content} (status: in_progress)
- [ ] {todo.content} (status: pending)

_(none)_    ← if no todos

## Preferences
_Append lasting preferences/constraints stated by the user here.
Agent: use Edit tool to append; never rewrite existing entries._

- {preserved preference from previous compaction, if any}
```

## Component design

### `hooks/lib/transcript.py` (pure, no I/O)

```python
@dataclass
class Message:
    role: Literal["user","assistant","system","tool"]
    content: str
    raw: dict
    index: int

@dataclass
class TodoItem:
    content: str
    status: Literal["pending","in_progress","completed"]

def parse_jsonl(path: str) -> list[Message]:
    """Stream-read JSONL; skip corrupt lines; return ordered list."""

def find_last_user_index(messages: list[Message]) -> int | None:
    """Return index of last role=user message, or None."""

def extract_latest_todos(messages: list[Message]) -> list[TodoItem]:
    """Find most recent TodoWrite tool call; parse its todo list."""

def slice_in_flight(messages: list[Message], from_index: int) -> list[Message]:
    """Return messages[from_index:]."""
```

### `hooks/lib/core.py` (pure)

```python
def compose_memory_markdown(
    session_id: str,
    active_task_user_msg: str,
    in_flight: list[Message],
    todos: list[TodoItem],
    existing_preferences_section: str | None,
) -> str: ...

def compaction_instructions() -> str: ...

def prompt_pointer_text(session_id: str, memory_size_bytes: int) -> str: ...
```

### `hooks/lib/memory.py` (file I/O)

```python
def memory_dir(project_root: Path) -> Path: ...
def memory_path(project_root: Path, session_id: str) -> Path: ...
def trace_path(project_root: Path, session_id: str) -> Path: ...
def read_preferences_section(path: Path) -> str | None: ...
def write_atomic(path: Path, content: str) -> None: ...
def append_trace(path: Path, event: dict) -> None: ...
def find_project_root(start: Path) -> Path: ...
```

### `hooks/pre_compact.py` and `hooks/user_prompt.py` (thin entry scripts)

Each ~15–25 lines. Read stdin JSON, orchestrate calls into `lib/`, write stdout JSON, always wrap `main()` in try/except that falls back to `{}` stdout.

## Error handling — Fail soft, never block

Top-level pattern for both entry scripts:

```python
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            memory.append_trace(trace_path, {"hook": "...", "error": str(e), "error_type": type(e).__name__})
        except Exception:
            pass
        json.dump({}, sys.stdout)
        sys.exit(0)
```

### Edge cases handled

| # | Case | Behavior |
|---|------|----------|
| E1 | Transcript file missing | `parse_jsonl` returns `[]`; no memory written; stdout `{}` |
| E2 | Corrupt JSONL line | Skip line; log `skipped_lines` count in trace |
| E3 | Session has no user message yet | `last_user_idx = None`; memory file not written |
| E4 | No TodoWrite in transcript | `todos = []`; section renders `_(none)_` |
| E5 | Memory file exists, no `## Preferences` | `read_preferences_section` → `None`; placeholder used |
| E6 | Memory file exists, `## Preferences` populated | Preserve verbatim; merge into new output |
| E7 | User deletes `compact-memory/` mid-session | Next UserPromptSubmit: no-op; next PreCompact re-creates |
| E8 | Atomic write fails | Top-level handler catches; stdout `{}` |
| E9 | Two parallel sessions on same project | Different `session_id` → different files, no conflict |
| E10 | Transcript >100 MB | Stream line-by-line; constant memory usage |
| E11 | Hook timeout | Design keeps runtime <500 ms: no network, no heavy compute |
| E12 | `.claude/` missing | `find_project_root` falls back to cwd; dir auto-created |
| E13 | Invalid stdin JSON | Top-level handler catches; stdout `{}` |
| E14 | Two compactions in one session | PreCompact overwrites Active Task + Todos; merges Preferences |
| E15 | Empty last user message | Placeholder `_(no active prompt)_` |

### Intentionally NOT handled (YAGNI)

- Concurrent writes (CLI serializes hook runs within one session).
- Manual corruption of memory file (next PreCompact overwrites cleanly).
- Retry logic (fail soft is sufficient).
- Trace log rotation (typical session writes <50 lines, <10 KB).

## Testing strategy

### Test layout

```
tests/
├── conftest.py                     shared fixtures
├── fixtures/                        7 transcript JSONL fixtures
├── test_transcript.py              10 unit tests
├── test_core.py                     8 unit tests
├── test_memory.py                  10 unit tests
├── test_pre_compact.py              6 subprocess integration tests
├── test_user_prompt.py              5 subprocess integration tests
└── test_edge_cases.py              15 tests (1 per E1–E15)
```

Total: ~54 test cases. Runner: `pytest`. Only dev dependency: `pytest` (+ `pytest-cov` optional).

### Coverage targets

- `hooks/lib/` → ≥ 90 %.
- Entry scripts (`pre_compact.py`, `user_prompt.py`) → ≥ 70 %.
- All E1–E15 edge cases explicitly covered.

### Tracing test (answers "how do I verify injection works?")

`tests/trace_run.py` — manual end-to-end script:

```bash
python3 tests/trace_run.py <path-to-real-transcript.jsonl>
```

Runs both hooks against a real transcript, pretty-prints stdin/stdout JSON and the memory file, and dumps the trace log — enabling eyeball verification before deployment.

### Runtime trace observability

Every hook invocation appends one line to `<session_id>.trace.jsonl`:

```json
{"ts":"2026-04-18T10:23:11Z","hook":"PreCompact","trigger":"auto","messages_count":142,"last_user_index":128,"todos_count":2,"memory_bytes":2341,"preserved_preferences":true}
{"ts":"2026-04-18T10:24:05Z","hook":"UserPromptSubmit","memory_bytes":2341,"pointer_injected":true}
```

`tail -f` this file to debug any production issue.

## Out of scope for v1

- CI pipeline (GitHub Actions).
- Cross-session memory aggregation.
- TUI or dashboard for browsing memory files.
- Auto-prune of old session memory files (deferred — user can `rm` manually).
- Support for multiple simultaneous memory backends (e.g., SQLite).

## Success criteria

1. After auto-compact fires, the agent's next action demonstrates awareness of:
   - The last user prompt before the compact,
   - Current in-progress todos (wording preserved),
   - Any preferences captured under `## Preferences`.
2. `trace.jsonl` shows a `PreCompact` record then subsequent `UserPromptSubmit` records with `pointer_injected: true` and matching `memory_bytes`.
3. Test suite green (`pytest` returns 0), coverage targets met.
4. Hook adds <500 ms latency to any single CLI operation.
5. No hook crash ever propagates to the CLI; `stdout {}` on any internal failure.
