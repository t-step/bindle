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
`init --qmd` additionally ensures a project-local QMD retrieval index
exists for the repository's own durable Markdown, via the native `qmd`
CLI (see qmd.py, and docs/DECISIONS.md D036) — a fourth provider-lifecycle
seam, shaped like Projectmem's (native CLI only, filesystem-native
detection) rather than the skill kits'. `--projectmem` and `--qmd` compose
freely: every requested layer's read-only preflight runs first, guardrails
mutate only once every requested preflight has passed, and each opt-in's
own mutation runs after that in a fixed order (Projectmem, then QMD) —
never a transaction, each step's failure is reported as-is without rolling
back an earlier step that already succeeded. `remove` never touches
`.qmd/` either, for the same "no ownership record proving it may destroy
this" reason as Projectmem, even though the QMD index is itself derived,
rebuildable state — see qmd.py.
`status` additionally reports read-only Projectmem and QMD adoption state
alongside the guardrail layer, without installing, repairing, or
otherwise mutating either. `branch` creates an
isolated worktree and feature branch off freshly-fetched origin/main
(AGENTS.md, "Development isolation"). `skills list`/`status`/`add`/
`remove` manage skill kits — named collections of agent-facing skills
Bindle makes available to Claude Code and Codex through each harness's
own native mechanism (see the `skills` package and docs/DECISIONS.md
D035) — a third, differently-shaped provider-lifecycle seam alongside
guardrails and Projectmem. `list` (the global repository inventory,
distinct from `skills list`), `update`, `upgrade`, and `doctor` remain
interface-only placeholders until their underlying components are
implemented in a later slice. `work load-speckit`/`publish`/`claim`/
`release`/`done` (specs/003-symphony-task-integration) load a settled
Spec Kit feature's tasks.md into the durable work ledger, regenerate the
published, versioned, read-only Symphony-facing SQLite projection, and
claim/release/complete a task through the ledger's own atomic
primitives — see speckit_loader.py and symphony_projection.py.
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
from . import milestone_review
from . import qmd as qmd_mod
from .repo import NotAGitRepositoryError, get_repo_info
from .skills import CATALOG, UnknownKitError, add_desired_kit, read_desired_kits, remove_desired_kit, require_kit
from .skills.config import SkillsConfigError
from .speckit_loader import TasksFileError, load_feature
from . import symphony_projection
from .work_ledger import WorkLedger

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
        "native `pjm init` CLI, or --qmd to also ensure a QMD retrieval "
        "index exists for this repository's durable Markdown via the "
        "native `qmd` CLI — both optional, never implied by a bare "
        "`bindle init`, and safe to combine.",
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


def _apply_projectmem(info, state: str, pjm: str | None) -> int:
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


def _qmd_init_preflight(info) -> tuple[int | None, str]:
    # Read-only precondition check for `bindle init --qmd`, mirroring
    # _projectmem_init_preflight's shape: run BEFORE any mutation, so a
    # QMD-side refusal never leaves guardrails (or Projectmem, if also
    # requested) newly installed/reconciled behind it.
    state = qmd_mod.detect_qmd(info)

    if state == "unavailable":
        print(
            "bindle init --qmd: the `qmd` executable was not found on "
            "PATH. Install QMD yourself (e.g. `npm install -g @tobilu/qmd` "
            "or `bun install -g @tobilu/qmd`) and retry — Bindle does not "
            "vendor or auto-install QMD, and guardrails were not touched.",
            file=sys.stderr,
        )
        return 1, state

    if state == "conflict":
        qmd_dir = os.path.join(info.worktree_root, ".qmd")
        print(
            f"bindle init --qmd: {qmd_dir} exists but does not look like "
            "a Bindle-owned QMD index for this repository — either the "
            "path is occupied by something QMD can't use, its index.yml "
            "doesn't match the expected shape, or its "
            "'repo' collection (if any) points somewhere other than this "
            "worktree. Refusing to touch it. Resolve it yourself, then "
            "retry — guardrails were not touched.",
            file=sys.stderr,
        )
        return 1, state

    return None, state


