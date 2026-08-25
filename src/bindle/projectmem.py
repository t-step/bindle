"""Read-only Projectmem adoption detection for the current repository.

Projectmem (docs/DECISIONS.md D022) has no `--status`/`--check` subcommand
comparable to install-guardrails.sh's `--status` mode (guardrails.py), and
none of its existing subcommands (`show`, `brief`, ...) are a non-mutating
status probe: they require an already-initialized project and are content
views, not health checks. There is also no guarantee the `pjm` CLI is on
PATH wherever `bindle status` runs.

So detection here does not shell out to Projectmem at all. Instead it
checks for the exact marker Projectmem's own source uses to recognize an
initialized project directory: `.projectmem/` is a directory and
`.projectmem/config.toml` exists (see the installed
`projectmem.storage._is_project_mem_dir` predicate, verbatim:
`candidate.is_dir() and (candidate / CONFIG_FILE).exists()` — plain
existence, via `Path.exists()`, which follows symlinks and accepts any
entry type; Projectmem never parses that file's contents or requires it
to be a regular file). This mirrors Projectmem's own documented
recognition boundary exactly, including its permissiveness, rather than
reverse-engineering or tightening incidental file layout, and never reads
the contents of any Projectmem-owned file — only path existence and type,
the same grade of coupling `git status` has to the existence of `.git`.

Detection is scoped to the current worktree root only (repo_info
.worktree_root), not a directory walk-up. Projectmem's own CLI walks up
from cwd looking for `.projectmem/` (like Git does for `.git/`), but
Bindle reports Projectmem adoption for the resolved repository/worktree
itself, not whatever ancestor that walk-up might happen to discover.
Whether `.projectmem/` is tracked, partially tracked, or fully
gitignored is repository policy (Projectmem 0.2.0 defaults to committing
distilled team knowledge and ignoring only runtime/scratch files;
ignoring the whole directory, as this repository currently does, is an
optional choice) and does not change Bindle's status scope. A linked
worktree created by `bindle branch` does not automatically share another
worktree's `.projectmem/` state, so walking up risks reporting
"installed" from an unrelated ancestor directory's Projectmem project
rather than this repository's own adoption state. This mirrors how
detect_git_guardrails/detect_claude_guardrails (guardrails.py) already
scope strictly to repo_info.worktree_root.

Four states, not the full five-state guardrail vocabulary:
  installed      — `.projectmem/` is a directory and `.projectmem/config.toml`
                   exists (any entry type): Projectmem's own
                   initialized-project predicate, matched exactly.
  not-installed  — no `.projectmem` path entry exists at all at the
                   worktree root (checked lexically — see conflict below
                   for why a plain existence check is not enough).
  partial        — `.projectmem` is a directory but `config.toml` is
                   missing: a recognizable-looking directory that
                   Projectmem's own logic would not recognize as
                   initialized (e.g. a failed/incomplete `pjm init`, or an
                   unrelated empty directory of the same name — those two
                   cases are not objectively distinguishable from the
                   filesystem alone, so both surface as "partial").
  conflict       — `.projectmem` path entry exists but cannot serve as
                   Projectmem's directory: a plain file occupies the path,
                   or a symlink at that path is dangling (resolves to
                   nothing). Either way `pjm init`'s own
                   `project_dir.mkdir(exist_ok=True)` would fail against
                   it, so this is not a clean uninitialized state. Detected
                   via `os.path.lexists()` (path entry exists, symlink or
                   not) combined with `os.path.isdir()` (False for a file
                   or a dangling symlink) — never followed or repaired.

No "invalid" state: Projectmem never validates `config.toml`'s contents
(no TOML parsing occurs anywhere in its own initialization or discovery
path), so there is no reliable signal to distinguish "malformed" from
"incomplete" — an empty or corrupt config.toml still satisfies Projectmem's
own recognition predicate. Do not manufacture a distinction that has no
objective observation behind it.
"""

from __future__ import annotations

import os
import shutil

from .repo import RepoInfo

ProjectmemState = str

_VALID_STATES = frozenset({"installed", "not-installed", "partial", "conflict"})

