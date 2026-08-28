"""Shared repository-local Git exclude-state primitives.

Multiple Bindle integrations need the same narrow capability: keep a
specific, exact path locally ignored for one repository without ever
touching that repository's own tracked `.gitignore` — `qmd.py`'s `.qmd/`
directory (D032's precedent) and, per docs/DECISIONS.md, the exact
canonical SQLite work-ledger/Symphony-projection artifact paths under
`.bindle-work/`. This module is the one place the write mechanics (atomic
replace, dedup) and the tracked/ignored predicates (`git ls-files` / `git
check-ignore`) live, so those integrations can never drift apart on them.

Every path this module writes goes to `<git-common-dir>/info/exclude`
(never the tracked `.gitignore`) — machine-local, shared across every
linked worktree of a repository (docs/WORKTREES.md), never committed,
never visible to teammates. This module never decides *which* lines a
caller should add; it only writes/checks the ones it's given.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

# SQLite's own rollback-journal / WAL sidecar file suffixes, appended to a
# database file's own path. `""` first so the database file itself is
# always the first line a caller derives via `sqlite_artifact_exclude_lines`
# below.
SQLITE_SIDECAR_SUFFIXES = ("", "-journal", "-wal", "-shm")


class GitCommandError(OSError):
    """Raised when a Git command needed to answer a tracked/ignored query
    could not be run, or exited in a way that leaves the answer unknown —
    never conflated with an ordinary, meaningful "no" answer. Subclasses
    `OSError` so an existing best-effort caller that already wraps its
    body in `except OSError: pass` (e.g. `qmd.ensure_gitignored`) keeps
    swallowing it unchanged; a safety-critical caller (e.g. `bindle
    init`'s tracked-path collision preflight) must catch this explicitly
    and fail closed instead of letting a failure read as "not tracked."
    """


def info_exclude_path(git_common_dir: str) -> str:
    """Path to `<git_common_dir>/info/exclude`."""
    return os.path.join(git_common_dir, "info", "exclude")


def is_path_tracked(repo_root: str, relpath: str) -> bool:
    """Whether `relpath` (relative to `repo_root`) is tracked by Git.

    Raises `GitCommandError` if `git ls-files` itself could not be run or
    exited with a genuine error. `git ls-files -- <path>` is a query, not
    a boolean check — verified empirically that it exits 0 whether or not
    any file matches (empty stdout = not tracked), and exits nonzero only
    on a real failure (e.g. not inside a Git repository, exit 128) — so
    any nonzero exit here signals Git itself failed, never "not tracked."
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
    """Whether `relpath` (relative to `repo_root`) is already ignored by
    some existing mechanism (tracked `.gitignore`, a global gitignore, or
    a prior `info/exclude` entry)."""
    result = subprocess.run(
        ["git", "-C", repo_root, "check-ignore", "-q", relpath],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def atomic_append_line(path: str, line: str) -> None:
    """Append `line` to the file at `path`, creating it if absent.

    Read-modify-write via a temp file in the same directory plus
    `os.replace` (atomic on POSIX and Windows) — never a partial write
    left behind on a crash mid-write. Does not check whether `line` is
    already present; callers that need dedup do that check themselves
    first (see `ensure_line_excluded` below).
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

    Never checks tracked/ignored state itself — callers with a
    directory-shaped exclude (like `qmd.py`'s `.qmd/`) need that decision
    made against the actual worktree path, not the literal exclude line
    text, so that check stays the caller's own responsibility (see
    `is_path_tracked`/`is_path_ignored` above).
    """
    path = info_exclude_path(git_common_dir)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            if line in f.read().splitlines():
                return
    atomic_append_line(path, line)


def sqlite_artifact_exclude_lines(root_relative_path: str) -> tuple[str, ...]:
    """Root-anchored `info/exclude` lines for one SQLite database and its
    rollback-journal/WAL/SHM sidecars.

    `root_relative_path` is the artifact's path relative to the
    repository root (e.g. `.bindle-work/ledger.sqlite3`), forward-slash
    separated. Each returned line is prefixed with `/` — anchored to the
    repository root, matching exactly one file, never a same-named file
    elsewhere in the tree.
    """
    return tuple(f"/{root_relative_path}{suffix}" for suffix in SQLITE_SIDECAR_SUFFIXES)