def _apply_qmd(info, state: str) -> int:
    if state == "ready":
        # Retroactively covers a repository that already had `.qmd/` from
        # before this ignore-rule addition existed — re-running `bindle
        # init --qmd` converges it, not just fresh initialization below.
        qmd_mod.ensure_gitignored(info)
        print("QMD: already initialized — left unchanged.")
        return 0

    # not-initialized, guardrails now applied: `qmd init` MUST run before
    # `qmd collection add` on every path, unconditionally — verified
    # empirically (see qmd.py's module docstring) that `collection add`
    # run without a prior project-local `qmd init` in the same directory
    # silently falls back to the machine-global default index instead of
    # refusing. Running `qmd init` first is what keeps this integration
    # entirely inside this worktree's own `.qmd/`, never the user's global
    # QMD state. `qmd init` is itself idempotent (verified empirically:
    # re-running it against an existing `.qmd/` with collections already
    # registered leaves them untouched), so this is safe to run even when
    # `.qmd/` already exists with unrelated collections in it (the
    # `not-initialized` state also covers "index exists, but our
    # collection doesn't yet").
    qmd_bin = qmd_mod.qmd_executable()
    qmd_env = qmd_mod.subprocess_env(info.worktree_root)
    init_result = subprocess.run(
        [qmd_bin, *qmd_mod.QMD_INIT_ARGS], cwd=info.worktree_root, env=qmd_env
    )
    if init_result.returncode != 0:
        print(
            f"bindle init --qmd: `qmd init` failed (exit "
            f"{init_result.returncode}).",
            file=sys.stderr,
        )
        return init_result.returncode

    # Registers and immediately indexes this repository's own durable
    # Markdown (see qmd.py's COLLECTION_NAME/COLLECTION_MASK) via QMD's
    # own native command — Bindle never writes `.qmd/index.yml` itself.
    # Any other collection already present in `.qmd/index.yml` (from the
    # user, or another tool) is untouched by this call; `collection add`
    # only ever creates the one collection it's given.
    add_result = subprocess.run(
        [qmd_bin, *qmd_mod.collection_add_args(info.worktree_root)],
        cwd=info.worktree_root,
        env=qmd_env,
    )
    if add_result.returncode != 0:
        print(
            "bindle init --qmd: the project-local index was created, but "
            f"`qmd collection add` failed (exit {add_result.returncode}) "
            "— .qmd/ and guardrails remain as they are.",
            file=sys.stderr,
        )
        return add_result.returncode

    qmd_mod.ensure_gitignored(info)
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    if not args.projectmem and not args.qmd:
        return _run_guardrail_installer("init", "--apply")

    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle init: {exc}", file=sys.stderr)
        return 1

    # Every requested layer's read-only preflight runs before ANY mutation
    # — a refusal on one opt-in must never leave guardrails, or an
    # already-preflighted other opt-in, newly mutated behind it (mirrors
    # D032's "all requested layers preflight together" precedent, now
    # generalized past just the two guardrail halves).
    projectmem_state, projectmem_pjm = None, None
    if args.projectmem:
        refusal, projectmem_state, projectmem_pjm = _projectmem_init_preflight(info)
        if refusal is not None:
            return refusal

    qmd_state = None
    if args.qmd:
        refusal, qmd_state = _qmd_init_preflight(info)
        if refusal is not None:
            return refusal

    # Preflight passed for every requested layer — now mutate. Guardrails
    # first (unchanged bare `bindle init` behavior), then each requested
    # opt-in in a fixed order (Projectmem, then QMD). None of this is a
    # transaction: a failure at any step is reported as-is and never rolls
    # back a step that already succeeded — re-running `bindle init` with
    # the same flags after fixing the problem picks up wherever it left
    # off (both `_apply_projectmem` and `_apply_qmd` are themselves
    # idempotent on their own "already done" state).
    guardrail_code = _run_guardrail_installer("init", "--apply")
    if guardrail_code != 0:
        return guardrail_code

    if args.projectmem:
        code = _apply_projectmem(info, projectmem_state, projectmem_pjm)
        if code != 0:
            return code

    if args.qmd:
        code = _apply_qmd(info, qmd_state)
        if code != 0:
            return code

    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    code = _run_guardrail_installer("remove", "--uninstall")
    if code == 0:
        # Projectmem is provider-owned working memory, not Bindle's to
        # destroy: `bindle remove` never touches `.projectmem/`, regardless
        # of whether Bindle created it. Report its survival when relevant
        # (nothing to say when it was never installed in the first place).
        #
        # QMD's index is itself derived/rebuildable state, not durable
        # knowledge — but Bindle still holds no ownership record proving
        # this specific collection is safe to delete unattended (a user
        # could have hand-edited `.qmd/index.yml`, or added other
        # collections alongside it), so `bindle remove` leaves it alone
        # too, for the same conservative reason as Projectmem. See qmd.py.
        try:
            info = get_repo_info()
            if detect_projectmem(info) == "installed":
                print("Projectmem: left untouched (not removed by `bindle remove`).")
            if qmd_mod.detect_qmd(info) == "ready":
                print("QMD: left untouched (not removed by `bindle remove`).")
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
    qmd_status = qmd_mod.detect_qmd(info)

    print(f"Repository: {os.path.basename(info.repo_root)}")
    print("Guardrails")
    print(f"  {'Git':<10}{git_status}")
    print(f"  {'Claude':<10}{claude_status}")
    print(f"{'Projectmem':<10}  {projectmem_status}")
    print(f"{'QMD':<10}  {qmd_status}")
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


