"""Symphony-facing publish and write surface (specs/003-symphony-task-integration).

Rationale lives in specs/003-symphony-task-integration/contracts/
(symphony-projection-v1.md, task-write-surface.md). Two additions over the
unchanged internal ledger:

1. `publish()` regenerates a disposable, physically separate SQLite export
   file (never a table in `ledger.sqlite3`) that a coordinator can query.
2. `claim_task()`/`release_task()`/`complete_task()` are the only external
   write surface: thin, type-checked wrappers over `WorkLedger`'s atomic
   primitives, adding no arbitration mechanism, raw SQL, or database handle
   (FR-020-FR-024).

Not a Symphony adapter: it never supervises Symphony and never reads, writes,
or translates Symphony's own `.symphony/local_tracker.json`; see
docs/SYMPHONY.md.
"""

from __future__ import annotations

import dataclasses
import os
import sqlite3

from . import git_local_exclude
from .work_ledger import WorkLedger, ledger_path

_PROJECTION_FILE_NAME = "symphony-projection.sqlite3"

# Independent of the ledger's `_SCHEMA_VERSION`; a breaking change ships as v2.
_PROJECTION_VERSION = 1

# ASCII "BSP1" (Bindle Symphony Projection, format 1) as a big-endian int32.
_APPLICATION_ID = 0x42535031

# Adopt a pre-marker file only if its tables match, not on user_version alone.
_KNOWN_TABLE_NAMES = frozenset({"task_projection"})


class ForeignDatabaseError(RuntimeError):
    """Raised when a file at the projection path is not Bindle's or adoptable.

    Absent files are safe to create; files with `_APPLICATION_ID`, or
    pre-marker files whose `user_version` and tables match, are safe to
    regenerate; anything else is never dropped or reinterpreted. `publish()`
    raises this before any `DROP TABLE`/`CREATE TABLE`.
    """

_CREATE_TASK_PROJECTION_SQL = """
CREATE TABLE task_projection (
  id           TEXT PRIMARY KEY,
  identifier   TEXT NOT NULL,
  title        TEXT,
  description  TEXT,
  status       TEXT NOT NULL,
  dispatchable INTEGER NOT NULL,
  created_at   TEXT NOT NULL
)
"""


def projection_path(repo_root: str) -> str:
    """Path to the published projection file, a sibling of `ledger.sqlite3`.

    Resolved from `repo_root` (the Git common directory), so every linked
    worktree sees the same file.
    """
    return os.path.join(os.path.dirname(ledger_path(repo_root)), _PROJECTION_FILE_NAME)


def ensure_gitignored(git_common_dir: str) -> bool:
    """Locally ignore the projection file and its SQLite sidecars.

    Mirrors `work_ledger.ensure_gitignored()`: adds lines to the machine-local
    `info/exclude`, never raises, and returns `True` iff every line was
    confirmed present (`False` on `OSError`). Never touches the tracked
    `.gitignore`.
    """
    try:
        relpath = f".bindle-work/{_PROJECTION_FILE_NAME}"
        for line in git_local_exclude.sqlite_artifact_exclude_lines(relpath):
            git_local_exclude.ensure_line_excluded(git_common_dir, line)
        return True
    except OSError:
        return False


def _table_columns(conn: sqlite3.Connection, table_name: str) -> tuple[tuple, ...]:
    """`(name, declared_type, notnull, pk)` per column, in column order.

    Deliberate copy of `work_ledger._table_columns`, not a shared module;
    `table_name` is never caller input.
    """
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return tuple((row[1], row[2], row[3], row[5]) for row in sorted(rows, key=lambda r: r[0]))


