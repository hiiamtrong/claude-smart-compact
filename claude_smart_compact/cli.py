"""Command-line entry for installing claude-smart-compact hooks into a project."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__

PACKAGE_DIR = Path(__file__).resolve().parent
HOOK_FILES = ("pre_compact.py", "user_prompt.py")
LIB_DIR = "lib"

SETTINGS_SNIPPET = """{
  "hooks": {
    "PreCompact": [
      {"hooks": [{"type": "command", "command": "python3 .claude/hooks/pre_compact.py"}]}
    ],
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "python3 .claude/hooks/user_prompt.py"}]}
    ]
  }
}"""

PRE_COMPACT_ENTRY = {"hooks": [{"type": "command", "command": "python3 .claude/hooks/pre_compact.py"}]}
USER_PROMPT_ENTRY = {"hooks": [{"type": "command", "command": "python3 .claude/hooks/user_prompt.py"}]}


def _entry_command(entry: dict) -> str | None:
    try:
        return entry["hooks"][0]["command"]
    except (KeyError, IndexError, TypeError):
        return None


def _merge_settings(project_dir: Path) -> int:
    settings = project_dir / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)

    if settings.exists():
        raw = settings.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"error: could not parse {settings}: {e}", file=sys.stderr)
            print("\nMerge this manually:\n", file=sys.stderr)
            print(SETTINGS_SNIPPET, file=sys.stderr)
            return 1
        if not isinstance(data, dict):
            print(f"error: {settings} is not a JSON object", file=sys.stderr)
            return 1
        backup = settings.with_suffix(settings.suffix + ".bak")
        backup.write_text(raw, encoding="utf-8")
    else:
        data = {}

    hooks = data.setdefault("hooks", {})
    for event_name, entry in [("PreCompact", PRE_COMPACT_ENTRY), ("UserPromptSubmit", USER_PROMPT_ENTRY)]:
        bucket = hooks.setdefault(event_name, [])
        if not isinstance(bucket, list):
            print(f"error: {settings} hooks.{event_name} is not a list", file=sys.stderr)
            return 1
        cmd = _entry_command(entry)
        already = any(_entry_command(existing) == cmd for existing in bucket)
        if not already:
            bucket.append(entry)

    tmp = settings.with_suffix(settings.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, settings)
    print(f"settings: merged {settings}")
    return 0


def install(project_dir: Path, force: bool, write_settings: bool = True) -> int:
    target = project_dir / ".claude" / "hooks"
    target.mkdir(parents=True, exist_ok=True)

    for name in HOOK_FILES:
        src = PACKAGE_DIR / name
        dst = target / name
        if dst.exists() and not force:
            print(f"skip: {dst} already exists (use --force to overwrite)", file=sys.stderr)
            continue
        shutil.copy2(src, dst)
        print(f"installed: {dst}")

    lib_src = PACKAGE_DIR / LIB_DIR
    lib_dst = target / LIB_DIR
    if lib_dst.exists():
        if force:
            shutil.rmtree(lib_dst)
        else:
            print(f"skip: {lib_dst} already exists (use --force to overwrite)", file=sys.stderr)
            if not write_settings:
                print("\nNext step: merge the following into .claude/settings.json:\n")
                print(SETTINGS_SNIPPET)
                return 0
            return _merge_settings(project_dir)
    shutil.copytree(lib_src, lib_dst, ignore=shutil.ignore_patterns("__pycache__"))
    print(f"installed: {lib_dst}/")

    if not write_settings:
        print("\nNext step: merge the following into .claude/settings.json:\n")
        print(SETTINGS_SNIPPET)
        return 0

    return _merge_settings(project_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claude-smart-compact",
        description="Install Claude Code smart-compact hooks into a project.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    inst = sub.add_parser("install", help="Copy hooks into <project>/.claude/hooks/")
    inst.add_argument("--dir", type=Path, default=Path.cwd(),
                      help="Project directory (default: current directory)")
    inst.add_argument("--force", action="store_true",
                      help="Overwrite existing files")
    inst.add_argument("--no-settings", dest="write_settings", action="store_false", default=True,
                      help="Skip automatic settings.json merge")
    args = parser.parse_args(argv)
    if args.command == "install":
        return install(args.dir, args.force, args.write_settings)
    return 1


if __name__ == "__main__":
    sys.exit(main())
