"""bindle CLI entrypoint.

Establishes the command surface for Bindle's repository and global
lifecycle commands (see AGENTS.md and docs/SCOPE.md). `--version`,
`repo info`, `init`, `remove`, and `migrate-legacy-global` have real
behavior today; `init`/`remove`/`migrate-legacy-global` manage only the
guardrail layer (Git hook dispatch + Claude Code PreToolUse guard) via
install-guardrails.sh — they do not yet manage any other Bindle-owned
component. `list`, `status`, `update`, `upgrade`, and `doctor` remain
interface-only placeholders until their underlying components are
implemented in a later slice.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.resources
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__
from .repo import NotAGitRepositoryError, get_repo_info

# Lifecycle commands with an established name and short/long --help text.
# `init`, `remove`, and `migrate-legacy-global` have real behavior (see
# _cmd_init/_cmd_remove/_cmd_migrate_legacy_global below); the rest remain
# interface-only placeholders (_cmd_not_implemented).
#
# The repository is the primary unit of Bindle management: `init` is the
# explicit per-repository opt-in boundary, and `remove`, `status`,
# `upgrade`, and `doctor` all target the current repository by default.
# `list` (global inventory of opted-in repositories), `update` (refresh
# Bindle's own component/catalog knowledge), and `migrate-legacy-global`
# (the explicit, repo-independent escape hatch for a recognized pre-rework
# GLOBAL guardrail install — see install-guardrails.sh
# --remove-legacy-global) are global/machine-level — none of the three
# targets or mutates any specific repository. Keep insertion order matching
# the intended `bindle --help` listing order.
_LIFECYCLE_COMMANDS: dict[str, tuple[str, str]] = {
    "init": (
        "Initialize or reconcile Bindle for this repository.",
        "Initialize or reconcile Bindle for the current repository. This "
        "is the explicit opt-in boundary: a repository becomes "
        "Bindle-managed by running `bindle init` in it. Intended to be "
        "safe to run repeatedly as more integrations are added later. "
        "Repository-scoped only: refuses to run (rather than silently "
        "migrating or removing it) if a recognized legacy machine-global "
        "Bindle guardrail install is still present; run "
        "`bindle migrate-legacy-global` first.",
    ),
    "remove": (
        "Remove Bindle-managed components from this repository.",
        "Remove Bindle-managed components, or Bindle management "
        "entirely, from the current repository. Repository-scoped only: "
        "refuses to run (rather than silently migrating or removing it) "
        "if a recognized legacy machine-global Bindle guardrail install "
        "is still present; run `bindle migrate-legacy-global` first.",
    ),
    "migrate-legacy-global": (
        "Remove a recognized legacy machine-global Bindle guardrail install.",
        "Explicitly migrate away a recognized pre-rework, machine-global "
        "Bindle guardrail install (Git core.hooksPath and/or the Claude "
        "Code PreToolUse guard), only for state this can positively prove "
        "is Bindle's own. Global/machine-level and intentionally "
        "separate from `bindle init`/`bindle remove`, which are "
        "repository-scoped and never perform this migration silently. "
        "Never touches an unrelated/foreign global value.",
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


def _installer_path() -> Path:
    # Package-owned runtime asset (src/bindle/_bin/), included in every
    # wheel/sdist build and resolved through the installed package's own
    # location — not relative to cwd or a Bindle source checkout, so this
    # works identically for `uv run bindle` (editable/dev) and a normally
    # installed `bindle` release alike.
    return Path(str(importlib.resources.files("bindle") / "_bin" / "install-guardrails.sh"))


def _installer_env() -> dict[str, str]:
    # The installer's Claude-layer settings.local.json merge needs generic
    # JSON structural operations (settings_json.py, package-owned) but no
    # external tool: BINDLE_PYTHON tells it to reuse the exact interpreter
    # already running `bindle` itself, so this works identically whether
    # `bindle` is invoked via `uv run` or from a normally installed
    # package, with no new runtime prerequisite beyond Python itself.
    return {**os.environ, "BINDLE_PYTHON": sys.executable}


def _run_guardrail_installer(command: str, mode: str) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle {command}: {exc}", file=sys.stderr)
        return 1

    installer = _installer_path()
    if not installer.is_file():
        print(
            f"bindle {command}: guardrail installer not found at {installer} "
            "(this Bindle installation is missing a required runtime asset)",
            file=sys.stderr,
        )
        return 1

    result = subprocess.run(
        ["bash", str(installer), mode, "--repo", info.worktree_root],
        env=_installer_env(),
    )
    return result.returncode


def _cmd_init(args: argparse.Namespace) -> int:
    return _run_guardrail_installer("init", "--apply")


def _cmd_remove(args: argparse.Namespace) -> int:
    return _run_guardrail_installer("remove", "--uninstall")


def _cmd_migrate_legacy_global(args: argparse.Namespace) -> int:
    # Global/machine-level, unlike _run_guardrail_installer above: no
    # current-repository resolution, and no --repo argument — this exposes
    # install-guardrails.sh --remove-legacy-global exactly as-is, as the
    # smallest CLI surface over the runtime asset `bindle init`/`bindle
    # remove` already resolve via _installer_path(), for a normally
    # installed package where invoking the packaged script directly isn't
    # ergonomic.
    installer = _installer_path()
    if not installer.is_file():
        print(
            "bindle migrate-legacy-global: guardrail installer not found "
            f"at {installer} (this Bindle installation is missing a "
            "required runtime asset)",
            file=sys.stderr,
        )
        return 1

    result = subprocess.run(
        ["bash", str(installer), "--remove-legacy-global"],
        env=_installer_env(),
    )
    return result.returncode


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

    if args.command == "init":
        return _cmd_init(args)

    if args.command == "remove":
        return _cmd_remove(args)

    if args.command == "migrate-legacy-global":
        return _cmd_migrate_legacy_global(args)

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
