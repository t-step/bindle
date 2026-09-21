"""Read-only Projectmem adoption detection for the current repository.

Projectmem (D022) has no non-mutating `--status`/`--check` probe comparable to
install-guardrails.sh's `--status` (guardrails.py): its subcommands (`show`,
`brief`, ...) need an already-initialized project and are content views, not
health checks, and `pjm` may not be on PATH wherever `bindle status` runs. So
detection never shells out. It checks the marker Projectmem's own source uses
to recognize an initialized project (installed
`projectmem.storage._is_project_mem_dir`):
`candidate.is_dir() and (candidate / CONFIG_FILE).exists()`, i.e. `.projectmem/`
is a directory and `.projectmem/config.toml` exists. That is plain
`Path.exists()` (follows symlinks, accepts any entry type; contents are never
parsed), matched exactly including its permissiveness rather than tightening
incidental layout. Only path existence and type are read, the same coupling
`git status` has to `.git`.

Detection is scoped to the current worktree root (repo_info.worktree_root), not
a directory walk-up. Projectmem's CLI walks up from cwd like Git does for
`.git/`, but a linked worktree created by `bindle branch` does not share another
worktree's `.projectmem/` state, so walking up risks reporting "installed" from
an unrelated ancestor's project; this mirrors
detect_git_guardrails/detect_claude_guardrails. Whether `.projectmem/` is
tracked, partly tracked, or gitignored (as in this repository) is repository
policy (Projectmem 0.2.0 defaults to committing distilled team knowledge) and
does not change the scope.

Four states, not the five-state guardrail vocabulary:
  installed      `.projectmem/` is a directory and `.projectmem/config.toml`
                 exists (any entry type): Projectmem's own initialized-project
                 predicate, matched exactly.
  not-installed  no `.projectmem` path entry exists at the worktree root
                 (checked with lexists; see conflict).
  partial        `.projectmem` is a directory but `config.toml` is missing: a
                 failed/incomplete `pjm init` or an unrelated empty directory
                 of the same name, which the filesystem cannot distinguish, so
                 both surface as "partial".
  conflict       a `.projectmem` path entry exists but cannot serve as the
                 directory: a plain file, or a dangling symlink. `pjm init`'s
                 `project_dir.mkdir(exist_ok=True)` would fail against it, so it
                 is not a clean uninitialized state. Detected via
                 `os.path.lexists()` plus `os.path.isdir()` (False for a file or
                 dangling symlink); never followed or repaired.

No "invalid" state: Projectmem never validates `config.toml`'s contents (no TOML
parsing in its initialization or discovery), so nothing objective distinguishes
"malformed" from "incomplete"; an empty or corrupt config.toml still satisfies
its recognition predicate.
"""

from __future__ import annotations

import os
import shutil

from .repo import RepoInfo

ProjectmemState = str

_VALID_STATES = frozenset({"installed", "not-installed", "partial", "conflict"})

_DIR_NAME = ".projectmem"
_CONFIG_FILE = "config.toml"

# Installed separately (`uv tool install projectmem`); not a Bindle dependency.
_PJM_BINARY = "pjm"

# Flags for Bindle-initiated `pjm init` (never a pre-existing "installed"
# repo; see cli.py): repo-local working-memory state only, nothing outward.
#   --no-hooks         linked worktrees have a `.git` file, so pjm's
#                      `<cwd>/.git/hooks` install would silently no-op
#   --no-global        don't opt into machine-wide ~/.projectmem/global
#   --no-watch         no silent daemon (`pjm watch` stays explicit)
#   --no-backfill      no unexpected ingest of existing Git history
#   --no-claude-md     provider-neutral: no Claude prose appended to CLAUDE.md
#   --no-mcp-config    MCP registration is a separate concern
#   --no-structure     no code-structure analysis
#   --no-stack-detect  no stack/manifest analysis
PJM_INIT_ARGS = (
    "init",
    "--no-hooks",
    "--no-global",
    "--no-watch",
    "--no-backfill",
    "--no-claude-md",
    "--no-mcp-config",
    "--no-structure",
    "--no-stack-detect",
)

# Run against repo_root, never a linked worktree_root: pjm 0.2.0 resolves
# `<cwd>/.git/hooks` directly and only repo_root has a real `.git/`.
# Storage stays worktree-local; Bindle never edits Projectmem's hook files.
PJM_HOOKS_INSTALL_ARGS = ("hooks", "install")


def pjm_executable() -> str | None:
    """Absolute path to the `pjm` CLI on PATH, or None if it isn't installed.

    Bindle never constructs `.projectmem/` state itself; this only locates the
    CLI to invoke.
    """
    return shutil.which(_PJM_BINARY)


def detect_projectmem(repo_info: RepoInfo) -> ProjectmemState:
    """Read-only: Projectmem's adoption state for repo_info's worktree root."""
    path = os.path.join(repo_info.worktree_root, _DIR_NAME)

    # lexists, not exists: a dangling symlink still occupies the path.
    if not os.path.lexists(path):
        return "not-installed"

    # isdir is False for a file or dangling symlink: both are "conflict".
    if not os.path.isdir(path):
        return "conflict"

    # exists, not isfile: Projectmem's own predicate accepts any entry type.
    if os.path.exists(os.path.join(path, _CONFIG_FILE)):
        return "installed"

    return "partial"
