"""Symphony-facing publish and write surface (specs/003-symphony-task-integration).

Implements the accepted design in specs/003-symphony-task-integration/
(spec.md, plan.md, research.md, data-model.md,
contracts/symphony-projection-v1.md, contracts/task-write-surface.md) —
read those first for the "why" behind anything here. In short: this module
adds two things on top of the existing, unchanged internal ledger
(`src/bindle/work_ledger.py`):

1. `publish()` — a disposable, regenerated, physically separate SQLite
   export file (never a view or table inside the internal `ledger.sqlite3`)
   that an external coordinator can open and query directly, on its own
   schedule, without ever touching Bindle's own internal tables or process.
2. `claim_task()`/`release_task()`/`complete_task()` — the smallest
   possible external write surface, each a thin, type-checked wrapper over
   `WorkLedger`'s own already-atomic `claim()`/`release_claim()`/
   `mark_done()` primitives. Neither adds a new arbitration mechanism, raw
   SQL exposure, or a database handle a caller could use for anything
   beyond these named operations (FR-020-FR-024).

This module is never a Symphony adapter: it does not install, start, stop,
or otherwise supervise Symphony. A future Symphony-side `Tracker` adapter
would read this published artifact and map its rows onto `Tracker.Issue`
directly — that adapter is separate future work and is unrelated to
Symphony's own standalone local tracker format (`.symphony/local_tracker.json`),
which this module never reads, writes, or translates into — see
docs/SYMPHONY.md.
"""

from __future__ import annotations

import dataclasses
import os
import sqlite3

from . import git_local_exclude
from .work_ledger import WorkLedger, ledger_path

_PROJECTION_FILE_NAME = "symphony-projection.sqlite3"

# The published export file's own `PRAGMA user_version` — independent of
# the internal ledger's `_SCHEMA_VERSION` (research.md's "Decision:
# published projection versioning"). A future incompatible shape change
# ships as `contracts/symphony-projection-v2.md` alongside a bump of this
# constant, mirroring the `coordinator-projection.md` ->
# `coordinator-projection-v2.md` precedent specs/002 already established.
_PROJECTION_VERSION = 1

# SQLite `PRAGMA application_id` — a small, narrow ownership marker for
# exactly this one file, distinct from `work_ledger._APPLICATION_ID` (see
# that module for the shared rationale). The ASCII bytes "BSP1" ("Bindle
# Symphony Projection", format 1) read as a big-endian 32-bit integer.
_APPLICATION_ID = 0x42535031

# The exact table this projection format has always had — used by
# `_verify_ownership` to positively recognize a pre-marker
# (application_id == 0) file as a genuine, adoptable Bindle projection
# rather than an unrelated file that happens to share `user_version == 1`.
_KNOWN_TABLE_NAMES = frozenset({"task_projection"})