def _cmd_skills_list(args: argparse.Namespace) -> int:
    print("Skill kits")
    for kit_id, kit_info in CATALOG.items():
        print(f"  {kit_id:<22}{kit_info.source} — {kit_info.description}")
    return 0


def _cmd_skills_status(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle skills status: {exc}", file=sys.stderr)
        return 1

    try:
        desired = read_desired_kits(info.worktree_root)
    except SkillsConfigError as exc:
        print(f"bindle skills status: {exc}", file=sys.stderr)
        return 1

    for kit_id, kit_info in CATALOG.items():
        kit_status = kit_info.module.status(info)
        print(kit_id)
        print(f"  {'desired':<10}{'yes' if kit_id in desired else 'no'}")
        print(f"  {'Claude':<10}{kit_status.claude}")
        print(f"  {'Codex':<10}{kit_status.codex}")
    return 0


def _cmd_skills_add(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle skills add: {exc}", file=sys.stderr)
        return 1

    try:
        kit_info = require_kit(args.kit)
    except UnknownKitError as exc:
        print(f"bindle skills add: {exc}", file=sys.stderr)
        return 1

    try:
        changed = add_desired_kit(info.worktree_root, kit_info.kit_id)
    except SkillsConfigError as exc:
        print(f"bindle skills add: {exc}", file=sys.stderr)
        return 1

    print(kit_info.kit_id)
    print(f"  {'desired':<10}{'added' if changed else 'already desired'}")

    outcome = kit_info.module.add(info)
    for line in outcome.lines:
        print(f"  {line}")

    return 0 if outcome.ok else 1


def _cmd_work_load_speckit(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle work load-speckit: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    try:
        result = load_feature(
            ledger, args.feature_dir, source_promoted_by=args.promoted_by
        )
    except TasksFileError as exc:
        print(f"bindle work load-speckit: {exc}", file=sys.stderr)
        return 1

    print(f"created: {len(result.created)}")
    for item_id in result.created:
        print(f"  {item_id}")
    print(f"resynced: {len(result.resynced)}")
    for item_id in result.resynced:
        print(f"  {item_id}")

    # Skipped lines and unresolved dependencies are reported to the caller
    # (spec.md FR-010/FR-011) rather than silently discarded — surfaced as
    # a non-zero exit so they're not missed in a script, even though every
    # other well-formed task line in the same file still loaded normally.
    ok = not result.skipped and not result.unresolved_dependencies
    if result.skipped:
        print(f"bindle work load-speckit: {len(result.skipped)} line(s) skipped:", file=sys.stderr)
        for skipped in result.skipped:
            print(f"  line {skipped.line_number}: {skipped.reason}", file=sys.stderr)
    if result.unresolved_dependencies:
        print(
            f"bindle work load-speckit: {len(result.unresolved_dependencies)} "
            "unresolved dependency reference(s):",
            file=sys.stderr,
        )
        for dep in result.unresolved_dependencies:
            print(f"  {dep.task_id} depends on missing {dep.depends_on}", file=sys.stderr)
    return 0 if ok else 1


def _cmd_work_publish(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle work publish: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    path = symphony_projection.publish(ledger)
    print(path)
    return 0


def _cmd_work_claim(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle work claim: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    result = symphony_projection.claim_task(
        ledger, args.id, args.owner, worktree_path=args.worktree, branch=args.branch
    )
    if not result.ok:
        print(f"bindle work claim: {result.reason}", file=sys.stderr)
        return 1
    return 0


def _cmd_work_release(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle work release: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    result = symphony_projection.release_task(ledger, args.id, args.owner)
    if not result.ok:
        print(f"bindle work release: {result.reason}", file=sys.stderr)
        return 1
    return 0


def _cmd_work_done(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle work done: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    result = symphony_projection.complete_task(ledger, args.id)
    if not result.ok:
        print(f"bindle work done: {result.reason}", file=sys.stderr)
        return 1
    return 0


def _cmd_skills_remove(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle skills remove: {exc}", file=sys.stderr)
        return 1

    try:
        kit_info = require_kit(args.kit)
    except UnknownKitError as exc:
        print(f"bindle skills remove: {exc}", file=sys.stderr)
        return 1

    outcome = kit_info.module.remove(info)

    try:
        changed = remove_desired_kit(info.worktree_root, kit_info.kit_id)
    except SkillsConfigError as exc:
        print(f"bindle skills remove: {exc}", file=sys.stderr)
        return 1

    print(kit_info.kit_id)
    for line in outcome.lines:
        print(f"  {line}")
    print(f"  {'desired':<10}{'removed' if changed else 'already not desired'}")

    return 0 if outcome.ok else 1


def _format_not_ready_reason(reasons: list[str]) -> str:
    # milestone_review.MilestoneReviewView.not_ready_reason is a flat
    # subset of {"blocked", "no_children"} plus one entry per outstanding
    # child id — render the two fixed tokens as-is and group every
    # remaining entry (a child id) under one "outstanding: ..." clause.
    parts = []
    if "blocked" in reasons:
        parts.append("blocked")
    if "no_children" in reasons:
        parts.append("no_children")
    outstanding = [r for r in reasons if r not in ("blocked", "no_children")]
    if outstanding:
        parts.append("outstanding: " + ", ".join(outstanding))
    return ", ".join(parts)


def _cmd_milestone_review(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle milestone review: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    result = milestone_review.review_milestone(ledger, args.id)
    if not result.ok:
        print(f"bindle milestone review: {result.reason}", file=sys.stderr)
        return 1

    view = result.view
    readiness = (
        "ready"
        if view.review_ready
        else f"not ready ({_format_not_ready_reason(view.not_ready_reason)})"
    )
    claim_suffix = f", claimed by {view.claim.owner}" if view.claim else ""
    print(f"milestone {view.id}: {view.status}, {readiness}{claim_suffix}")
    for child in view.children:
        evidence_str = (
            "none"
            if not child.evidence
            else "[" + ", ".join(f"{p.kind} {p.value}" for p in child.evidence) + "]"
        )
        blocked_str = "yes" if child.is_blocked else "no"
        print(f"  {child.id}  {child.status}  evidence: {evidence_str}  blocked: {blocked_str}")
    return 0


def _cmd_milestone_list(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle milestone list: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    entries = milestone_review.list_milestones(ledger)
    if args.status is not None:
        entries = [e for e in entries if e.status == args.status]
    if args.ready_only:
        entries = [e for e in entries if e.review_ready]

    for entry in entries:
        print(f"{entry.id}  {entry.status}  {'ready' if entry.review_ready else 'not ready'}")
    return 0


def _cmd_milestone_enter_review(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle milestone enter-review: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    result = milestone_review.enter_review(ledger, args.id)
    if not result.ok:
        print(f"bindle milestone enter-review: {result.reason}", file=sys.stderr)
        return 1
    return 0


def _cmd_milestone_claim(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle milestone claim: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    result = milestone_review.claim_milestone(
        ledger, args.id, args.owner, worktree_path=args.worktree, branch=args.branch
    )
    if not result.ok:
        print(f"bindle milestone claim: {result.reason}", file=sys.stderr)
        return 1
    return 0


def _cmd_milestone_release(args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle milestone release: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    result = milestone_review.release_milestone(ledger, args.id, args.owner)
    if not result.ok:
        print(f"bindle milestone release: {result.reason}", file=sys.stderr)
        return 1
    return 0


def _cmd_milestone_accept(args: argparse.Namespace) -> int:
    return _cmd_milestone_decide("accept", milestone_review.accept, args)


def _cmd_milestone_decline(args: argparse.Namespace) -> int:
    return _cmd_milestone_decide("decline", milestone_review.decline, args)


def _cmd_milestone_decide(verb: str, fn, args: argparse.Namespace) -> int:
    try:
        info = get_repo_info()
    except NotAGitRepositoryError as exc:
        print(f"bindle milestone {verb}: {exc}", file=sys.stderr)
        return 1

    ledger = WorkLedger(info.repo_root)
    result = fn(ledger, args.id, evidence_locator=args.evidence, note=args.note)
    if not result.ok:
        print(f"bindle milestone {verb}: {result.reason}", file=sys.stderr)
        return 1

    past_tense = "accepted" if verb == "accept" else "declined"
    print(f"bindle milestone {verb}: {args.id} {past_tense}")
    if result.rationale_error is not None:
        print(
            f"bindle milestone {verb}: decision recorded, but the rationale "
            f"locator was not: {result.rationale_error}",
            file=sys.stderr,
        )
    return 0


class _BindleArgumentParser(argparse.ArgumentParser):
    """`ArgumentParser` with colorized help forced off.

    Python 3.14 added `color=True` as argparse's own default (a
    Bindle-wide styling policy this project has never opted into — CLI
    output is deterministic plain text everywhere else). `color` doesn't
    exist as a constructor argument or attribute on the Python versions
    this project also supports (>=3.11), so it can't be passed directly;
    `hasattr` guards the override so this is a no-op on 3.11-3.13.

    `add_subparsers()` defaults its `parser_class` kwarg to `type(self)`
    (confirmed against the installed argparse source, not assumed), so
    every subparser and nested subparser created from a parser built with
    this class also gets it — verified empirically in
    tests/test_cli.py::TestHelpOutputIsPlainText.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self, "color"):
            self.color = False


def build_parser() -> argparse.ArgumentParser:
    parser = _BindleArgumentParser(prog="bindle")
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
            command_parser.add_argument(
                "--qmd",
                action="store_true",
                help="Also ensure a project-local QMD retrieval index exists for this repository.",
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

    skills_parser = subparsers.add_parser(
        "skills",
        help="Manage repository skill kits.",
        description=(
            "Manage skill kits: named collections of agent-facing skills Bindle "
            "makes available to Claude Code and Codex through each harness's own "
            "native mechanism (docs/DECISIONS.md D035)."
        ),
    )
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command")
    skills_subparsers.add_parser("list", help="List known skill kits.")
    skills_subparsers.add_parser(
        "status", help="Show skill-kit adoption status for this repository."
    )
    skills_add_parser = skills_subparsers.add_parser(
        "add", help="Add a skill kit to this repository."
    )
    skills_add_parser.add_argument("kit", help="Kit ID (see `bindle skills list`)")
    skills_remove_parser = skills_subparsers.add_parser(
        "remove", help="Remove a skill kit from this repository."
    )
    skills_remove_parser.add_argument("kit", help="Kit ID (see `bindle skills list`)")

    work_parser = subparsers.add_parser(
        "work",
        help="Load Spec Kit tasks, publish the Symphony projection, and claim/release/complete tasks.",
        description=(
            "Symphony Task Integration (specs/003-symphony-task-integration): load a "
            "settled Spec Kit feature's tasks.md into the durable work ledger, publish "
            "the versioned, read-only Symphony-facing projection, and claim/release/"
            "complete a task through the ledger's own atomic primitives."
        ),
    )
    work_subparsers = work_parser.add_subparsers(dest="work_command")

    load_speckit_parser = work_subparsers.add_parser(
        "load-speckit",
        help="Load one Spec Kit feature directory's tasks.md into the ledger.",
    )
    load_speckit_parser.add_argument(
        "feature_dir",
        help="Feature directory path relative to the repository root, e.g. specs/003-symphony-task-integration",
    )
    load_speckit_parser.add_argument(
        "--promoted-by",
        default=None,
        help="Identity recorded as source_promoted_by for newly created work items.",
    )

    work_subparsers.add_parser(
        "publish", help="Regenerate the published Symphony projection file."
    )

    claim_parser = work_subparsers.add_parser("claim", help="Claim a task.")
    claim_parser.add_argument("id", help="Work item id")
    claim_parser.add_argument("--owner", required=True, help="Claim owner identity")
    claim_parser.add_argument(
        "--worktree", default=None, help="Worktree path to record with the claim"
    )
    claim_parser.add_argument(
        "--branch", default=None, help="Branch name to record with the claim"
    )

    release_parser = work_subparsers.add_parser("release", help="Release a claim.")
    release_parser.add_argument("id", help="Work item id")
    release_parser.add_argument("--owner", required=True, help="Claim owner identity")

    done_parser = work_subparsers.add_parser("done", help="Mark a claimed task done.")
    done_parser.add_argument("id", help="Work item id")

    milestone_parser = subparsers.add_parser(
        "milestone",
        help="Review milestone readiness/evidence and record accept/decline decisions.",
        description=(
            "Milestone Review Surface (specs/004-milestone-review-surface): the "
            "human-facing counterpart to `bindle work` — a maintainer's CLI path to "
            "the milestone review lifecycle specs/002-milestone-task-work-items "
            "already implements in the ledger (review-readiness, enter-review, "
            "claim/release, accept/decline). Deliberately a separate command group "
            "from `bindle work`, not a namespace it nests under: this surface "
            "exposes no task mutation, and `bindle work` exposes no milestone "
            "mutation."
        ),
    )
    milestone_subparsers = milestone_parser.add_subparsers(dest="milestone_command")

    milestone_review_parser = milestone_subparsers.add_parser(
        "review", help="Show a milestone's status, review-readiness, and evidence."
    )
    milestone_review_parser.add_argument("id", help="Work item id")

    milestone_list_parser = milestone_subparsers.add_parser(
        "list", help="Enumerate milestone work items."
    )
    milestone_list_parser.add_argument(
        "--status",
        choices=["open", "review", "accepted", "superseded"],
        default=None,
        help="Only show milestones with this status.",
    )
    milestone_list_parser.add_argument(
        "--ready-only",
        action="store_true",
        help="Only show review-ready milestones.",
    )

    milestone_enter_review_parser = milestone_subparsers.add_parser(
        "enter-review", help="Move a review-ready milestone from open to review."
    )
    milestone_enter_review_parser.add_argument("id", help="Work item id")

    milestone_claim_parser = milestone_subparsers.add_parser(
        "claim", help="Claim a milestone."
    )
    milestone_claim_parser.add_argument("id", help="Work item id")
    milestone_claim_parser.add_argument(
        "--owner", required=True, help="Claim owner identity"
    )
    milestone_claim_parser.add_argument(
        "--worktree", default=None, help="Worktree path to record with the claim"
    )
    milestone_claim_parser.add_argument(
        "--branch", default=None, help="Branch name to record with the claim"
    )

    milestone_release_parser = milestone_subparsers.add_parser(
        "release", help="Release a claim on a milestone."
    )
    milestone_release_parser.add_argument("id", help="Work item id")
    milestone_release_parser.add_argument(
        "--owner", required=True, help="Claim owner identity"
    )

    def _add_decision_arguments(decision_parser: argparse.ArgumentParser) -> None:
        decision_parser.add_argument("id", help="Work item id")
        decision_parser.add_argument(
            "--evidence",
            default=None,
            help="Rationale-locator evidence pointer value, recorded against the milestone.",
        )
        decision_parser.add_argument(
            "--note",
            default=None,
            help="Optional note alongside --evidence (requires --evidence).",
        )
        # `--note` without `--evidence` is a usage error caught by argument
        # parsing (contracts/milestone-review-surface.md), not a manual
        # check inside the command handler — the parser reference is
        # stashed on the Namespace itself (set_defaults) so main()'s
        # dispatch can call this exact subparser's own .error() (argparse's
        # own mechanism: prints usage, exits 2) rather than the top-level
        # parser's.
        decision_parser.set_defaults(_decision_parser=decision_parser)

    milestone_accept_parser = milestone_subparsers.add_parser(
        "accept", help="Accept a milestone currently in review."
    )
    _add_decision_arguments(milestone_accept_parser)

    milestone_decline_parser = milestone_subparsers.add_parser(
        "decline", help="Decline a milestone currently in review, back to open."
    )
    _add_decision_arguments(milestone_decline_parser)

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

    if args.command == "skills":
        if args.skills_command == "list":
            return _cmd_skills_list(args)
        if args.skills_command == "status":
            return _cmd_skills_status(args)
        if args.skills_command == "add":
            return _cmd_skills_add(args)
        if args.skills_command == "remove":
            return _cmd_skills_remove(args)
        parser.parse_args(["skills", "--help"])
        return 1

    if args.command == "work":
        if args.work_command == "load-speckit":
            return _cmd_work_load_speckit(args)
        if args.work_command == "publish":
            return _cmd_work_publish(args)
        if args.work_command == "claim":
            return _cmd_work_claim(args)
        if args.work_command == "release":
            return _cmd_work_release(args)
        if args.work_command == "done":
            return _cmd_work_done(args)
        parser.parse_args(["work", "--help"])
        return 1

    if args.command == "milestone":
        if args.milestone_command == "review":
            return _cmd_milestone_review(args)
        if args.milestone_command == "list":
            return _cmd_milestone_list(args)
        if args.milestone_command == "enter-review":
            return _cmd_milestone_enter_review(args)
        if args.milestone_command == "claim":
            return _cmd_milestone_claim(args)
        if args.milestone_command == "release":
            return _cmd_milestone_release(args)
        if args.milestone_command in ("accept", "decline"):
            if args.note is not None and args.evidence is None:
                args._decision_parser.error("argument --note: not allowed without argument --evidence")
            if args.milestone_command == "accept":
                return _cmd_milestone_accept(args)
            return _cmd_milestone_decline(args)
        parser.parse_args(["milestone", "--help"])
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
