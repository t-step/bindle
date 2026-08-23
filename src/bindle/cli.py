"""bindle CLI entrypoint.

Deliberately small: `--version` and `repo info` (the repository identity
helper in bindle.repo). See AGENTS.md and docs/SCOPE.md for why this
stays minimal.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from . import __version__
from .repo import NotAGitRepositoryError, get_repo_info


def _cmd_repo_info(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle repo info: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(dataclasses.asdict(info), indent=2))
        return 0

    print(f"repository root: {info.repo_root}")
    print(f"worktree root:   {info.worktree_root}")
    print(f"git dir:         {info.git_dir}")
    print(f"git common dir:  {info.git_common_dir}")
    print(f"branch:          {info.branch if info.branch else '(detached HEAD)'}")
    print(f"HEAD SHA:        {info.head_sha}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bindle")
    parser.add_argument(
        "--version", action="version", version=f"bindle {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command")

    repo_parser = subparsers.add_parser("repo", help="Repository identity commands")
    repo_subparsers = repo_parser.add_subparsers(dest="repo_command")
    info_parser = repo_subparsers.add_parser("info", help="Show repository identity")
    info_parser.add_argument("--json", action="store_true", help="Emit JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "repo":
        if args.repo_command == "info":
            return _cmd_repo_info(args)
        parser.parse_args(["repo", "--help"])
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