_DIR_NAME = ".projectmem"
_CONFIG_FILE = "config.toml"

# The native Projectmem CLI entry point (installed separately, e.g. via
# `uv tool install projectmem` — Bindle declares no dependency on it; see
# pjm_executable()).
_PJM_BINARY = "pjm"

# `pjm init` flags Bindle always passes when it initializes Projectmem
# itself (never for a pre-existing "installed" repo — see cli.py). Bindle
# initializes Projectmem's core repository-local working-memory state,
# while suppressing every provider convenience that reaches outside that
# scope:
#   --no-hooks          Projectmem's own hook installer resolves
#                       `<cwd>/.git/hooks` directly — in a linked Git
#                       worktree, `.git` is a file, not that directory, so
#                       hook installation would silently no-op if attempted
#                       here. Hooks are installed separately (see
#                       PJM_HOOKS_INSTALL_ARGS below), against the
#                       repository's shared Git common directory, so they
#                       actually take effect regardless of which worktree
#                       `bindle init --projectmem` was run from.
#   --no-global        Projectmem's own cross-project memory store
#                       (~/.projectmem/global) is a standing, machine-wide
#                       system Bindle does not want to opt a repository
#                       into as a side effect of `bindle init`.
#   --no-watch          `bindle init` must not silently start a
#                       long-running watcher/daemon; that stays an
#                       explicit Projectmem/user choice (`pjm watch`).
#   --no-backfill       `bindle init` must not unexpectedly ingest existing
#                       Git history into Projectmem's working memory.
#   --no-claude-md      Bindle is provider-neutral: Projectmem must not
#                       silently append Claude-specific bridge prose into
#                       the repository's own CLAUDE.md as a side effect of
#                       Bindle setup.
#   --no-mcp-config     Projectmem MCP registration/configuration is a
#                       separate concern, not part of this seam.
#   --no-structure      Bindle setup should not trigger Projectmem's
#                       repository code-structure analysis.
#   --no-stack-detect   Bindle setup should not trigger Projectmem's
#                       stack/manifest analysis merely to initialize
#                       provider storage.
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

# `pjm hooks install` — Projectmem's own native hook installer, invoked
# separately from `pjm init` above and always against the repository's
# main checkout (RepoInfo.repo_root), never a linked worktree's own
# `worktree_root`: it also resolves `<cwd>/.git/hooks` directly (confirmed
# against the installed Projectmem 0.2.0 source), and `repo_root` is the
# one path guaranteed to have a real `.git/` directory regardless of which
# worktree Bindle was invoked from. Storage (PJM_INIT_ARGS, above) stays
# worktree-local by design — only hook installation needs this repository/
# common-Git scope. Bindle never constructs or edits Projectmem's hook
# files itself; this is Projectmem's own supported CLI surface for
# installing them.
PJM_HOOKS_INSTALL_ARGS = ("hooks", "install")


def pjm_executable() -> str | None:
    """Absolute path to the `pjm` CLI on PATH, or None if it isn't installed.

    Bindle has no Projectmem package dependency (AGENTS.md) and never
    constructs `.projectmem/` state itself — this is only ever used to
    either invoke the real `pjm init` or fail clearly when it's absent.
    """
    return shutil.which(_PJM_BINARY)


def detect_projectmem(repo_info: RepoInfo) -> ProjectmemState:
    """Read-only: Projectmem's adoption state for repo_info's worktree root."""
    path = os.path.join(repo_info.worktree_root, _DIR_NAME)

    # lexists (not exists): a dangling symlink at `path` must not read as a
    # clean absence — the path entry is occupied even though its target
    # isn't there.
    if not os.path.lexists(path):
        return "not-installed"

    # isdir follows symlinks and is False for a file or a dangling symlink,
    # so both collapse into "conflict" without following or repairing them.
    if not os.path.isdir(path):
        return "conflict"

    # exists (not isfile): matches Projectmem's own
    # `(candidate / CONFIG_FILE).exists()` predicate exactly, which accepts
    # any entry type at that path, not just a regular file.
    if os.path.exists(os.path.join(path, _CONFIG_FILE)):
        return "installed"

    return "partial"