class ForeignDatabaseError(RuntimeError):
    """Raised when an existing file at the projection path cannot be
    positively identified as a Bindle-owned or adoptable Symphony
    projection.

    Mirrors `work_ledger.ForeignDatabaseError`'s same-path filesystem-
    collision safety rule, applied to the disposable projection file: an
    absent file is always safe to create; one already carrying
    `_APPLICATION_ID`, or a pre-marker file whose `user_version` and
    table set positively match `_PROJECTION_VERSION`/`_KNOWN_TABLE_NAMES`,
    is safe to adopt and regenerate; anything else must never be dropped,
    recreated, or reinterpreted. `publish()` raises this before its own
    `DROP TABLE`/`CREATE TABLE` ever runs.
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
    """Path to this repository's published Symphony projection file.

    A sibling of `ledger.sqlite3` under the same `.bindle-work/` directory
    `ledger_path()` already establishes (research.md's "Decision:
    published projection storage location and format"), resolved from
    `repo_root` (`RepoInfo.repo_root` — the Git common directory), so
    every linked worktree sees the same published artifact, exactly like
    the internal ledger.
    """
    return os.path.join(os.path.dirname(ledger_path(repo_root)), _PROJECTION_FILE_NAME)


def ensure_gitignored(git_common_dir: str) -> bool:
    """Make sure the published projection file and its SQLite sidecars are
    locally ignored for this repository.

    Adds exactly `/.bindle-work/symphony-projection.sqlite3` and its
    `-journal`/`-wal`/`-shm` sidecar lines to the repository's
    machine-local `info/exclude` — mirrors `work_ledger.ensure_gitignored()`
    exactly, including its return-value contract (see that function's
    docstring for the full rationale): never raises, but returns `True`
    iff every line was confirmed present and `False` if an `OSError`
    prevented that, so a caller can report the outcome instead of
    silently claiming success. Never the tracked `.gitignore`, never a
    broader rule.
    """
    try:
        relpath = f".bindle-work/{_PROJECTION_FILE_NAME}"
        for line in git_local_exclude.sqlite_artifact_exclude_lines(relpath):
            git_local_exclude.ensure_line_excluded(git_common_dir, line)
        return True
    except OSError:
        return False


def _table_columns(conn: sqlite3.Connection, table_name: str) -> tuple[tuple, ...]:
    """`(name, declared_type, notnull, pk)` for every column of `table_name`,
    ordered by column position — mirrors `work_ledger._table_columns`
    exactly (see its docstring); kept as a small, self-contained copy here
    rather than a new shared module, since each file's `_verify_ownership`
    is already its own independent, parallel implementation. `table_name`
    is always `"task_projection"`, never caller-supplied input.
    """
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return tuple((row[1], row[2], row[3], row[5]) for row in sorted(rows, key=lambda r: r[0]))


def _reference_task_projection_columns() -> tuple[tuple, ...]:
    """The exact current `task_projection` column shape, derived by
    running `_CREATE_TASK_PROJECTION_SQL` — the identical, authoritative
    SQL `publish()` uses — against a throwaway in-memory connection.
    Never a second, independently-maintained schema definition. There is
    only ever one projection format version to date (`_PROJECTION_VERSION
    == 1`); a future v2 format would add its own reference shape here
    alongside `contracts/symphony-projection-v2.md`.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(_CREATE_TASK_PROJECTION_SQL)
        return _table_columns(conn, "task_projection")
    finally:
        conn.close()


def _verify_ownership(conn: sqlite3.Connection, db_path: str) -> None:
    """Refuse to touch an existing file at `db_path` that cannot be
    positively identified as Bindle-owned or adoptable, before `publish()`
    ever runs `DROP TABLE`/`CREATE TABLE` against it. Strictly
    path-oriented, with no filesize or content heuristic — a path absent
    before this invocation is stamped `_APPLICATION_ID` by `publish()`
    itself, immediately, before this function is ever called (see
    `publish()`'s own comment). See `ForeignDatabaseError` above and
    `work_ledger._verify_ownership` (the identical structure, applied to
    the ledger file) for the full rationale.
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

    contracts/symphony-projection-v1.md: reads the current
    `generate_external_projection()` result (one snapshot, per that
    method's own single-`SELECT` consistency guarantee) and rewrites the
    export file's `task_projection` table from it — drop and recreate,
    fully, inside one transaction, never an incremental patch — so a
    reader never observes a partially-rewritten table (data-model.md's
    "Regeneration"). `PRAGMA user_version` is set to `1`
    (`_PROJECTION_VERSION`) inside that same transaction, exactly
    mirroring `work_ledger._ensure_schema`'s own verified-safe pattern of
    including a `PRAGMA user_version` write inside an explicit
    transaction so a crash mid-publish leaves the file at its prior,
    fully-valid state rather than a half-written one.

    This is the only write path to the export file: nothing else in
    Bindle's code ever opens it for writing, and Bindle's own internal
    code never reads it back (data-model.md's "Regeneration") — it exists
    solely for an external reader.

    This in-place transaction, rather than a write-to-temp-then-rename,
    was adversarially verified (research.md's "Decision: publish
    atomicity mechanism") to give a concurrent reader the guarantee that
    actually matters — never a torn or schema/version-inconsistent
    projection, including under a hard process kill before commit — so
    it is retained deliberately, not for lack of consideration.
    """
    export_path = projection_path(ledger.repo_root)
    os.makedirs(os.path.dirname(export_path), exist_ok=True)
    # Must be observed BEFORE sqlite3.connect() below, which creates a
    # 0-byte file immediately for a path that didn't already exist — see
    # work_ledger.connect()'s identical comment.
    path_existed_before = os.path.exists(export_path)
    rows = ledger.generate_external_projection()

    conn = sqlite3.connect(export_path, isolation_level=None)
    try:
        if not path_existed_before:
            # This connection's own sqlite3.connect() call is what just
            # created export_path — stamp ownership immediately, before
            # the regenerate transaction below can ever fail, so a crash
            # mid-publish still leaves the file positively recognizable as
            # Bindle's own on the next `publish()` attempt (no filesize or
            # content heuristic needed — see work_ledger.connect()'s
            # identical rationale).
            conn.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        # Ownership MUST be verified before the transaction below ever
        # runs `DROP TABLE`/`CREATE TABLE` — a foreign or unrecognizable
        # file at `export_path` must never be regenerated or
        # reinterpreted (see `ForeignDatabaseError`/`_verify_ownership`
        # above).
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
            # PRAGMA user_version/application_id do not accept `?` bind
            # parameters; both values here are always the fixed internal
            # constants above, never caller-provided input. Stamping
            # application_id inside this same transaction, alongside
            # user_version, adopts a pre-marker file (already positively
            # verified above) exactly once.
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


# -- Write surface (User Story 3) -------------------------------------
#
# contracts/task-write-surface.md: each function first resolves `id`
# through `WorkLedger.get_work_item()` and rejects with a distinct result
# when it does not exist or is not a `type = 'task'` row (FR-024) — never
# silently treating a milestone id as a task. Once that guard passes,
# each function delegates unchanged to the corresponding existing,
# already-atomic `WorkLedger` primitive; none of these functions
# introduces a new arbitration mechanism, raw SQL, or a database handle
# (FR-020-FR-023).


@dataclasses.dataclass(frozen=True)
class ClaimResult:
    """Result of `claim_task()`.

    `ok=True` iff the claim was acquired. `ok=False` carries `reason`:
    `"not_found"` (no such work item), `"not_a_task"` (a milestone id),
    or `"already_claimed"` (the underlying `WorkLedger.claim()`'s own
    ordinary, expected "someone else already holds this claim" outcome).
    """

    ok: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class ReleaseResult:
    """Result of `release_task()`.

    `ok=True` iff the release was performed (which, per
    `WorkLedger.release_claim()`'s own "safe release" guarantee, is also
    true when the claim was already absent or held by a different
    owner — a no-op, never an error). `ok=False` carries `reason`:
    `"not_found"` or `"not_a_task"`.
    """

    ok: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class CompleteResult:
    """Result of `complete_task()`.

    `ok=True` iff the task transitioned to `done`. `ok=False` carries
    `reason`: `"not_found"`, `"not_a_task"`, or `"not_open"` (the
    underlying `WorkLedger.mark_done()`'s own guarded-transition refusal
    when the task is not currently `open` — never silently reapplied).
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
    """Claim a task by id, on behalf of an external caller.

    Delegates directly to `WorkLedger.claim()`, preserving that method's
    exact atomicity guarantee: of any number of concurrent claim attempts
    against one never-before-claimed task, exactly one succeeds and every
    other receives an immediate, unambiguous rejection (SC-008) — this
    function adds only the milestone/not-found guard above `claim()`,
    never a second arbitration mechanism.
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
    """Release a claim held by `owner` on a task, on behalf of an external caller.

    Delegates directly to `WorkLedger.release_claim()` — releasing a
    claim not held by `owner`, or releasing an already-unclaimed task, is
    a no-op, never an error, exactly matching the underlying method's own
    "safe release" guarantee.
    """
    item = ledger.get_work_item(id)
    if item is None:
        return ReleaseResult(ok=False, reason="not_found")
    if item.type != "task":
        return ReleaseResult(ok=False, reason="not_a_task")
    ledger.release_claim(id, owner)
    return ReleaseResult(ok=True)


def complete_task(ledger: WorkLedger, id: str) -> CompleteResult:
    """Mark a task done, on behalf of an external caller.

    Delegates directly to `WorkLedger.mark_done()`, mirroring its exact
    guarded-transition semantics: rejected (never silently reapplied)
    when the task is not currently `open`.
    """
    item = ledger.get_work_item(id)
    if item is None:
        return CompleteResult(ok=False, reason="not_found")
    if item.type != "task":
        return CompleteResult(ok=False, reason="not_a_task")
    if ledger.mark_done(id):
        return CompleteResult(ok=True)
    return CompleteResult(ok=False, reason="not_open")
