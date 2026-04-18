"""Command-line entry for installing claude-smart-compact hooks into a project."""
from __future__ import annotations

import argparse
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


def install(project_dir: Path, force: bool) -> int:
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
            print("\nNext step: merge the following into .claude/settings.json:\n")
            print(SETTINGS_SNIPPET)
            return 0
    shutil.copytree(lib_src, lib_dst)
    print(f"installed: {lib_dst}/")

    print("\nNext step: merge the following into .claude/settings.json:\n")
    print(SETTINGS_SNIPPET)
    return 0


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
    args = parser.parse_args(argv)
    if args.command == "install":
        return install(args.dir, args.force)
    return 1


if __name__ == "__main__":
    sys.exit(main())
