"""Shared repository-local Git exclude-state primitives.

Keeps an exact path locally ignored via `<git-common-dir>/info/exclude`, never
the tracked `.gitignore`: machine-local, shared across linked worktrees
(docs/WORKTREES.md), never committed. Used by `qmd.py` (`.qmd/`, D032) and the
`.bindle-work/` SQLite work-ledger artifacts, so their write mechanics and
tracked/ignored predicates cannot drift apart. Callers decide which lines to
add; this module only writes/checks the ones given.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

# SQLite journal/WAL/SHM sidecar suffixes; "" first so the database file leads.
SQLITE_SIDECAR_SUFFIXES = ("", "-journal", "-wal", "-shm")


class GitCommandError(OSError):
    """A Git tracked/ignored query could not be answered; never conflated with a
    meaningful "no".

    Subclasses `OSError` so best-effort callers wrapping `except OSError` (e.g.
    `qmd.ensure_gitignored`) keep swallowing it; safety-critical callers (e.g.
    `bindle init`'s tracked-path collision preflight) must catch it and fail
    closed.
    """


def info_exclude_path(git_common_dir: str) -> str:
    """Path to `<git_common_dir>/info/exclude`."""
    return os.path.join(git_common_dir, "info", "exclude")


def is_path_tracked(repo_root: str, relpath: str) -> bool:
    """Whether `relpath` (relative to `repo_root`) is tracked by Git.

    Raises `GitCommandError` on any nonzero exit: `git ls-files -- <path>` exits
    0 whether or not a file matches (empty stdout = untracked), so nonzero means
    Git itself failed (e.g. exit 128 outside a repo).
    """
    result = subprocess.run(
        ["git", "-C", repo_root, "ls-files", "--", relpath],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitCommandError(
            f"git ls-files failed for {relpath!r} in {repo_root!r} "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
    return bool(result.stdout.strip())


def is_path_ignored(repo_root: str, relpath: str) -> bool:
    """Whether `relpath` is already ignored by `.gitignore`, a global gitignore,
    or `info/exclude`."""
    result = subprocess.run(
        ["git", "-C", repo_root, "check-ignore", "-q", relpath],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def atomic_append_line(path: str, line: str) -> None:
    """Append `line` to `path` (created if absent) via temp file + `os.replace`;
    never partial.

    Does not dedup; see `ensure_line_excluded`.
    """
    existing = ""
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()
    sep = "" if not existing or existing.endswith("\n") else "\n"
    new_text = f"{existing}{sep}{line}\n"

    dest_dir = os.path.dirname(path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".bindle-exclude-tmp.", dir=dest_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ensure_line_excluded(git_common_dir: str, line: str) -> None:
    """Idempotently append `line` to `info/exclude` if not already present.

    Does not check tracked/ignored state: directory-shaped excludes (like
    `.qmd/`) need that decided against the worktree path, so callers use
    `is_path_tracked`/`is_path_ignored` themselves.
    """
    path = info_exclude_path(git_common_dir)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            if line in f.read().splitlines():
                return
    atomic_append_line(path, line)


def sqlite_artifact_exclude_lines(root_relative_path: str) -> tuple[str, ...]:
    """Root-anchored `info/exclude` lines for one SQLite database and its
    journal/WAL/SHM sidecars.

    `root_relative_path` is forward-slash separated, relative to the repo root
    (e.g. `.bindle-work/ledger.sqlite3`); the leading `/` anchors each line to
    exactly one file, never a same-named file elsewhere.
    """
    return tuple(f"/{root_relative_path}{suffix}" for suffix in SQLITE_SIDECAR_SUFFIXES)