def _reference_task_projection_columns() -> tuple[tuple, ...]:
    """Column shape derived from the one `_CREATE_TASK_PROJECTION_SQL`."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(_CREATE_TASK_PROJECTION_SQL)
        return _table_columns(conn, "task_projection")
    finally:
        conn.close()


def _verify_ownership(conn: sqlite3.Connection, db_path: str) -> None:
    """Raise `ForeignDatabaseError` unless `db_path` is ours or adoptable.

    Path-oriented, with no filesize or content heuristic: `publish()` stamps a
    path that was absent beforehand before calling this. Same structure as
    `work_ledger._verify_ownership`.
    """
    try:
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        if app_id == _APPLICATION_ID:
            return
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        tables = frozenset(row[0] for row in rows)
    except sqlite3.DatabaseError as exc:
        raise ForeignDatabaseError(
            f"{db_path}: existing file is not a readable SQLite database "
            f"({exc}) — refusing to treat it as a Bindle Symphony projection."
        ) from exc

    if app_id == 0 and version == 0 and not tables:
        raise ForeignDatabaseError(
            f"{db_path}: an existing, empty file already occupies the "
            "Symphony projection path — refusing to treat a pre-existing "
            "file as fresh Bindle state. Move or remove it yourself if it "
            "is safe to replace."
        )

    if app_id == 0 and version == _PROJECTION_VERSION and tables == _KNOWN_TABLE_NAMES:
        if _table_columns(conn, "task_projection") == _reference_task_projection_columns():
            return
        raise ForeignDatabaseError(
            f"{db_path}: an existing file matches a Bindle Symphony "
            f"projection's table name at user_version={version}, but its "
            "column shape does not match — refusing to treat it as a "
            "Bindle-owned or adoptable projection. Move or remove the "
            "existing file yourself if it is safe to replace, or "
            "investigate what created it."
        )

    raise ForeignDatabaseError(
        f"{db_path}: an existing file occupies the Symphony projection "
        "path but is not recognizable as a Bindle-owned or adoptable "
        f"projection (application_id={app_id}, user_version={version}, "
        f"tables={sorted(tables)}) — refusing to regenerate it. Move or "
        "remove the existing file yourself if it is safe to replace, or "
        "investigate what created it."
    )


def publish(ledger: WorkLedger) -> str:
    """Regenerate the published Symphony projection file and return its path.

    Drops and recreates `task_projection` from one
    `generate_external_projection()` snapshot inside a single transaction,
    together with the `user_version` write, so a reader never sees a partial
    table and a crash mid-publish leaves the prior valid file
    (contracts/symphony-projection-v1.md).

    This is the only write path to the export file, and Bindle never reads it
    back.

    The in-place transaction is deliberate, not write-to-temp-then-rename:
    research.md ("publish atomicity mechanism") verified it still never exposes
    a torn projection, even on a hard kill.
    """
    export_path = projection_path(ledger.repo_root)
    os.makedirs(os.path.dirname(export_path), exist_ok=True)
    # Must precede sqlite3.connect(), which creates a 0-byte file immediately.
    path_existed_before = os.path.exists(export_path)
    rows = ledger.generate_external_projection()

    conn = sqlite3.connect(export_path, isolation_level=None)
    try:
        if not path_existed_before:
            # Stamp early so a mid-publish crash still leaves a recognized file.
            conn.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        # Must precede any DROP/CREATE: never regenerate a foreign file.
        _verify_ownership(conn, export_path)
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DROP TABLE IF EXISTS task_projection")
            conn.execute(_CREATE_TASK_PROJECTION_SQL)
            conn.executemany(
                "INSERT INTO task_projection "
                "(id, identifier, title, description, status, dispatchable, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        row.id,
                        row.identifier,
                        row.title,
                        row.description,
                        row.status,
                        int(row.dispatchable),
                        row.created_at,
                    )
                    for row in rows
                ],
            )
            # PRAGMAs take no `?` binds; these interpolate fixed constants only.
            # Stamping here also adopts a verified pre-marker file.
            conn.execute(f"PRAGMA user_version = {_PROJECTION_VERSION}")
            conn.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
    finally:
        conn.close()
    return export_path


# Each write function rejects unknown and non-task ids (FR-024).


@dataclasses.dataclass(frozen=True)
class ClaimResult:
    """Result of `claim_task()`.

    `ok=False` carries `reason`: `"not_found"`, `"not_a_task"` (a milestone
    id), or `"already_claimed"` (the ordinary outcome when another owner holds
    the claim).
    """

    ok: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class ReleaseResult:
    """Result of `release_task()`.

    `ok=True` also when the claim was absent or held by another owner (a
    no-op, never an error). `ok=False` carries `reason`: `"not_found"` or
    `"not_a_task"`.
    """

    ok: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class CompleteResult:
    """Result of `complete_task()`.

    `ok=False` carries `reason`: `"not_found"`, `"not_a_task"`, or
    `"not_open"` (never reapplied).
    """

    ok: bool
    reason: str | None = None


def claim_task(
    ledger: WorkLedger,
    id: str,
    owner: str,
    worktree_path: str | None = None,
    branch: str | None = None,
) -> ClaimResult:
    """Claim a task by id for an external caller.

    Delegates to `WorkLedger.claim()`, so of any number of concurrent attempts
    on an unclaimed task exactly one succeeds and the rest are rejected
    immediately (SC-008).
    """
    item = ledger.get_work_item(id)
    if item is None:
        return ClaimResult(ok=False, reason="not_found")
    if item.type != "task":
        return ClaimResult(ok=False, reason="not_a_task")
    if ledger.claim(id, owner, worktree_path=worktree_path, branch=branch):
        return ClaimResult(ok=True)
    return ClaimResult(ok=False, reason="already_claimed")


def release_task(ledger: WorkLedger, id: str, owner: str) -> ReleaseResult:
    """Release `owner`'s claim on a task; an unheld release is a no-op."""
    item = ledger.get_work_item(id)
    if item is None:
        return ReleaseResult(ok=False, reason="not_found")
    if item.type != "task":
        return ReleaseResult(ok=False, reason="not_a_task")
    ledger.release_claim(id, owner)
    return ReleaseResult(ok=True)


def complete_task(ledger: WorkLedger, id: str) -> CompleteResult:
    """Mark a task done via `WorkLedger.mark_done()`; rejected unless open."""
    item = ledger.get_work_item(id)
    if item is None:
        return CompleteResult(ok=False, reason="not_found")
    if item.type != "task":
        return CompleteResult(ok=False, reason="not_a_task")
    if ledger.mark_done(id):
        return CompleteResult(ok=True)
    return CompleteResult(ok=False, reason="not_open")
