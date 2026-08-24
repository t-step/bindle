"""bindle CLI entrypoint.

Establishes the command surface for Bindle's repository and global
lifecycle commands (see AGENTS.md and docs/SCOPE.md). Only `--version`
and `repo info` have real behavior; the lifecycle commands below are
interface-only placeholders until their underlying components are
implemented in a later slice.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from . import __version__
from .repo import NotAGitRepositoryError, get_repo_info

# Lifecycle commands with an established name, short --help summary, and
# longer per-command description, but no implementation yet.
#
# The repository is the primary unit of Bindle management: `init` is the
# explicit per-repository opt-in boundary, and `remove`, `status`,
# `upgrade`, and `doctor` all target the current repository by default.
# Only `list` (global inventory of opted-in repositories) and `update`
# (refresh Bindle's own component/catalog knowledge) are global/machine-
# level — neither targets nor mutates any specific repository. Keep
# insertion order matching the intended `bindle --help` listing order.
_LIFECYCLE_COMMANDS: dict[str, tuple[str, str]] = {
    "init": (
        "Initialize or reconcile Bindle for this repository.",
        "Initialize or reconcile Bindle for the current repository. This "
        "is the explicit opt-in boundary: a repository becomes "
        "Bindle-managed by running `bindle init` in it. Intended to be "
        "safe to run repeatedly as more integrations are added later.",
    ),
    "remove": (
        "Remove Bindle-managed components from this repository.",
        "Remove Bindle-managed components, or Bindle management "
        "entirely, from the current repository.",
    ),
    "list": (
        "List repositories that have opted into Bindle.",
        "List repositories that have explicitly opted into Bindle (via "
        "`bindle init`), and eventually what each has configured. "
        "Global/machine-level and read-only — this does not target or "
        "modify the current repository specifically.",
    ),
    "status": (
        "Show Bindle state for this repository.",
        "Show Bindle-managed state for the current repository: what is "
        "installed and configured here. Repository-targeted and "
        "read-only.",
    ),
    "update": (
        "Refresh Bindle's available component/catalog information.",
        "Refresh Bindle's own available component, version, and catalog "
        "knowledge. Global/machine-level — this refreshes what Bindle "
        "knows, not what is installed anywhere, and never mutates a "
        "managed repository; see `bindle upgrade` for that.",
    ),
    "upgrade": (
        "Upgrade installed Bindle-managed components for this repository.",
        "Upgrade Bindle-managed components already installed in the "
        "current repository. Repository-targeted by default: it upgrades "
        "this repository's installed components, not every repository "
        "Bindle knows about.",
    ),
    "doctor": (
        "Diagnose Bindle configuration for this repository.",
        "Diagnose Bindle configuration for the current repository. "
        "Read-only — this command never modifies anything.",
    ),
}


def _cmd_not_implemented(name: str) -> int:
    print(f"bindle {name}: not implemented yet", file=sys.stderr)
    return 1


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

    for name, (help_text, description) in _LIFECYCLE_COMMANDS.items():
        subparsers.add_parser(name, help=help_text, description=description)

    repo_parser = subparsers.add_parser("repo", help="Repository information.")
    repo_subparsers = repo_parser.add_subparsers(dest="repo_command")
    info_parser = repo_subparsers.add_parser("info", help="Show repository identity")
    info_parser.add_argument("--json", action="store_true", help="Emit JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in _LIFECYCLE_COMMANDS:
        return _cmd_not_implemented(args.command)

    if args.command == "repo":
        if args.repo_command == "info":
            return _cmd_repo_info(args)
        parser.parse_args(["repo", "--help"])
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
