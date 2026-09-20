"""Durable, repository-scoped, SQLite-backed ledger for decomposed work.

Design: specs/001-durable-work-ledger/ (read it for the "why"). Per work item it
stores orthogonal coordination facts (status, blocking, claim, evidence, a
source pointer) in one SQLite database at the Git common directory
(`RepoInfo.repo_root`, never the invoking worktree), so every linked worktree
sees the same ledger. Schema v2 (specs/002-milestone-task-work-items/) adds
`type` (`task` | `milestone`) and `parent_id`. Never a scheduler, DAG solver,
daemon, or Symphony adapter.

`WorkLedger` is stateless except for `repo_root`: every method opens and closes
its own short-lived connection.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import os
import sqlite3
import subprocess
from collections.abc import Sequence

from . import git_local_exclude


class SchemaVersionError(RuntimeError):
    """Raised when an existing ledger's schema version is unexpected."""


class ForeignDatabaseError(RuntimeError):
    """Raised when the ledger path holds a file not positively a Bindle ledger.

    Same-path collision safety rule (docs/DECISIONS.md): an absent file is safe
    to create; a file carrying `_APPLICATION_ID`, or a pre-marker file whose
    `user_version` and table set match a known Bindle shape, is safe to adopt;
    anything else (foreign, unreadable, or Bindle-shaped at an unexpected
    version) is never overwritten. `connect()` raises this before any `CREATE
    TABLE`, migration, or journal-mode write.
    """


_LEDGER_DIR_NAME = ".bindle-work"
_LEDGER_FILE_NAME = "ledger.sqlite3"

# application_id: ASCII "BWL1" as big-endian int32; not symphony_projection's.
_APPLICATION_ID = 0x42574C31

# Table set of every schema version (1-3); recognizes pre-marker ledgers.
_KNOWN_TABLE_NAMES = frozenset(
    {"work_items", "work_item_blocked_by", "work_item_claims", "work_item_evidence"}
)
_KNOWN_SCHEMA_VERSIONS = frozenset({1, 2, 3})

# PRAGMA user_version: when the schema next changes, bump this and add a
# migration keyed by the version it moves from.
# v2 (specs/002 research.md): `type`/`parent_id`/`description` columns and a
# compound (type, status) CHECK; `_migrate_v1_to_v2`.
# v3 (specs/003 research.md, "created_at NOT NULL for live rows"): CHECK
# (archived_at IS NOT NULL OR created_at IS NOT NULL), since the Symphony
# projection's `created_at` is NOT NULL; `_migrate_v2_to_v3` backfills a live
# row's NULL `created_at` from `updated_at` first (v1 reaches v3 via both
# migrations).
_SCHEMA_VERSION = 3


def _work_items_create_sql(table_name: str) -> str:
    """The `work_items` (v3) `CREATE TABLE` body for `table_name`.

    One definition shared by fresh init and the v1->v2 / v2->v3 rebuild
    migrations (`work_items_new`, later renamed), so the paths cannot drift
    apart.
    """
    return f"""
    CREATE TABLE {table_name} (
      id                TEXT PRIMARY KEY,
      type              TEXT NOT NULL CHECK (type IN ('task', 'milestone')),
      parent_id         TEXT REFERENCES {table_name}(id),
      title             TEXT,
      description       TEXT,
      status            TEXT NOT NULL,
      superseded_by     TEXT REFERENCES {table_name}(id),
      source_kind       TEXT CHECK (source_kind IN ('speckit_task', 'plan', 'adhoc')),
      source_locator    TEXT,
      source_promoted_by TEXT,
      created_at        TEXT,
      updated_at        TEXT NOT NULL,
      archived_at       TEXT,
      CHECK (
        (status = 'superseded' AND superseded_by IS NOT NULL) OR
        (status != 'superseded' AND superseded_by IS NULL)
      ),
      CHECK (
        (type = 'task' AND status IN ('open', 'done', 'superseded')) OR
        (type = 'milestone' AND status IN ('open', 'review', 'accepted', 'superseded'))
      ),
      CHECK (
        (type = 'milestone' AND parent_id IS NULL) OR (type = 'task')
      ),
      CHECK (
        archived_at IS NOT NULL OR created_at IS NOT NULL
      )
    )
    """


_SCHEMA_STATEMENTS = (
    _work_items_create_sql("work_items"),
    """
    CREATE TABLE work_item_blocked_by (
      work_item_id      TEXT NOT NULL REFERENCES work_items(id),
      blocked_on_id     TEXT NOT NULL REFERENCES work_items(id),
      PRIMARY KEY (work_item_id, blocked_on_id),
      CHECK (work_item_id != blocked_on_id)
    )
    """,
    """
    CREATE TABLE work_item_claims (
      work_item_id      TEXT PRIMARY KEY REFERENCES work_items(id),
      owner             TEXT NOT NULL,
      claimed_at        TEXT NOT NULL,
      worktree_path     TEXT,
      branch            TEXT
    )
    """,
    """
    CREATE TABLE work_item_evidence (
      evidence_id       INTEGER PRIMARY KEY,
      work_item_id      TEXT NOT NULL REFERENCES work_items(id),
      kind              TEXT NOT NULL CHECK (kind IN ('branch', 'commit', 'pull_request', 'other')),
      value             TEXT NOT NULL,
      recorded_at       TEXT NOT NULL,
      note              TEXT
    )
    """,
)


def ledger_path(repo_root: str) -> str:
    """Ledger file path under `repo_root`, the Git common directory.

    Never the invoking worktree; every linked worktree therefore opens the same
    physical file.
    """
    return os.path.join(repo_root, _LEDGER_DIR_NAME, _LEDGER_FILE_NAME)


def ensure_gitignored(git_common_dir: str) -> bool:
    """Locally ignore the ledger file and sidecars; `True` iff all confirmed.

    Adds exactly `/.bindle-work/ledger.sqlite3` and its `-journal`/`-wal`/`-shm`
    lines to the machine-local `info/exclude` -- never the tracked `.gitignore`,
    never a broader `.bindle-work/` or `*.sqlite3` rule (see
    `git_local_exclude.py`, docs/DECISIONS.md) -- so other content under
    `.bindle-work/` stays trackable. Idempotent. Never raises on an `OSError`;
    returns `False` instead so a caller (`bindle init`) can report it rather
    than claim success.
    """
    try:
        relpath = f"{_LEDGER_DIR_NAME}/{_LEDGER_FILE_NAME}"
        for line in git_local_exclude.sqlite_artifact_exclude_lines(relpath):
            git_local_exclude.ensure_line_excluded(git_common_dir, line)
        return True
    except OSError:
        return False


