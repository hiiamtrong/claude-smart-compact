# cc-compact

Two Claude Code CLI hooks that preserve task state, in-progress todos, and
user preferences across auto-compaction, without bloating the context window.

## How it works

- **PreCompact** runs when the CLI is about to auto-compact. It reads the
  session transcript, extracts the last user message + in-flight turns + the
  latest `TodoWrite` snapshot, and writes a Markdown memory file to
  `<project>/.claude/compact-memory/<session_id>.md`.
- **UserPromptSubmit** runs on every user prompt after the first compaction.
  It injects a short pointer telling the agent the memory file is available
  and may be read on demand.
- Preferences are **agent-authored** — the hook preserves a `## Preferences`
  section on every run, but does not populate it automatically. Append with
  the Edit tool when the user states a lasting preference.

## Install

From PyPI:

```bash
pip install cc-compact
cd /path/to/your/project
cc-compact install
```

The installer automatically creates or updates `.claude/settings.json` with the required hook entries,
preserving any existing configuration. To skip this and manage `settings.json` manually, pass `--no-settings`.

### Upgrading

`cc-compact install` creates symbolic links into the installed
package by default. After upgrading the package, your hooks in every
project are automatically up-to-date — no need to re-run `install` per
project:

```bash
pipx upgrade cc-compact   # or: pip install -U cc-compact
```

If you prefer to copy files (e.g., for portability across machines without
the package installed), use `--copy`:

```bash
cc-compact install --copy   # needs --force to redeploy after upgrades
```

Windows falls back to `--copy` automatically (symlinks require admin rights).

### Manual (without pip)

If you prefer not to pip install, copy `cc_compact/` into
your project's `.claude/hooks/` directly. The deployed layout is:

```text
<project>/.claude/hooks/
├── pre_compact.py
├── user_prompt.py
└── lib/
    ├── core.py
    ├── hook_runner.py
    ├── memory.py
    └── transcript.py
```

## Verify

Run the manual trace script:

```bash
python3 tests/trace_run.py tests/fixtures/transcript_with_todos.jsonl
```

## Run tests

```bash
pip install -e ".[dev]"
pytest --cov=cc_compact
```

## Debug

Every hook run appends to `<project>/.claude/compact-memory/<session_id>.trace.jsonl`.
`tail -f` this file to watch the hooks work in real time.
