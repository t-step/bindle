"""bindle CLI entrypoint.

Establishes the command surface for Bindle's repository and global
lifecycle commands (see AGENTS.md and docs/SCOPE.md). `--version`,
`repo info`, `branch`, `init`, `remove`, `status`, and `migrate-legacy-global`
have real behavior today; `init`/`remove` cover only the guardrail layer
(Git hook dispatch + Claude Code PreToolUse guard) via
install-guardrails.sh — they do not yet manage any other Bindle-owned
component. `status` additionally reports read-only Projectmem adoption
state (see projectmem.py) alongside the guardrail layer, without installing,
repairing, or otherwise mutating either. `branch` creates an isolated
worktree and feature branch off freshly-fetched origin/main (AGENTS.md,
"Development isolation"). `list`, `update`, `upgrade`, and `doctor` remain
interface-only placeholders until their underlying components are
implemented in a later slice.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys

from . import __version__
from .guardrails import (
    GuardrailDetectionError,
    detect_claude_guardrails,
    detect_git_guardrails,
    installer_env,
    installer_path,
)
from .projectmem import detect_projectmem
from .repo import NotAGitRepositoryError, get_repo_info

# Lifecycle commands with an established name and short/long --help text.
# `init`, `remove`, `status`, and `migrate-legacy-global` have real behavior
# (see _cmd_init/_cmd_remove/_cmd_status/_cmd_migrate_legacy_global below);
# the rest remain interface-only placeholders (_cmd_not_implemented).
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


# Aliases (not re-declarations) of guardrails.py's installer_path/
# installer_env — this module's own single point of contact with the
# installer, so `_run_guardrail_installer`/`_cmd_migrate_legacy_global`
# below and existing tests that patch `bindle.cli._installer_path` keep
# working unchanged, while detect_git_guardrails/detect_claude_guardrails
# (guardrails.py) share the exact same underlying functions rather than a
# separately-drifting copy.
_installer_path = installer_path
_installer_env = installer_env


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


def _cmd_status(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle status: {exc}", file=sys.stderr)
        return 1

    try:
        git_status = detect_git_guardrails(info)
        claude_status = detect_claude_guardrails(info)
    except GuardrailDetectionError as exc:
        print(f"bindle status: {exc}", file=sys.stderr)
        return 1

    projectmem_status = detect_projectmem(info)

    print(f"Repository: {os.path.basename(info.repo_root)}")
    print("Guardrails")
    print(f"  {'Git':<10}{git_status}")
    print(f"  {'Claude':<10}{claude_status}")
    print(f"{'Projectmem':<10}  {projectmem_status}")
    return 0


# The branch this repository's routine work always branches from (see
# AGENTS.md, "Development isolation": "Start new work from an up-to-date
# main.").
_BRANCH_BASE = "main"


def _cmd_branch(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle branch: {exc}", file=sys.stderr)
        return 1

    name = args.name
    if not name.strip() or name != name.strip():
        print("bindle branch: branch name must not be empty or contain leading/trailing whitespace", file=sys.stderr)
        return 1

    exists = subprocess.run(
        ["git", "-C", info.repo_root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
        capture_output=True,
        text=True,
    )
    if exists.returncode == 0:
        print(f"bindle branch: branch '{name}' already exists", file=sys.stderr)
        return 1

    # Fetch the base branch explicitly rather than trusting the local
    # tracking branch — a stale local `main` is exactly how a prior branch
    # in this repo (`feat/local-orchestration`) ended up forked before a
    # policy change had landed. Refuse rather than silently branching off
    # whatever happens to be on disk if the fetch itself fails.
    fetch = subprocess.run(
        ["git", "-C", info.repo_root, "fetch", "origin", _BRANCH_BASE],
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        print(
            f"bindle branch: failed to fetch origin/{_BRANCH_BASE} — refusing to branch off "
            f"potentially stale history:\n{fetch.stderr.strip()}",
            file=sys.stderr,
        )
        return 1

    parent_dir = os.path.dirname(info.repo_root)
    repo_name = os.path.basename(info.repo_root)
    slug = name.replace("/", "-")
    target = os.path.join(parent_dir, f"{repo_name}-{slug}")

    if os.path.exists(target):
        print(f"bindle branch: target worktree path already exists: {target}", file=sys.stderr)
        return 1

    add = subprocess.run(
        [
            "git",
            "-C",
            info.repo_root,
            "worktree",
            "add",
            "-b",
            name,
            target,
            f"origin/{_BRANCH_BASE}",
        ],
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        print(f"bindle branch: {add.stderr.strip()}", file=sys.stderr)
        return 1

    print(target)
    return 0


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

    branch_parser = subparsers.add_parser(
        "branch",
        help="Create a new worktree and branch off up-to-date origin/main.",
        description=(
            "Create an isolated Git worktree and feature branch for one product "
            f"slice, branched directly off freshly-fetched origin/{_BRANCH_BASE} so "
            "it can never inherit local drift. Refuses to fall back to a stale "
            "local branch if the fetch fails, and refuses to reuse an existing "
            "branch name or worktree path. Prints the new worktree's absolute "
            "path on success."
        ),
    )
    branch_parser.add_argument("name", help="Name for the new branch")

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

    if args.command == "status":
        return _cmd_status(args)

    if args.command in _LIFECYCLE_COMMANDS:
        return _cmd_not_implemented(args.command)

    if args.command == "repo":
        if args.repo_command == "info":
            return _cmd_repo_info(args)
        parser.parse_args(["repo", "--help"])
        return 1

    if args.command == "branch":
        return _cmd_branch(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