def _existing_table_names(conn: sqlite3.Connection) -> frozenset[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return frozenset(row[0] for row in rows)


def _table_columns(conn: sqlite3.Connection, table_name: str) -> tuple[tuple, ...]:
    """Per-column `(name, declared_type, notnull, pk)` via `PRAGMA table_info`.

    In column order. `table_name` is interpolated into SQL: always a fixed name
    from `_KNOWN_TABLE_NAMES`, never caller input.
    """
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    # row: (cid, name, type, notnull, dflt_value, pk)
    return tuple((row[1], row[2], row[3], row[5]) for row in sorted(rows, key=lambda r: r[0]))


# Columns _migrate_v1_to_v2 adds; current shape minus these is the v1 shape.
_V1_TO_V2_ADDED_WORK_ITEMS_COLUMNS = frozenset({"type", "parent_id", "description"})


def _reference_table_columns() -> dict[str, tuple[tuple, ...]]:
    """The current column shape of every table in `_KNOWN_TABLE_NAMES`.

    Built by running `_SCHEMA_STATEMENTS` against a throwaway in-memory
    connection and reading `PRAGMA table_info`, so there is no second schema
    definition. Only `work_items` ever changed shape across v1-3; this shape is
    also v2's and v3's, since `_migrate_v2_to_v3` changes only a table-level
    `CHECK`, which `table_info` does not show.
    """
    conn = sqlite3.connect(":memory:")
    try:
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        return {name: _table_columns(conn, name) for name in _KNOWN_TABLE_NAMES}
    finally:
        conn.close()


def _expected_table_columns(version: int) -> dict[str, tuple[tuple, ...]]:
    """Expected column shape per table for a pre-marker database at `version`.

    `version` is one of `_KNOWN_SCHEMA_VERSIONS`. v2 and v3 share
    `_reference_table_columns()`; v1's `work_items` omits
    `_V1_TO_V2_ADDED_WORK_ITEMS_COLUMNS`.
    """
    current = _reference_table_columns()
    if version != 1:
        return current
    v1 = dict(current)
    v1["work_items"] = tuple(
        col for col in current["work_items"] if col[0] not in _V1_TO_V2_ADDED_WORK_ITEMS_COLUMNS
    )
    return v1


def _verify_ownership(conn: sqlite3.Connection, db_path: str) -> None:
    """Refuse an existing `db_path` file that is not Bindle-owned or migratable.

    Runs before `_ensure_schema()` or any journal-mode write. Path-oriented,
    with no filesize or content heuristic: `connect()` stamps `_APPLICATION_ID`
    on a path it just created before calling this, so an `application_id == 0`
    state seen here always means a pre-existing file this invocation did not
    create.

    * `application_id == _APPLICATION_ID`: proceed (fresh, or an already-stamped
      ledger); a crash after the stamp leaves a file a retry recognizes as its
      own.
    * `application_id == 0`, `user_version == 0`, no tables: refused regardless
      of size, since an unrelated empty SQLite database is indistinguishable
      from a partially initialized one.
    * `application_id == 0`, `user_version` in `_KNOWN_SCHEMA_VERSIONS`, table
      set exactly `_KNOWN_TABLE_NAMES`, and every table's `PRAGMA table_info`
      columns matching `_expected_table_columns(version)`: a pre-marker ledger;
      proceed, and `_ensure_schema()` migrates it and stamps the marker once. A
      table-name match with mismatched columns is never adopted.
    * Anything else (foreign nonzero `application_id`, unmatched shape,
      unreadable file): raises `ForeignDatabaseError`, failing closed with
      nothing created, migrated, or written.
    """
    try:
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        if app_id == _APPLICATION_ID:
            return
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = _existing_table_names(conn)
    except sqlite3.DatabaseError as exc:
        raise ForeignDatabaseError(
            f"{db_path}: existing file is not a readable SQLite database "
            f"({exc}) — refusing to treat it as a Bindle work ledger."
        ) from exc

    if app_id == 0 and version == 0 and not tables:
        raise ForeignDatabaseError(
            f"{db_path}: an existing, empty file already occupies the "
            "work ledger path — refusing to treat a pre-existing file as "
            "fresh Bindle state. Move or remove it yourself if it is "
            "safe to replace."
        )

    if app_id == 0 and version in _KNOWN_SCHEMA_VERSIONS and tables == _KNOWN_TABLE_NAMES:
        expected = _expected_table_columns(version)
        mismatched = [
            name for name in _KNOWN_TABLE_NAMES if _table_columns(conn, name) != expected[name]
        ]
        if not mismatched:
            return
        raise ForeignDatabaseError(
            f"{db_path}: an existing file matches a Bindle work ledger's "
            f"table names at user_version={version}, but the column shape "
            f"of {sorted(mismatched)} does not match — refusing to treat "
            "it as a Bindle-owned or migratable ledger. Move or remove "
            "the existing file yourself if it is safe to replace, or "
            "investigate what created it."
        )

    raise ForeignDatabaseError(
        f"{db_path}: an existing file occupies the work ledger path but is "
        "not recognizable as a Bindle-owned or migratable work ledger "
        f"(application_id={app_id}, user_version={version}, "
        f"tables={sorted(tables)}) — refusing to create or migrate a "
        "schema over it. Move or remove the existing file yourself if it "
        "is safe to replace, or investigate what created it."
    )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        # One transaction: in autocommit each CREATE TABLE commits alone, so a
        # mid-way failure would leave user_version 0 with a partial schema and
        # every later connect() would fail recreating tables. PRAGMA
        # user_version is rolled back by ROLLBACK like ordinary DDL/DML on this
        # SQLite/Python.
        with _transaction(conn):
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)
            # PRAGMA takes no bind parameters; value is a fixed constant.
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    elif version == 1:
        _migrate_v1_to_v2(conn)
    elif version == 2:
        _migrate_v2_to_v3(conn)
    elif version != _SCHEMA_VERSION:
        raise SchemaVersionError(
            f"ledger at schema version {version}, expected {_SCHEMA_VERSION}"
        )

    # Stamped here, not per branch, so an already-current pre-marker database is
    # still adopted; safe after `_verify_ownership`, and idempotent to reissue.
    conn.execute(f"PRAGMA application_id = {_APPLICATION_ID}")


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Migrate a version-1 database in place, to the current `_SCHEMA_VERSION`.

    SQLite cannot `ALTER` a `CHECK` or add `NOT NULL` to a column, so this uses
    the standard table-rebuild sequence (specs/002 research.md, "Decision:
    schema migration from version 1 to version 2"). `PRAGMA foreign_keys` is a
    no-op inside a transaction, so enforcement is turned off around the rebuild
    (the other tables hold live `REFERENCES work_items(id)` rows), restored
    afterward, and `PRAGMA foreign_key_check` verifies integrity rather than
    silently skipping it.

    Existing rows are backfilled to `type = 'task'` with `parent_id` NULL (v1
    had no milestones), and any live row's NULL `created_at` is backfilled from
    its `updated_at` exactly as `_migrate_v2_to_v3` does, because the shared
    current shape includes v3's `created_at` CHECK. Rebuilds straight to
    `_work_items_create_sql`'s shape, never an intermediate v2 shape. One
    transaction, so a crash leaves the original v1 database intact.
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with _transaction(conn):
            conn.execute("ALTER TABLE work_items ADD COLUMN type TEXT")
            conn.execute("ALTER TABLE work_items ADD COLUMN parent_id TEXT")
            conn.execute("ALTER TABLE work_items ADD COLUMN description TEXT")
            conn.execute("UPDATE work_items SET type = 'task' WHERE type IS NULL")
            conn.execute(
                "UPDATE work_items SET created_at = updated_at "
                "WHERE created_at IS NULL AND archived_at IS NULL"
            )
            conn.execute(_work_items_create_sql("work_items_new"))
            conn.execute(
                "INSERT INTO work_items_new "
                "(id, type, parent_id, title, description, status, superseded_by, "
                "source_kind, source_locator, source_promoted_by, created_at, "
                "updated_at, archived_at) "
                "SELECT id, type, parent_id, title, description, status, superseded_by, "
                "source_kind, source_locator, source_promoted_by, created_at, "
                "updated_at, archived_at "
                "FROM work_items"
            )
            conn.execute("DROP TABLE work_items")
            conn.execute("ALTER TABLE work_items_new RENAME TO work_items")
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        integrity_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity_violations:
            raise SchemaVersionError(
                f"v1->v2 migration left dangling foreign keys: {integrity_violations}"
            )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Migrate a version-2 database to version 3 in place.

    Installs `CHECK (archived_at IS NOT NULL OR created_at IS NOT NULL)`
    (specs/003 research.md, "Decision: created_at NOT NULL for live rows"): the
    published Symphony projection's `created_at` is `NOT NULL` and sourced
    verbatim from `work_items.created_at`, which v2 did not guarantee for a live
    row. No exposed method produces that state, but a hand-restored or
    externally written ledger could, and `publish()`'s insert would then fail.

    Backfills a live row's NULL `created_at` from its own `updated_at` (never a
    value invented at migration time), then rebuilds the table as
    `_migrate_v1_to_v2` does, since SQLite cannot `ALTER` a `CHECK` onto an
    existing table. An archived row's deliberately cleared `created_at` is left
    untouched: the backfill excludes it and the CHECK permits it.
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with _transaction(conn):
            conn.execute(
                "UPDATE work_items SET created_at = updated_at "
                "WHERE created_at IS NULL AND archived_at IS NULL"
            )
            conn.execute(_work_items_create_sql("work_items_new"))
            conn.execute(
                "INSERT INTO work_items_new "
                "(id, type, parent_id, title, description, status, superseded_by, "
                "source_kind, source_locator, source_promoted_by, created_at, "
                "updated_at, archived_at) "
                "SELECT id, type, parent_id, title, description, status, superseded_by, "
                "source_kind, source_locator, source_promoted_by, created_at, "
                "updated_at, archived_at "
                "FROM work_items"
            )
            conn.execute("DROP TABLE work_items")
            conn.execute("ALTER TABLE work_items_new RENAME TO work_items")
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        integrity_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity_violations:
            raise SchemaVersionError(
                f"v2->v3 migration left dangling foreign keys: {integrity_violations}"
            )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def connect(repo_root: str) -> sqlite3.Connection:
    """Open a short-lived ledger connection, schema bootstrapped or verified.

    `isolation_level=None` is autocommit: a single statement commits on its own,
    and a multi-statement mutation wraps itself in `BEGIN IMMEDIATE` / `COMMIT`
    (research.md, "Decision: transaction boundaries"). The caller must close the
    connection. `WorkLedger`'s methods are the normal entry point; this is
    exposed for direct SQL inspection, tests, and several statements on one
    connection.
    """
    db_path = ledger_path(repo_root)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    # Read before sqlite3.connect(), which creates a 0-byte file for a new path.
    path_existed_before = os.path.exists(db_path)
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 2000")
        if not path_existed_before:
            # Stamp ownership first so a crash leaves a file a retry recognizes.
            conn.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        # Verify before WAL: journal_mode writes the header of a foreign file.
        _verify_ownership(conn, db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        _ensure_schema(conn)
    except BaseException:
        # Close explicitly; a lingering connection can leave the DB "locked".
        conn.close()
        raise
    return conn


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _local_branch_exists(repo_root: str, branch: str) -> bool:
    """Whether `branch` exists as a local ref in `repo_root`.

    Runs a read-only `git show-ref --verify --quiet` with `cwd=repo_root` (never
    the invoking worktree), for `reconcile()`'s `stale_claim` check (FR-009).
    Deliberately not `repo.py`'s `_git`, which raises on nonzero exit; a missing
    branch is an ordinary outcome here.
    """
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _registered_worktree_paths(repo_root: str) -> set[str] | None:
    """Paths Git registers as live worktrees of `repo_root`.

    A stricter staleness signal for `reconcile()`'s `stale_claim` check (FR-009)
    than `os.path.isdir`, which cannot tell a live worktree from an ordinary
    directory at the recorded path. Parses multi-block porcelain output, so it
    does not reuse `repo.py`'s single-value `_git`. Read-only.

    Returns `None`, distinct from an empty set, when Git cannot enumerate
    worktrees for `repo_root` (nonzero exit, e.g. the plain temporary directory
    most tests use), so `reconcile()` falls back to the `os.path.isdir`
    heuristic instead of calling every claim stale. Real use always has a Git
    common directory.

    Porcelain shape (observed): one block per worktree, starting with `worktree
    <path>`, then attribute lines (`HEAD`, `branch`/`bare`/`detached`, optional
    `locked [reason]` and `prunable [reason]`), blocks separated by a blank
    line.

    - A `locked` worktree is live and included.
    - A `prunable` worktree is excluded: after a bare `rm -rf` of a worktree
      directory (skipping `git worktree remove`), Git keeps its entry, annotated
      `prunable`, until `git worktree prune` -- even if an unrelated directory
      is later created at that path. Including it would readmit the "ordinary
      directory mistaken for a live worktree" case this check exists to close.

    Paths are `os.path.realpath`-normalized (Git already reports canonical
    paths) so a caller can compare its own realpath'd `worktree_path` directly.
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    paths: set[str] = set()
    for block in result.stdout.strip("\n").split("\n\n"):
        lines = block.splitlines()
        if not lines or not lines[0].startswith("worktree "):
            continue
        if any(line.startswith("prunable") for line in lines[1:]):
            continue
        paths.add(os.path.realpath(lines[0][len("worktree ") :]))
    return paths


@contextlib.contextmanager
def _transaction(conn: sqlite3.Connection):
    """Run a multi-statement mutation in one `BEGIN IMMEDIATE` transaction.

    Rolled back on any exception. `IMMEDIATE` (not deferred) so lock acquisition
    fails fast on contention. A single-statement mutation does not need this:
    `connect()`'s autocommit already makes it atomic.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


@dataclasses.dataclass(frozen=True)
class WorkItem:
    """One row of `work_items`, in full or thinned-by-archival form.

    Archival (data-model.md, "Work Item") clears `title`, `description`,
    `source_kind`, `source_locator`, `source_promoted_by`, and `created_at` to
    `None`; `id`, `type`, `status`, `superseded_by`, `updated_at`, and
    `archived_at` stay populated. `parent_id` (a task's milestone; always `None`
    for a milestone) is never cleared, and no operation reassigns it.
    """

    id: str
    type: str
    parent_id: str | None
    title: str | None
    description: str | None
    status: str
    superseded_by: str | None
    source_kind: str | None
    source_locator: str | None
    source_promoted_by: str | None
    created_at: str | None
    updated_at: str
    archived_at: str | None


@dataclasses.dataclass(frozen=True)
class ReconciliationFinding:
    """One finding from a read-only Reconciliation Report (FR-010).

    `finding` is `stale_claim` | `corrupt_claim` | `dangling_blocker` |
    `duplicate_source` | `cycle_detected` (data-model.md, "Reconciliation
    Report"). `item_id` is `None` when the finding concerns a set of items or
    the whole database (`duplicate_source`, a whole-file `corrupt_claim`).
    """

    item_id: str | None
    finding: str
    detail: str


@dataclasses.dataclass(frozen=True)
class ProjectedWorkItem:
    """Coordinator-facing projection of one Work Item (contracts/coordinator-projection.md).

    Coordinator-agnostic: no Symphony-specific fields or
    `active_states`/`terminal_states` strings, which belong to an external
    WORKFLOW.md this module never sees; an adapter maps `terminal`/`eligible`
    onto them.
    """

    id: str
    title: str | None
    terminal: bool
    eligible: bool


@dataclasses.dataclass(frozen=True)
class ExternalProjectionRow:
    """One row of the published, external Symphony-facing projection.

    Contract: contracts/symphony-projection-v1.md. A separate contract from
    `ProjectedWorkItem`, never sharing its schema (FR-019). `status` is the raw
    string (`open` | `done` | `superseded`); `dispatchable` is computed in
    Bindle (FR-016) so external readers never evaluate blocking or claim state.
    `identifier` (FR-015) is a deterministic, workspace-name-safe derivation of
    `id`, never an independent identity (research.md, "Decision: identifier
    derivation for external workspace naming"). `created_at` is copied verbatim
    from the canonical row, never synthesized, because Symphony ranks eligible
    candidates by it; it is typed `str` because the query is restricted to
    `archived_at IS NULL` rows, which v3's `CHECK` guarantees carry a non-`NULL`
    `created_at`.
    """

    id: str
    identifier: str
    title: str | None
    description: str | None
    status: str
    dispatchable: bool
    created_at: str


@dataclasses.dataclass(frozen=True)
class EvidencePointer:
    """One `work_item_evidence` row read back (specs/004 data-model.md)."""

    kind: str
    value: str
    recorded_at: str
    note: str | None


@dataclasses.dataclass(frozen=True)
class ClaimInfo:
    """The single claim row for a work item (specs/004 data-model.md).

    `worktree_path`/`branch` are `None` when not supplied at claim time.
    """

    owner: str
    claimed_at: str
    worktree_path: str | None
    branch: str | None


_WORK_ITEM_COLUMNS = (
    "id",
    "type",
    "parent_id",
    "title",
    "description",
    "status",
    "superseded_by",
    "source_kind",
    "source_locator",
    "source_promoted_by",
    "created_at",
    "updated_at",
    "archived_at",
)


def _row_to_work_item(row: tuple) -> WorkItem:
    return WorkItem(*row)


# Whether the referenced item (aliased `dep` in every query) still blocks, by
# type-aware status (specs/002 data-model.md, "Dependency resolution"): a task
# resolves at done/superseded, a milestone at accepted/superseded (never
# review/open); a dangling reference (`dep.id IS NULL`) still blocks. Shared by
# every blocking/eligibility query so the rule is defined exactly once.
_STILL_BLOCKING_CONDITION = """(
                      dep.id IS NULL OR NOT (
                        (dep.type = 'task' AND dep.status IN ('done', 'superseded'))
                        OR (dep.type = 'milestone' AND dep.status IN ('accepted', 'superseded'))
                      )
                    )"""


def is_dispatchable(status: str, claimed: bool, blocked: bool) -> bool:
    """Task dispatchability: `status == 'open'` and not claimed and not blocked.

    Pure and I/O-free so it evaluates identically against live ledger state and
    a read-only forecast (specs/005-work-state-visibility). Takes no `type`:
    callers already scope to `type == 'task'`.
    """
    return status == "open" and not claimed and not blocked


def _review_ready_sql(id_expr: str) -> str:
    """SQL boolean: is the milestone named by `id_expr` review-ready?

    See specs/002 data-model.md, "Review readiness". `id_expr` is substituted
    into the query text, so it must be one of two fixed internal literals, never
    caller data: `"?"` for a standalone query (`is_review_ready`, bound three
    times to the same id), or `"work_items.id"` as a correlated reference inside
    `mark_in_review`'s `UPDATE ... WHERE`.

    The second form makes readiness hold at the moment of the same atomic update
    (FR-010); a separate `is_review_ready()` pre-check would leave a race
    window.
    """
    return f"""(
        NOT EXISTS (
          SELECT 1 FROM work_item_blocked_by e
          LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
          WHERE e.work_item_id = {id_expr}
            AND {_STILL_BLOCKING_CONDITION}
        )
        AND EXISTS (
          SELECT 1 FROM work_items c WHERE c.parent_id = {id_expr}
        )
        AND NOT EXISTS (
          SELECT 1 FROM work_items c
          WHERE c.parent_id = {id_expr}
            AND NOT (
              c.status = 'superseded'
              OR (
                c.status = 'done'
                AND EXISTS (
                  SELECT 1 FROM work_item_evidence ev WHERE ev.work_item_id = c.id
                )
              )
            )
        )
      )"""


class WorkLedger:
    """The ledger for one repository, identified by its `repo_root`.

    A cheap handle holding no connection or cache; each method opens and closes
    its own short-lived connection.
    """

    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root

    def _connect(self) -> sqlite3.Connection:
        return connect(self.repo_root)

    def ensure_schema(self) -> None:
        """Bootstrap or verify this repository's ledger schema, eagerly.

        Every other method already does this via `connect()`; this lets a caller
        (`bindle init`, see `cli.py`) ask for schema readiness as a standalone
        step without touching `_connect()`. Creates
        `.bindle-work/ledger.sqlite3` at `_SCHEMA_VERSION` on a fresh
        repository; on an existing one, verifies and migrates forward in place
        (`_migrate_v1_to_v2`/`_migrate_v2_to_v3`). Never creates, claims, or
        transitions a work item; existing rows are preserved except for a
        migration's own backfills.
        """
        self._connect().close()

    def create_work_item(
        self,
        id: str,
        title: str,
        source_kind: str,
        source_locator: str,
        source_promoted_by: str | None = None,
        blocked_by: Sequence[str] = (),
        type: str = "task",
        parent_id: str | None = None,
        description: str | None = None,
    ) -> None:
        """Create a Work Item; the only operation that does so (FR-002/FR-003).

        `status` is always `open`. With `blocked_by`, the item and its
        dependency edges are created in one transaction, so an item is never
        recorded with only some of its declared dependencies.

        `type` defaults to `"task"`. A `parent_id` must name an existing
        `type='milestone'` row that is currently `open` (specs/002
        FR-002/FR-003/FR-003a), else `ValueError` before any row is written;
        membership is frozen once a milestone leaves `open`, so its accepted or
        under-review child set cannot change underneath a human decision. A
        milestone naming a `parent_id` is instead rejected by the schema `CHECK`
        (`sqlite3.IntegrityError`).

        The parent status check runs inside the same `BEGIN IMMEDIATE`
        transaction as the `INSERT`, not before it: `status` is mutable (`open
        -> review` at any time), so a separate pre-check would let a concurrent
        `mark_in_review()` invalidate it before the write. `BEGIN IMMEDIATE`
        holds the write lock across both.
        """
        now = _now()
        insert_item = (
            "INSERT INTO work_items "
            "(id, type, parent_id, title, description, status, source_kind, "
            "source_locator, source_promoted_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)"
        )
        params = (
            id,
            type,
            parent_id,
            title,
            description,
            source_kind,
            source_locator,
            source_promoted_by,
            now,
            now,
        )

        conn = self._connect()
        try:
            with _transaction(conn):
                if parent_id is not None:
                    parent_row = conn.execute(
                        "SELECT type, status FROM work_items WHERE id = ?",
                        (parent_id,),
                    ).fetchone()
                    if parent_row is None or parent_row[0] != "milestone":
                        raise ValueError(
                            f"parent_id {parent_id!r} does not name an existing "
                            "milestone work item"
                        )
                    if parent_row[1] != "open":
                        raise ValueError(
                            f"parent_id {parent_id!r} names a milestone that is "
                            f"not open (status={parent_row[1]!r}); a task may "
                            "only be attached to an open milestone"
                        )
                conn.execute(insert_item, params)
                for blocked_on_id in blocked_by:
                    conn.execute(
                        "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                        "VALUES (?, ?)",
                        (id, blocked_on_id),
                    )
        finally:
            conn.close()

    def get_work_item(self, id: str) -> WorkItem | None:
        """Read a single Work Item by id, or `None` if it does not exist."""
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT {', '.join(_WORK_ITEM_COLUMNS)} FROM work_items WHERE id = ?",
                (id,),
            ).fetchone()
            return _row_to_work_item(row) if row is not None else None
        finally:
            conn.close()

    def resync_declarative_fields(
        self, id: str, title: str | None, description: str | None
    ) -> bool:
        """Re-sync a Work Item's `title`/`description` from a fresh source read.

        The only mutation a reloading caller (e.g. a Spec Kit `tasks.md` loader)
        may perform on an id it already recognizes (specs/003 research.md,
        "Decision: how a reload updates an existing work item"): it never
        touches `status`, `type`, `parent_id`, `source_*`, any claim, or any
        evidence, so a reload cannot disturb runtime-owned state.
        Source-agnostic: it does not know what any `source_kind` means.

        Guarded on `archived_at IS NULL`: an archived row's
        `title`/`description` are already `NULL`, so resync is a no-op, not a
        failure. Returns `True` iff exactly one row was updated; `False` if `id`
        does not exist or is archived.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE work_items SET title = ?, description = ?, updated_at = ? "
                "WHERE id = ? AND archived_at IS NULL",
                (title, description, _now(), id),
            )
            return cursor.rowcount == 1
        finally:
            conn.close()

    def list_work_items(self) -> list[WorkItem]:
        """List every Work Item, active and archived, ordered by id."""
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT {', '.join(_WORK_ITEM_COLUMNS)} FROM work_items ORDER BY id"
            ).fetchall()
            return [_row_to_work_item(row) for row in rows]
        finally:
            conn.close()

    def add_blocked_by(self, work_item_id: str, blocked_on_id: str) -> None:
        """Declare that `work_item_id` is blocked on `blocked_on_id`.

        No validation here: the schema's `CHECK (work_item_id != blocked_on_id)`
        and foreign keys (enforced because `connect()` sets `PRAGMA foreign_keys
        = ON`) reject a self-cycle or dangling target by raising
        `sqlite3.IntegrityError`.
        """
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                "VALUES (?, ?)",
                (work_item_id, blocked_on_id),
            )
        finally:
            conn.close()

    def is_blocked(self, work_item_id: str) -> bool:
        """Whether `work_item_id` is currently blocked.

        Type-aware via `_STILL_BLOCKING_CONDITION`: any `blocked_by` row whose
        target has not reached its own type's resolved state, or resolves to no
        row (dangling, conservatively still blocking per FR-021), counts.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                f"""
                SELECT EXISTS (
                  SELECT 1 FROM work_item_blocked_by e
                  LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
                  WHERE e.work_item_id = ?
                    AND {_STILL_BLOCKING_CONDITION}
                )
                """,
                (work_item_id,),
            ).fetchone()
            return bool(row[0])
        finally:
            conn.close()

    def list_blocking(self, work_item_id: str) -> list[str]:
        """List ids blocking `work_item_id`, by `blocked_on_id` (specs/004).

        Uses the same `_STILL_BLOCKING_CONDITION` as `is_blocked()`, so the two
        never disagree; a dangling reference is included as declared. Returns
        `[]`, never raises, when not blocked or when `work_item_id` does not
        exist.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT e.blocked_on_id FROM work_item_blocked_by e
                LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
                WHERE e.work_item_id = ?
                  AND {_STILL_BLOCKING_CONDITION}
                ORDER BY e.blocked_on_id
                """,
                (work_item_id,),
            ).fetchall()
            return [row[0] for row in rows]
        finally:
            conn.close()

    def is_claimed(self, work_item_id: str) -> bool:
        """Whether `work_item_id` has a claim row (not a column)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM work_item_claims WHERE work_item_id = ?)",
                (work_item_id,),
            ).fetchone()
            return bool(row[0])
        finally:
            conn.close()

    def list_available_work_items(self) -> list[str]:
        """List the ids of every **task** currently available to start, by `id`.

        Available means `status = 'open'` AND not claimed AND not blocked
        (data-model.md, "Available to start"). Restricted to `type = 'task'` in
        the `WHERE` clause (specs/002; mirrors `generate_projection()`, FR-017):
        a milestone is a human acceptance unit, never something to "start", and
        a predicate cannot be bypassed the way a post-filter can.

        Per-row inclusion is decided in Python by `is_dispatchable()`, the sole
        authoritative dispatchability rule, shared with
        `work_status.build_forecast()` (specs/005 research.md,
        "dispatchable-next shares one authoritative predicate"), rather than
        re-expressed in SQL. `wi.status = 'open'` stays in `WHERE` only as a
        candidate-narrowing filter: `claimed`/`blocked` are correlated `EXISTS`
        in the `SELECT` list, so without it SQLite would evaluate both for every
        `done`/`superseded` task that `is_dispatchable()` rejects anyway.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT
                  wi.id,
                  wi.status,
                  EXISTS (
                    SELECT 1 FROM work_item_claims c WHERE c.work_item_id = wi.id
                  ) AS claimed,
                  EXISTS (
                    SELECT 1 FROM work_item_blocked_by e
                    LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
                    WHERE e.work_item_id = wi.id
                      AND {_STILL_BLOCKING_CONDITION}
                  ) AS blocked
                FROM work_items wi
                WHERE wi.type = 'task' AND wi.status = 'open'
                ORDER BY wi.id
                """
            ).fetchall()
            return [
                row[0]
                for row in rows
                if is_dispatchable(row[1], bool(row[2]), bool(row[3]))
            ]
        finally:
            conn.close()

    def mark_done(self, work_item_id: str) -> bool:
        """Transition `work_item_id` to `done`.

        A single guarded `UPDATE ... WHERE status = 'open'`, already atomic
        under `connect()`'s autocommit, so no `_transaction`. Returns `True` iff
        exactly one row was updated; `False` (a no-op, not an error) if the item
        does not exist or is not `open`, which keeps a double-transition race
        from silently double-applying.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE work_items SET status = 'done', updated_at = ? "
                "WHERE id = ? AND status = 'open'",
                (_now(), work_item_id),
            )
            return cursor.rowcount == 1
        finally:
            conn.close()

    def mark_superseded(self, work_item_id: str, superseded_by: str) -> bool:
        """Transition `work_item_id` to `superseded` by `superseded_by`.

        Same guarded shape and return meaning as `mark_done`; `superseded_by` is
        required by the status/superseded_by pairing `CHECK`.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE work_items SET status = 'superseded', superseded_by = ?, "
                "updated_at = ? WHERE id = ? AND status = 'open'",
                (superseded_by, _now(), work_item_id),
            )
            return cursor.rowcount == 1
        finally:
            conn.close()

    def is_review_ready(self, work_item_id: str) -> bool:
        """Whether the milestone `work_item_id` is ready for human review.

        Per specs/002 data-model.md, "Review readiness", true iff (a) the
        milestone is not blocked, (b) it has at least one child task, and (c)
        every child is `superseded`, or `done` with at least one evidence
        pointer. Purely derived, never stored. Only meaningful for a
        `type='milestone'` row; for a task it always reports `False`.

        `mark_in_review` re-evaluates this same condition atomically in its own
        `UPDATE` (via `_review_ready_sql`); this method is only for inspecting
        readiness without attempting a transition, not the enforcement of
        FR-010.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT {_review_ready_sql('?')}",
                (work_item_id, work_item_id, work_item_id),
            ).fetchone()
            return bool(row[0])
        finally:
            conn.close()

    def mark_in_review(self, work_item_id: str) -> bool:
        """Transition milestone `work_item_id` from `open` to `review` (FR-010).

        The review-readiness condition (`_review_ready_sql`) is embedded in this
        `UPDATE`'s `WHERE`, so a change to a child task cannot land between
        "checked ready" and "transitioned". Returns `True` iff one row was
        updated; `False` if the item does not exist, is not a milestone, is not
        `open`, or is not (or no longer) review-ready.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                f"""
                UPDATE work_items SET status = 'review', updated_at = ?
                WHERE id = ? AND type = 'milestone' AND status = 'open'
                  AND {_review_ready_sql('work_items.id')}
                """,
                (_now(), work_item_id),
            )
            return cursor.rowcount == 1
        finally:
            conn.close()

    def decline_review(self, work_item_id: str) -> bool:
        """Transition milestone `work_item_id` from `review` back to `open`.

        The "changes requested" outcome (spec.md US4): touches only this
        milestone's row, never a child task's status, evidence, or identity.
        Returns `True` iff one row was updated; `False` if the item does not
        exist, is not a milestone, or is not `review`.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE work_items SET status = 'open', updated_at = ? "
                "WHERE id = ? AND type = 'milestone' AND status = 'review'",
                (_now(), work_item_id),
            )
            return cursor.rowcount == 1
        finally:
            conn.close()

    def accept_milestone(self, work_item_id: str) -> bool:
        """Transition milestone `work_item_id` from `review` to `accepted`.

        `accepted` is the milestone's terminal state (FR-005). Returns `True`
        iff one row was updated; `False` if the item does not exist, is not a
        milestone, or is not `review`.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE work_items SET status = 'accepted', updated_at = ? "
                "WHERE id = ? AND type = 'milestone' AND status = 'review'",
                (_now(), work_item_id),
            )
            return cursor.rowcount == 1
        finally:
            conn.close()

    def claim(
        self,
        work_item_id: str,
        owner: str,
        worktree_path: str | None = None,
        branch: str | None = None,
    ) -> bool:
        """Attempt to claim a Work Item (FR-007, FR-018); `True` iff acquired.

        A single `INSERT INTO work_item_claims` is the sole arbitration
        (data-model.md, "Claim atomicity contract"): the primary key on
        `work_item_id` lets exactly one of any number of concurrent attempts
        succeed. Returns `False`, never an error, when a claim row already
        exists. A `work_item_id` with no `work_items` row raises a different
        `sqlite3.IntegrityError` (foreign-key violation), which is re-raised.

        The cases are told apart by `exc.sqlite_errorcode` (Python 3.11+, the
        repository minimum), not `str(exc)`, whose wording is not stable API. A
        conflict on `PRIMARY KEY (work_item_id)` reports
        `SQLITE_CONSTRAINT_PRIMARYKEY` (not the generic
        `SQLITE_CONSTRAINT_UNIQUE`); only that means "already claimed".
        """
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO work_item_claims "
                "(work_item_id, owner, claimed_at, worktree_path, branch) "
                "VALUES (?, ?, ?, ?, ?)",
                (work_item_id, owner, _now(), worktree_path, branch),
            )
            return True
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY:
                return False
            raise
        finally:
            conn.close()

    def release_claim(self, work_item_id: str, owner: str) -> None:
        """Release a claim, by its recorded owner only (FR-007).

        Deleting zero rows (already released, or `owner` mismatch) is a no-op,
        never an error (data-model.md, "Safe release").
        """
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM work_item_claims WHERE work_item_id = ? AND owner = ?",
                (work_item_id, owner),
            )
        finally:
            conn.close()

    def override_release_claim(
        self, work_item_id: str, note: str | None = None
    ) -> None:
        """Override-release a claim, unconditional on owner (FR-019).

        Legitimate only when justified by an observed `stale_claim` or
        `corrupt_claim` finding (data-model.md, "Staleness"); that is a process
        expectation on the caller, not verified here. Deletes the claim without
        an `owner` filter (the recorded owner may be unreachable) and, only when
        `note` is given, records an `other` Evidence Pointer in the same
        transaction.

        Does NOT grant the caller a claim: the item merely becomes claimable
        again, and a caller wanting it must separately `claim()` (spec.md, Edge
        Cases).
        """
        conn = self._connect()
        try:
            with _transaction(conn):
                conn.execute(
                    "DELETE FROM work_item_claims WHERE work_item_id = ?",
                    (work_item_id,),
                )
                if note is not None:
                    conn.execute(
                        "INSERT INTO work_item_evidence "
                        "(work_item_id, kind, value, recorded_at, note) "
                        "VALUES (?, 'other', 'claim-override', ?, ?)",
                        (work_item_id, _now(), note),
                    )
        finally:
            conn.close()

    def add_evidence(
        self, work_item_id: str, kind: str, value: str, note: str | None = None
    ) -> None:
        """Attach an Evidence Pointer to a Work Item (FR-008).

        Append-only: no `UPDATE`/`DELETE` path exists for a pointer
        (data-model.md's Evidence Pointer invariant), so the pointer of a
        rebased, squashed, or deleted branch stays as a historical observation.
        `kind` is enforced by the schema's `CHECK`, not re-validated here.
        """
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO work_item_evidence "
                "(work_item_id, kind, value, recorded_at, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (work_item_id, kind, value, _now(), note),
            )
        finally:
            conn.close()

    def has_qualifying_evidence(self, work_item_id: str) -> bool:
        """Whether `work_item_id` has at least one evidence pointer of any kind.

        Per specs/002 data-model.md. Read-only; does not gate `mark_done`
        (evidence stays optional, 001 FR-008). Consumed by `is_review_ready` for
        a task's parent milestone.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM work_item_evidence WHERE work_item_id = ?)",
                (work_item_id,),
            ).fetchone()
            return bool(row[0])
        finally:
            conn.close()

    def list_evidence(self, work_item_id: str) -> list[EvidencePointer]:
        """Every Evidence Pointer for `work_item_id`, in insertion order.

        Per specs/004 data-model.md. Ordered by `evidence_id`, not
        `recorded_at`, which can tie for pointers recorded in the same instant.
        Returns `[]` for a nonexistent `work_item_id`.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT kind, value, recorded_at, note FROM work_item_evidence "
                "WHERE work_item_id = ? ORDER BY evidence_id",
                (work_item_id,),
            ).fetchall()
            return [EvidencePointer(*row) for row in rows]
        finally:
            conn.close()

    def get_claim(self, work_item_id: str) -> ClaimInfo | None:
        """Claim row for `work_item_id`, or `None` (specs/004 data-model.md)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT owner, claimed_at, worktree_path, branch "
                "FROM work_item_claims WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
            return ClaimInfo(*row) if row is not None else None
        finally:
            conn.close()

    def reconcile(self) -> list[ReconciliationFinding]:
        """Run a read-only Reconciliation Report (FR-010).

        Compares recorded state against observed repository state (claim
        `worktree_path` registered as a live Git worktree, claim `branch`
        existing as a local ref; FR-009) and internal consistency (claim row
        shape, database integrity, dangling blocking edges, duplicate sources,
        blocking cycles), per data-model.md's "Reconciliation Report". Every
        query is a `SELECT` and every Git call read-only; a stale or corrupt
        finding does not by itself change whether an item is computed as
        available (research.md, "Decision: claim safety").

        Covers `stale_claim`, `corrupt_claim`, `dangling_blocker`,
        `duplicate_source`, and `cycle_detected`. `dangling_evidence` is
        deliberately not implemented: verifying an Evidence Pointer's
        `branch`/`commit` value would need to validate arbitrary SHAs and PR
        references, a distinct check from claim-branch existence.
        """
        findings: list[ReconciliationFinding] = []
        conn = self._connect()
        try:
            # stale_claim (FR-009, data-model.md "Staleness"): worktree_path no
            # longer a registered Git worktree (see
            # `_registered_worktree_paths`; os.path.isdir is only the fallback
            # when repo_root is not a Git repo), or a recorded branch that no
            # longer exists as a local ref. Branch-only claims are inspected
            # too. One claim yields at most one finding, worktree checked first.
            # An owner who stopped working while worktree/branch still exist is
            # undetectable by absence checks.
            # One `git worktree list` per reconcile(), reused for every claim.
            registered_worktrees = _registered_worktree_paths(self.repo_root)
            for work_item_id, worktree_path, branch in conn.execute(
                "SELECT work_item_id, worktree_path, branch FROM work_item_claims "
                "WHERE worktree_path IS NOT NULL OR branch IS NOT NULL"
            ).fetchall():
                if worktree_path is not None:
                    if registered_worktrees is not None:
                        worktree_stale = (
                            os.path.realpath(worktree_path) not in registered_worktrees
                        )
                        detail = (
                            f"worktree_path {worktree_path!r} is not a "
                            "currently registered Git worktree"
                        )
                    else:
                        worktree_stale = not os.path.isdir(worktree_path)
                        detail = f"worktree_path {worktree_path!r} does not exist"
                else:
                    worktree_stale = False
                    detail = ""

                if worktree_stale:
                    findings.append(
                        ReconciliationFinding(
                            item_id=work_item_id,
                            finding="stale_claim",
                            detail=detail,
                        )
                    )
                elif branch is not None and not _local_branch_exists(
                    self.repo_root, branch
                ):
                    findings.append(
                        ReconciliationFinding(
                            item_id=work_item_id,
                            finding="stale_claim",
                            detail=f"branch {branch!r} does not exist",
                        )
                    )

            # corrupt_claim (a): NULL/empty owner or claimed_at. Unreachable
            # through claim() (NOT NULL); defense in depth against bypassed
            # constraints or file tampering.
            for work_item_id, owner, claimed_at in conn.execute(
                "SELECT work_item_id, owner, claimed_at FROM work_item_claims "
                "WHERE owner IS NULL OR owner = '' "
                "OR claimed_at IS NULL OR claimed_at = ''"
            ).fetchall():
                findings.append(
                    ReconciliationFinding(
                        item_id=work_item_id,
                        finding="corrupt_claim",
                        detail=(
                            f"claim row for {work_item_id!r} has a missing or "
                            f"empty owner/claimed_at (owner={owner!r}, "
                            f"claimed_at={claimed_at!r})"
                        ),
                    )
                )

            # corrupt_claim (b): whole-database-file integrity check.
            integrity_result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity_result != "ok":
                findings.append(
                    ReconciliationFinding(
                        item_id=None,
                        finding="corrupt_claim",
                        detail=f"PRAGMA integrity_check reported: {integrity_result}",
                    )
                )

            for work_item_id, blocked_on_id in conn.execute(
                "SELECT e.work_item_id, e.blocked_on_id FROM work_item_blocked_by e "
                "LEFT JOIN work_items dep ON dep.id = e.blocked_on_id "
                "WHERE dep.id IS NULL"
            ).fetchall():
                findings.append(
                    ReconciliationFinding(
                        item_id=work_item_id,
                        finding="dangling_blocker",
                        detail=(
                            f"blocked_on_id {blocked_on_id!r} does not resolve "
                            "to any work item"
                        ),
                    )
                )

            # data-model.md's duplicate-source query, verbatim.
            for source_kind, source_locator, item_ids in conn.execute(
                "SELECT source_kind, source_locator, GROUP_CONCAT(id) AS item_ids "
                "FROM work_items WHERE archived_at IS NULL "
                "GROUP BY source_kind, source_locator HAVING COUNT(*) > 1"
            ).fetchall():
                findings.append(
                    ReconciliationFinding(
                        item_id=None,
                        finding="duplicate_source",
                        detail=(
                            f"source_kind={source_kind!r} "
                            f"source_locator={source_locator!r} shared by "
                            f"items: {item_ids}"
                        ),
                    )
                )

            # data-model.md's "Cycle detection" recursive CTE, verbatim.
            for (start_id,) in conn.execute(
                """
                WITH RECURSIVE reachable(start_id, id) AS (
                  SELECT work_item_id, blocked_on_id FROM work_item_blocked_by
                  UNION
                  SELECT r.start_id, e.blocked_on_id
                  FROM reachable r JOIN work_item_blocked_by e ON e.work_item_id = r.id
                )
                SELECT DISTINCT start_id FROM reachable WHERE id = start_id
                """
            ).fetchall():
                findings.append(
                    ReconciliationFinding(
                        item_id=start_id,
                        finding="cycle_detected",
                        detail=(
                            f"{start_id!r} can reach itself through declared "
                            "blocked_by edges"
                        ),
                    )
                )
        finally:
            conn.close()
        return findings

    def generate_projection(self) -> list[ProjectedWorkItem]:
        """Generate a disposable, coordinator-facing projection (FR-013/FR-014).

        Per contracts/coordinator-projection.md (extended by specs/002's
        coordinator-projection-v2.md): only non-archived **task** rows, filtered
        in `WHERE` (`archived_at IS NULL AND wi.type = 'task'`, FR-017) so no
        milestone is ever included and a caller cannot bypass it by reading the
        table. `terminal` is `True` iff `status` is `done` or `superseded`;
        `eligible` is the Available-to-start computation (data-model.md), so a
        blocked or claimed item is never presented as eligible to an adapter
        that would not re-check (Symphony's shipped `local` tracker, per the
        contract).

        Derived from one `SELECT` on one connection, with eligibility inline as
        `NOT EXISTS` subqueries, rather than combining
        `list_available_work_items()` with a second read: two reads left a
        window in which a claim could land between them, giving a stale
        `eligible=True` mixed with `id`/`title`/`status` from a later snapshot.

        This guarantees internal consistency of one projection, nothing more. A
        competing `claim()` can still land after the snapshot, so a coordinator
        MUST still attempt `claim()` before treating an item as acquired; the
        projection is advisory, never a reservation. Purely a read, ordered by
        `id`, so regenerating it from unchanged state yields an equal list
        (spec.md SC-005).
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT
                  wi.id,
                  wi.title,
                  wi.status,
                  (
                    wi.status = 'open'
                    AND NOT EXISTS (
                      SELECT 1 FROM work_item_claims c WHERE c.work_item_id = wi.id
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM work_item_blocked_by e
                      LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
                      WHERE e.work_item_id = wi.id
                        AND {_STILL_BLOCKING_CONDITION}
                    )
                  ) AS eligible
                FROM work_items wi
                WHERE wi.archived_at IS NULL
                  AND wi.type = 'task'
                ORDER BY wi.id
                """
            ).fetchall()
        finally:
            conn.close()
        return [
            ProjectedWorkItem(
                id=row[0],
                title=row[1],
                terminal=row[2] in ("done", "superseded"),
                eligible=bool(row[3]),
            )
            for row in rows
        ]

    def generate_external_projection(self) -> list[ExternalProjectionRow]:
        """Generate the row set for the published, external Symphony projection.

        A second, independent query rather than a transformation of
        `generate_projection()`: the published contract
        (contracts/symphony-projection-v1.md) is a physically separate artifact
        with its own shape and version, never coupled to `ProjectedWorkItem`
        (FR-019, research.md, "Decision: published projection storage location
        and format"). They share only the `_STILL_BLOCKING_CONDITION` fragment.

        Restricted in `WHERE` to non-archived task rows (`wi.archived_at IS NULL
        AND wi.type = 'task'`), so no milestone can appear (FR-014, SC-007).
        `dispatchable` is computed inline in the same `SELECT` for the
        one-snapshot reason in `generate_projection()`'s docstring. `created_at`
        is read straight off the canonical row, never derived. `identifier`
        (FR-015) replaces every `:` in `id` with `-`.

        Purely a read, ordered by `id`, so regenerating it from unchanged state
        yields an equal list (SC-006).
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT
                  wi.id,
                  wi.title,
                  wi.description,
                  wi.status,
                  wi.created_at,
                  (
                    wi.status = 'open'
                    AND NOT EXISTS (
                      SELECT 1 FROM work_item_claims c WHERE c.work_item_id = wi.id
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM work_item_blocked_by e
                      LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
                      WHERE e.work_item_id = wi.id
                        AND {_STILL_BLOCKING_CONDITION}
                    )
                  ) AS dispatchable
                FROM work_items wi
                WHERE wi.archived_at IS NULL AND wi.type = 'task'
                ORDER BY wi.id
                """
            ).fetchall()
        finally:
            conn.close()
        return [
            ExternalProjectionRow(
                id=row[0],
                identifier=row[0].replace(":", "-"),
                title=row[1],
                description=row[2],
                status=row[3],
                created_at=row[4],
                dispatchable=bool(row[5]),
            )
            for row in rows
        ]

    def archive_work_item(self, id: str) -> bool:
        """Archive a terminal work item in place (FR-020/FR-021, SC-008).

        Per data-model.md's "Archival" transaction: thins the row's
        non-essential columns to `NULL`, stamps `archived_at`, and in the same
        transaction deletes the item's own Evidence Pointers, its own declared
        `blocked_by` edges, and any lingering claim row (defensive). Edges other
        items declare against it are untouched, and `id`, `type`, `status`, and
        `superseded_by` are never cleared, so another item's blocking evaluation
        or a task's `parent_id` resolution naming this id keeps resolving as
        before (research.md, "Decision: retention"). A task's terminal set is
        `done`/`superseded`; a milestone's is `accepted`/`superseded` (specs/002
        FR-005).

        Two preconditions are embedded in the guarded `UPDATE`'s `WHERE`, inside
        the `BEGIN IMMEDIATE` transaction, rather than checked beforehand: a
        separate check would leave a check-then-act race window (as with
        `mark_in_review`'s FR-010). One atomic statement's row-count is the sole
        arbitration, since `BEGIN IMMEDIATE` holds SQLite's write lock
        throughout.

        - FR-015: a `type='milestone'` row is refused while any child
          (`parent_id` naming it) has a status outside `('done', 'superseded')`;
          a child is always a task and can never be `accepted`, so that status
          is not listed. Harmless for a task (no children), so not conditioned
          on `type`.
        - FR-015a: an attributed task (`parent_id IS NOT NULL`) is refused while
          its parent milestone is `open` or `review`, because archiving deletes
          the child's evidence rows and could silently invalidate the parent's
          review-readiness (or the evidence behind `mark_in_review`/
          `accept_milestone`). It is permitted once the parent is `accepted` or
          `superseded` (its children can no longer change) or when the task has
          no `parent_id`. A concurrent `accept_milestone(parent)` and
          `archive_work_item(child)` serialize to exactly two outcomes: archival
          sees the parent still `review` and is refused (accept then succeeds),
          or accept commits first and archival succeeds. Archiving under an
          `open`/`review` parent is unreachable in either ordering.

        Returns `True` iff the `UPDATE` matched a row: `id` exists, is in a
        terminal status for its type, is not yet archived, and satisfies both
        preconditions. Otherwise `False`, a guarded no-op (not an error) that
        skips the cleanup `DELETE`s. Re-archiving is a true no-op: `AND
        archived_at IS NULL` leaves `archived_at`/`updated_at` as the first
        archival set them (data-model.md, "`archived_at`... permanent").
        """
        now = _now()
        conn = self._connect()
        try:
            with _transaction(conn):
                cursor = conn.execute(
                    "UPDATE work_items AS wi SET title = NULL, description = NULL, "
                    "source_kind = NULL, source_locator = NULL, "
                    "source_promoted_by = NULL, "
                    "created_at = NULL, archived_at = ?, updated_at = ? "
                    "WHERE wi.id = ? AND wi.status IN ('done', 'accepted', 'superseded') "
                    "AND wi.archived_at IS NULL "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM work_items c WHERE c.parent_id = ? "
                    "  AND c.status NOT IN ('done', 'superseded')"
                    ") "
                    "AND ("
                    "  wi.parent_id IS NULL "
                    "  OR EXISTS ("
                    "    SELECT 1 FROM work_items p WHERE p.id = wi.parent_id "
                    "    AND p.status IN ('accepted', 'superseded')"
                    "  )"
                    ")",
                    (now, now, id, id),
                )
                archived = cursor.rowcount == 1
                if archived:
                    conn.execute(
                        "DELETE FROM work_item_evidence WHERE work_item_id = ?",
                        (id,),
                    )
                    conn.execute(
                        "DELETE FROM work_item_blocked_by WHERE work_item_id = ?",
                        (id,),
                    )
                    conn.execute(
                        "DELETE FROM work_item_claims WHERE work_item_id = ?",
                        (id,),
                    )
            return archived
        finally:
            conn.close()
