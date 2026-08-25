"""bindle CLI entrypoint.

Establishes the command surface for Bindle's repository and global
lifecycle commands (see AGENTS.md and docs/SCOPE.md). `--version`,
`repo info`, `branch`, `init`, `remove`, `status`, and `migrate-legacy-global`
have real behavior today. `init`/`remove` always cover the guardrail layer
(Git hook dispatch + Claude Code PreToolUse guard) via
install-guardrails.sh; `init --projectmem` additionally ensures Projectmem
is initialized for the repository via the native `pjm` CLI (see
projectmem.py) — the explicit, opt-in provider-lifecycle seam this slice
adds, still no general Bindle-owned component/provider registry.
Projectmem storage is initialized worktree-local (`pjm init --no-hooks
...`); its Git hooks are then installed separately, against the
repository's shared Git common directory (`pjm hooks install`, `cwd`
resolved to the main checkout) rather than a linked worktree's own `.git`
(a file, not a directory there) — see D033. Known Projectmem preconditions
(partial/conflicting `.projectmem/`, a missing `pjm` executable) are
checked before guardrails mutate anything, so a refusal on the Projectmem
side never leaves guardrails newly installed/reconciled behind it.
`remove` never touches Projectmem's own state, since Bindle has no
ownership record proving it may destroy it.
`status` additionally reports read-only Projectmem adoption state
alongside the guardrail layer, without installing, repairing, or
otherwise mutating either. `branch` creates an
isolated worktree and feature branch off freshly-fetched origin/main
(AGENTS.md, "Development isolation"). `list`, `update`, `upgrade`, and
`doctor` remain interface-only placeholders until their underlying
components are implemented in a later slice.
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
from .projectmem import (
    PJM_HOOKS_INSTALL_ARGS,
    PJM_INIT_ARGS,
    detect_projectmem,
    pjm_executable,
)
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
        "`bindle migrate-legacy-global` first. Add --projectmem to also "
        "ensure Projectmem is initialized for this repository via its "
        "native `pjm init` CLI — optional, never implied by a bare "
        "`bindle init`.",
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


def _projectmem_init_preflight(info) -> tuple[int | None, str, str | None]:
    # Read-only precondition check for `bindle init --projectmem`, run
    # BEFORE any mutation (guardrails or Projectmem) — a known Projectmem
    # precondition failure must never leave guardrails newly
    # installed/reconciled behind it. Detection is the exact same read-only
    # detect_projectmem() `bindle status` already uses; detection does not
    # imply ownership, so "installed" is a no-op success regardless of
    # whether Bindle created it, and needs no `pjm` executable at all.
    #
    # Never lets native `pjm init` run against "partial"/"conflict" state:
    # verified empirically this session that it does NOT refuse on either
    # (a partial `.projectmem/` is silently completed; a conflicting file
    # crashes with an unhandled traceback) — this check is what makes
    # Bindle refuse cleanly instead.
    #
    # Returns (refusal_exit_code, state, pjm_path). refusal_exit_code is
    # None when the precondition passed (proceed to guardrails); pjm_path
    # is the resolved `pjm` binary to reuse for the later init call when
    # state is "not-installed", else None (not needed for "installed").
    mem_dir = os.path.join(info.worktree_root, ".projectmem")
    state = detect_projectmem(info)

    if state == "partial":
        print(
            f"bindle init --projectmem: {mem_dir} exists but is missing "
            "config.toml — a recognizable but incomplete Projectmem state. "
            "Refusing to finish initialization over ambiguous state "
            "(native `pjm init` would silently complete it, which could "
            "paper over a failed prior init or an unrelated directory of "
            "the same name). Resolve it yourself, then retry — guardrails "
            "were not touched.",
            file=sys.stderr,
        )
        return 1, state, None

    if state == "conflict":
        print(
            f"bindle init --projectmem: {mem_dir} exists but is not a "
            "directory Projectmem can use (a file, or a dangling symlink). "
            "Refusing to replace it. Remove or rename it yourself, then "
            "retry — guardrails were not touched.",
            file=sys.stderr,
        )
        return 1, state, None

    if state == "installed":
        return None, state, None

    # not-installed: a `pjm` executable is required before anything else
    # in this invocation mutates. Never falls back to constructing
    # .projectmem/ state manually — see projectmem.py.
    pjm = pjm_executable()
    if pjm is None:
        print(
            "bindle init --projectmem: the `pjm` executable was not found "
            "on PATH. Install Projectmem yourself (e.g. `uv tool install "
            "projectmem`) and retry — Bindle does not fall back to "
            "constructing .projectmem/ state manually, and guardrails were "
            "not touched.",
            file=sys.stderr,
        )
        return 1, state, None

    return None, state, pjm


def _cmd_init(args: argparse.Namespace) -> int:
    if not args.projectmem:
        return _run_guardrail_installer("init", "--apply")

    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle init: {exc}", file=sys.stderr)
        return 1

    refusal, state, pjm = _projectmem_init_preflight(info)
    if refusal is not None:
        return refusal

    # Preflight passed — now mutate. Guardrails first (unchanged bare
    # `bindle init` behavior), Projectmem second. These are two
    # independent operations, not a transaction: a guardrail failure here
    # simply means Projectmem is never attempted this invocation (nothing
    # was mutated on the Projectmem side by the preflight check above);
    # re-running `bindle init --projectmem` after fixing the guardrail
    # problem picks Projectmem up on its own next run.
    guardrail_code = _run_guardrail_installer("init", "--apply")
    if guardrail_code != 0:
        return guardrail_code

    if state == "installed":
        # Accepting a healthy existing installation, not repairing one:
        # this guarantees correct hook placement when Bindle itself
        # initializes Projectmem, but it does not audit or repair the hook
        # state of a pre-existing Projectmem installation (e.g. one set up
        # by hand from a linked worktree before this fix existed). Doing
        # that would turn `init --projectmem` into a general repair
        # mechanism, which is out of scope for this slice.
        print("Projectmem: already installed — left unchanged.")
        return 0

    # not-installed, guardrails now applied: initialize storage through
    # Projectmem's own native CLI with the narrowed flag set (see
    # PJM_INIT_ARGS) — --no-hooks included, since Projectmem's own hook
    # installer resolves `<cwd>/.git/hooks` directly and would silently
    # no-op against a linked worktree's `.git` (a file, not that
    # directory). An unexpected runtime/filesystem failure here is
    # reported as-is — guardrails already succeeded and remain installed;
    # `.projectmem/` (whatever `pjm init` left behind) is never deleted to
    # simulate an all-or-nothing rollback, since it is provider-owned
    # state, not disposable staging.
    init_result = subprocess.run([pjm, *PJM_INIT_ARGS], cwd=info.worktree_root)
    if init_result.returncode != 0:
        print(
            f"bindle init --projectmem: `pjm init` failed (exit "
            f"{init_result.returncode}).",
            file=sys.stderr,
        )
        return init_result.returncode

    # Storage is worktree-local; Projectmem's Git hooks are
    # repository/common-Git state — install them separately, against the
    # repository's main checkout (info.repo_root), which always has a
    # real `.git/hooks` directory regardless of which linked worktree this
    # command was run from. Still Projectmem's own native installer, never
    # Bindle-authored hook content. A failure here is reported as-is and
    # never rolls back the Projectmem storage or guardrails that already
    # succeeded — this stays a sequence of independently owned operations,
    # not a transaction.
    hooks_result = subprocess.run([pjm, *PJM_HOOKS_INSTALL_ARGS], cwd=info.repo_root)
    if hooks_result.returncode != 0:
        print(
            "bindle init --projectmem: Projectmem storage was initialized, "
            f"but `pjm hooks install` failed (exit {hooks_result.returncode}) "
            "— .projectmem/ and guardrails remain as they are.",
            file=sys.stderr,
        )
    return hooks_result.returncode


def _cmd_remove(args: argparse.Namespace) -> int:
    code = _run_guardrail_installer("remove", "--uninstall")
    if code == 0:
        # Projectmem is provider-owned working memory, not Bindle's to
        # destroy: `bindle remove` never touches `.projectmem/`, regardless
        # of whether Bindle created it. Report its survival when relevant
        # (nothing to say when it was never installed in the first place).
        try:
            info = get_repo_info()
            if detect_projectmem(info) == "installed":
                print("Projectmem: left untouched (not removed by `bindle remove`).")
        except NotAGitRepositoryError:
            pass
    return code


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
        command_parser = subparsers.add_parser(name, help=help_text, description=description)
        if name == "init":
            command_parser.add_argument(
                "--projectmem",
                action="store_true",
                help="Also ensure Projectmem is initialized for this repository.",
            )

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
