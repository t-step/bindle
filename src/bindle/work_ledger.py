"""Durable work ledger: a repository-scoped, SQLite-backed coordination
ledger for decomposed implementation work.

Implements the accepted design in specs/001-durable-work-ledger/ (spec.md,
plan.md, research.md, data-model.md, contracts/) — read those first for the
"why" behind anything here. In short: a small set of orthogonal
coordination facts per work item (status, blocking, claim, evidence, a
source pointer back to the spec/plan/task it was promoted from), backed by
one small SQLite database at the repository's Git common directory
(`RepoInfo.repo_root`, never the invoking worktree — see research.md's
"Decision: storage location"), so every linked worktree on this machine
sees the same ledger. This module is never a scheduler, a dependency/DAG
solver, a daemon, or a Symphony adapter.

specs/002-milestone-task-work-items/ (data-model.md, research.md) extends
this schema (v2) with `type` (`task` | `milestone`) and `parent_id` on
`work_items`, so a milestone (a human acceptance unit) can group one or
more child tasks (execution units) without becoming a second table or a
generalized workflow engine — see that feature's data-model.md for the
full compound-CHECK schema and its research.md for why `in_progress`/
`planned`/`active` were deliberately not introduced.

`WorkLedger` is a thin, stateless-except-for-`repo_root` wrapper: every
method opens its own short-lived connection, does its work, and closes it
(research.md, "Decision: connection lifecycle") — no long-lived connection
or daemon holds the database open between calls. It is not an ORM; it is a
handful of narrow methods over plain SQL, mirroring this repository's
existing `projectmem.py`/`qmd.py` shape (one purpose-built module using its
underlying tool — here, stdlib `sqlite3` — directly).
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
    """Raised when an existing file at the ledger path cannot be positively
    identified as a Bindle-owned or migratable work ledger.

    docs/DECISIONS.md's same-path filesystem-collision safety rule: an
    absent ledger file is always safe to create; an existing one already
    carrying `_APPLICATION_ID`, or one whose `user_version` and table set
    positively match a known pre-marker Bindle ledger shape, is safe to
    reconcile or adopt; anything else — a foreign database, an unreadable
    file, or a Bindle-shaped file at an unexpected version — must never be
    overwritten or reinterpreted. `connect()` raises this before any
    `CREATE TABLE`, migration, or journal-mode write touches the file.
    """


_LEDGER_DIR_NAME = ".bindle-work"
_LEDGER_FILE_NAME = "ledger.sqlite3"

# SQLite `PRAGMA application_id` — a small, narrow ownership marker for
# exactly this one file (never a broader ownership registry or manifest).
# The ASCII bytes "BWL1" ("Bindle Work Ledger", format 1) read as a
# big-endian 32-bit integer; fits a signed 32-bit PRAGMA value (SQLite
# stores this as a signed int32) and is distinct from
# `symphony_projection._APPLICATION_ID`. `connect()`/`_ensure_schema()`
# stamp this on every fresh-create, migrate, and pre-marker-adopt path —
# see `_verify_ownership` for how an existing file is checked against it
# before anything is written.
_APPLICATION_ID = 0x42574C31

# The exact table set every schema version (1, 2, or 3) of this ledger has
# always had — used by `_verify_ownership` to positively recognize a
# pre-marker (application_id == 0) database as a genuine, adoptable
# Bindle ledger rather than an unrelated file that happens to share a
# `user_version` number.
_KNOWN_TABLE_NAMES = frozenset(
    {"work_items", "work_item_blocked_by", "work_item_claims", "work_item_evidence"}
)
_KNOWN_SCHEMA_VERSIONS = frozenset({1, 2, 3})

# PRAGMA user_version — see research.md's "Decision: schema versioning and
# migration ownership". Bump this and add an explicit migration step keyed
# by the version it moves *from* when the schema next changes.
#
# v2 (specs/002-milestone-task-work-items/research.md, "Decision: schema
# migration from version 1 to version 2"): adds `type`/`parent_id`/
# `description` to `work_items` and replaces its flat status CHECK with a
# compound (type, status) CHECK. A version-1 database is migrated forward
# by `_migrate_v1_to_v2`, never left behind.
#
# v3 (specs/003-symphony-task-integration/research.md, "Decision: created_at
# NOT NULL for live rows"): installs `CHECK (archived_at IS NOT NULL OR
# created_at IS NOT NULL)` on `work_items` — the published Symphony
# projection's `task_projection.created_at` is `NOT NULL`
# (contracts/symphony-projection-v1.md) and is sourced verbatim from this
# column, but v2's own `created_at TEXT` carried no such guarantee for a
# live (non-archived) row. A version-2 database is migrated forward by
# `_migrate_v2_to_v3`, which backfills any pre-existing live row's `NULL`
# `created_at` from that row's own `updated_at` before installing the
# constraint; a version-1 database reaches v3 via `_migrate_v1_to_v2`
# followed by `_migrate_v2_to_v3`, never left at v2.
_SCHEMA_VERSION = 3


def _work_items_create_sql(table_name: str) -> str:
    """The `work_items` (v3) `CREATE TABLE` body, parameterized by table name.

    Used for fresh initialization (`table_name="work_items"`) and for both
    the v1->v2 and v2->v3 table-rebuild migrations
    (`table_name="work_items_new"`, later renamed) — one definition, so
    none of these paths can ever drift apart. specs/002-milestone-task-
    work-items/data-model.md's "Schema overview", extended by specs/003-
    symphony-task-integration/research.md's "Decision: created_at NOT NULL
    for live rows" (the final CHECK below).
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


# data-model.md's "Schema overview" (v2).
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
    """Path to this repository's ledger database file.

    Resolved from `repo_root` (`RepoInfo.repo_root` — the Git common
    directory's repository identity, never the invoking worktree), so
    every linked worktree on this machine opens the same physical file
    (research.md, "Decision: storage location").
    """
    return os.path.join(repo_root, _LEDGER_DIR_NAME, _LEDGER_FILE_NAME)


def ensure_gitignored(git_common_dir: str) -> bool:
    """Make sure the ledger file and its SQLite sidecars are locally
    ignored for this repository.

    Adds exactly `/.bindle-work/ledger.sqlite3` and its `-journal`/`-wal`/
    `-shm` sidecar lines to the repository's machine-local `info/exclude`
    (never the tracked `.gitignore`, never a broader `.bindle-work/` or
    `*.sqlite3` rule — see `git_local_exclude.py`'s module docstring and
    docs/DECISIONS.md) — so anything else placed under `.bindle-work/`
    stays ordinary, visible, trackable content. Idempotent: never
    duplicates a line already present.

    Never *raises* on a filesystem/Git error — same convenience-layer
    posture as `qmd.py`'s own `ensure_gitignored` — but, unlike that
    function, reports the outcome: returns `True` iff every line was
    confirmed present, `False` if an `OSError` prevented that. Local-ignore
    hygiene is this feature's own stated postcondition (docs/DECISIONS.md),
    not merely QMD's best-effort convenience, so a caller (`bindle init`)
    can tell the difference and report it rather than silently claiming
    success — without this function itself needing to raise, retry, or
    add any rollback of its own.
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
    """`(name, declared_type, notnull, pk)` for every column of `table_name`,
    ordered by column position — read via `PRAGMA table_info`, SQLite's own
    schema introspection. Never a second, hand-maintained schema
    definition: this is compared only against fingerprints derived the
    same way from this module's own real `CREATE TABLE` statements (see
    `_reference_table_columns`), not against a separately-authored list.
    `table_name` is always one of the fixed internal names in
    `_KNOWN_TABLE_NAMES`, never caller-supplied input.
    """
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    # row: (cid, name, type, notnull, dflt_value, pk)
    return tuple((row[1], row[2], row[3], row[5]) for row in sorted(rows, key=lambda r: r[0]))


# Columns `_migrate_v1_to_v2` adds to `work_items` via `ALTER TABLE ... ADD
# COLUMN` — the exact same three names that function's own ALTER
# statements name (see its docstring). Kept here, cross-referenced rather
# than duplicated independently, so a version-1 database's expected
# `work_items` shape can be derived by removing exactly these columns
# from the current (v2/v3, identical) shape below, rather than a second,
# separately hand-maintained "v1 shape" definition that could drift from
# the migration itself.
_V1_TO_V2_ADDED_WORK_ITEMS_COLUMNS = frozenset({"type", "parent_id", "description"})


def _reference_table_columns() -> dict[str, tuple[tuple, ...]]:
    """The exact current column shape of every table in `_KNOWN_TABLE_NAMES`.

    Built by actually running `_SCHEMA_STATEMENTS` — the identical,
    authoritative SQL `_ensure_schema()` uses for a fresh ledger — against
    a throwaway in-memory connection and reading `PRAGMA table_info` back
    (`_table_columns`). Never a second, independently-maintained schema
    definition, hash, or manifest: this is the same schema authority
    every other bootstrap path already uses, just introspected rather
    than re-declared. `work_item_blocked_by`/`work_item_claims`/
    `work_item_evidence` have never changed shape across schema versions
    1–3 (only `work_items` has); this reference shape doubles as the v2
    *and* v3 `work_items` shape too, since `_migrate_v2_to_v3` changes
    only a table-level `CHECK` constraint (not visible to `PRAGMA
    table_info`, and not a column), never a column.
    """
    conn = sqlite3.connect(":memory:")
    try:
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        return {name: _table_columns(conn, name) for name in _KNOWN_TABLE_NAMES}
    finally:
        conn.close()


def _expected_table_columns(version: int) -> dict[str, tuple[tuple, ...]]:
    """The expected per-table column shape for a pre-marker database
    claiming to be at `version` (always one of `_KNOWN_SCHEMA_VERSIONS`).

    Versions 2 and 3 share `_reference_table_columns()` verbatim (see its
    docstring). Version 1's `work_items` shape is derived by removing
    `_V1_TO_V2_ADDED_WORK_ITEMS_COLUMNS` from that same reference shape —
    reusing `_migrate_v1_to_v2`'s own already-encoded knowledge of what
    changed, rather than a separate v1 schema definition.
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
    """Refuse to touch an existing file at `db_path` that cannot be
    positively identified as Bindle-owned or migratable, before
    `_ensure_schema()` (or any journal-mode write) ever runs against it.

    Strictly path-oriented, with no filesize or content heuristic: a path
    absent before this invocation is stamped `_APPLICATION_ID` by
    `connect()` itself, immediately, before this function is ever called
    (see `connect()`'s own comment) — so by the time this runs,
    `application_id == _APPLICATION_ID` is true for every legitimately
    fresh ledger, and any other `application_id == 0` state observed here
    can only mean a pre-existing file this invocation did not create.

    Outcomes, matching the same-path filesystem-collision safety rule
    this exists to enforce:

    * `application_id` already `_APPLICATION_ID` — either a path this same
      `connect()` call just created and stamped, or a Bindle ledger from a
      version of this code that already stamps the marker on an existing
      file. Proceed; `_ensure_schema()` handles ordinary create/verify/
      migrate from here, and a crash any time after the stamp leaves a
      file a retry recognizes as its own, with no filesize/content
      heuristic needed.
    * `application_id == 0`, `user_version == 0`, no tables — a
      pre-existing file this invocation did not create (had it, `connect()`
      would have already stamped it before this function ran). Always
      refused, regardless of file size: file size is not a trustworthy
      ownership signal, since an unrelated empty SQLite database can look
      identical to a partially-initialized one.
    * `application_id == 0`, `user_version` one of `_KNOWN_SCHEMA_VERSIONS`,
      its table set exactly `_KNOWN_TABLE_NAMES`, AND every one of those
      tables' actual columns (`PRAGMA table_info`) match
      `_expected_table_columns(version)` exactly — a legitimate ledger
      created before this marker existed. Proceed; `_ensure_schema()` will
      migrate it forward if needed and stamp `_APPLICATION_ID` exactly
      once, adopting it. A table-name match with a *mismatched* column
      shape (a foreign database that happens to reuse Bindle's table
      names) is never adopted — it falls through to the final refusal.
    * Anything else — a nonzero, non-Bindle `application_id`; a
      `user_version`/table-set/column-shape combination that doesn't
      positively match a known Bindle shape; or a file that isn't a
      readable SQLite database at all — raises `ForeignDatabaseError`.
      Fails closed: nothing is created, migrated, or written.
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
        # Fresh initialization is one atomic unit: every CREATE TABLE plus
        # the PRAGMA user_version write that marks the schema as
        # initialized, all inside one explicit transaction (research.md's
        # "Decision: transaction boundaries", reusing `_transaction` rather
        # than a second atomicity mechanism). Without this, `connect()`'s
        # autocommit mode (`isolation_level=None`) would commit each
        # CREATE TABLE individually — a failure partway through (e.g. after
        # `work_items` and `work_item_blocked_by` exist but before the
        # remaining tables are created) would leave `user_version` at `0`
        # with a partially-created schema, so the next `connect()` would
        # try to recreate already-existing tables and fail permanently.
        # Verified empirically that `PRAGMA user_version` participates in
        # and is rolled back by an explicit ROLLBACK exactly like ordinary
        # DDL/DML in this SQLite/Python version (3.53.4 via the stdlib
        # `sqlite3` module) — see the accompanying report for the
        # throwaway script and its output.
        with _transaction(conn):
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)
            # PRAGMA user_version does not accept `?` bind parameters; the
            # value here is always the fixed internal constant above, never
            # caller-provided input.
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    elif version == 1:
        _migrate_v1_to_v2(conn)
    elif version == 2:
        _migrate_v2_to_v3(conn)
    elif version != _SCHEMA_VERSION:
        raise SchemaVersionError(
            f"ledger at schema version {version}, expected {_SCHEMA_VERSION}"
        )

    # Every branch above (fresh create, either migration, or an
    # already-current schema that fell through untouched) leaves the file
    # at `_SCHEMA_VERSION` — stamp the ownership marker unconditionally
    # here rather than per-branch, so a pre-marker database that was
    # *already* current on entry (no CREATE/migration of its own to
    # piggyback the stamp onto) still gets adopted exactly once.
    # `_verify_ownership()` above has already established this file is
    # either fresh or a recognized/migratable Bindle ledger, so this write
    # is always safe by the time it runs. A single `PRAGMA` write is its
    # own atomic unit (autocommit) and is idempotent to reissue on a
    # connection that already carries the marker.
    conn.execute(f"PRAGMA application_id = {_APPLICATION_ID}")


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Migrate an existing version-1 database to version 2 in place.

    specs/002-milestone-task-work-items/research.md's "Decision: schema
    migration from version 1 to version 2": SQLite cannot `ALTER` a `CHECK`
    constraint or add `NOT NULL` to an existing column, so installing v2's
    compound `(type, status)` and milestone-`parent_id` CHECKs requires the
    standard SQLite table-rebuild sequence, not a plain `ALTER TABLE`.

    `PRAGMA foreign_keys` cannot be changed inside a transaction (a no-op
    if attempted with a transaction open) and SQLite's own guidance for
    this rebuild pattern is to disable foreign key enforcement for its
    duration — `work_item_blocked_by`/`work_item_claims`/
    `work_item_evidence` all hold live `REFERENCES work_items(id)` rows
    that would otherwise be checked against the intermediate DROP — then
    re-enable it and verify with `PRAGMA foreign_key_check` before
    returning, so this method never leaves the database in a state where
    referential integrity was silently skipped rather than verified.

    Every pre-existing row is backfilled to `type = 'task'` with
    `parent_id` left `NULL` — the only sensible reading of a v1 item, which
    had no milestone concept to attribute it to (research.md's "Decision:
    schema migration...", "Alternatives considered"). This function always
    rebuilds straight to the current `_work_items_create_sql` shape (the
    same shared definition fresh initialization uses) and stamps
    `_SCHEMA_VERSION`, so a v1 database never stops at an intermediate,
    no-longer-defined "v2-only" shape — it lands wherever `_ensure_schema`
    currently considers latest, exactly like `_migrate_v2_to_v3` below.
    Because that shared shape now includes v3's `CHECK (archived_at IS NOT
    NULL OR created_at IS NOT NULL)` (research.md's "Decision: created_at
    NOT NULL for live rows"), any pre-existing live row's `NULL`
    `created_at` is backfilled from that row's own `updated_at` before the
    rebuild reads it — the identical backfill `_migrate_v2_to_v3` performs,
    needed here for exactly the same reason: nothing in v1's own schema
    prevented that state either. Wrapped in one transaction (mirroring
    `_ensure_schema`'s own fresh-bootstrap atomicity) so a crash
    mid-migration leaves the database at its original, fully-functional
    version-1 state, never a partially migrated one.
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
    """Migrate an existing version-2 database to version 3 in place.

    specs/003-symphony-task-integration/research.md's "Decision: created_at
    NOT NULL for live rows": the published Symphony projection's
    `task_projection.created_at` column is `NOT NULL`
    (contracts/symphony-projection-v1.md) and is sourced verbatim from the
    canonical `work_items.created_at` column — but v2's own `created_at
    TEXT` carried no such guarantee for a live (`archived_at IS NULL`) row.
    No exposed method can currently produce that state (every
    `create_work_item()` call stamps `created_at` at insert time; the only
    code that ever clears it is `archive_work_item()`, which requires
    `archived_at` to become non-`NULL` in the same update), but the column
    itself did not structurally prevent it — a hand-restored or externally
    written ledger file could still carry a live row with `created_at IS
    NULL`, which would then make `publish()`'s own `NOT NULL` insert into
    `task_projection` fail. v3 closes that gap: this migration first
    backfills any such row's `created_at` from that row's own `updated_at`
    — the closest already-recorded, non-`NULL` timestamp already on the
    row, never a value invented at migration time — then rebuilds the
    table with `_work_items_create_sql`'s new `CHECK (archived_at IS NOT
    NULL OR created_at IS NOT NULL)`, exactly mirroring
    `_migrate_v1_to_v2`'s own table-rebuild pattern (SQLite cannot `ALTER`
    a `CHECK` constraint onto an existing table). An already-archived row's
    `created_at` (deliberately cleared by `archive_work_item`) is left
    untouched — the backfill's own `WHERE ... AND archived_at IS NULL`
    guard excludes it, and the new CHECK permits `created_at IS NULL`
    exactly when `archived_at IS NOT NULL`.
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
    """Open a short-lived connection to this repository's ledger.

    Sets every mandatory PRAGMA (research.md, "Decision: connection
    lifecycle") and bootstraps or verifies the schema (research.md,
    "Decision: schema versioning") before returning. `isolation_level=None`
    puts the connection in autocommit mode: a single statement commits
    immediately on its own; a multi-statement mutation wraps itself in an
    explicit `BEGIN IMMEDIATE` / `COMMIT` (research.md, "Decision:
    transaction boundaries") rather than relying on an implicit
    transaction. Callers are responsible for closing the returned
    connection — no long-lived connection or daemon holds the database
    open between operations. `WorkLedger`'s own methods are the normal way
    to use this module; this is exposed directly for direct SQL
    inspection/tests and for callers that need several statements against
    one connection outside a `WorkLedger` method.
    """
    db_path = ledger_path(repo_root)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    # Must be observed BEFORE sqlite3.connect() below, which creates a
    # 0-byte file immediately for a path that didn't already exist
    # (verified empirically) — this is the only way to know "this
    # invocation itself created db_path" from inside the function.
    path_existed_before = os.path.exists(db_path)
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 2000")
        if not path_existed_before:
            # This connection's own sqlite3.connect() call is what just
            # created db_path — stamp ownership immediately, as the very
            # first write, before `journal_mode`/schema bootstrap can ever
            # fail. A crash any time after this single, already-committed
            # (autocommit) statement leaves the file positively
            # recognizable as Bindle's own on the next connect() attempt,
            # so a retry can safely resume via `_verify_ownership`'s own
            # `application_id == _APPLICATION_ID` fast path below — no
            # filesize or content heuristic needed (docs/DECISIONS.md).
            conn.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        # Ownership MUST be verified before `journal_mode = WAL` below:
        # switching journal mode writes SQLite's WAL flag into the
        # database file's own header immediately, which would mutate a
        # foreign file before ownership is established. `foreign_keys`/
        # `busy_timeout` above are connection-local settings, never
        # written to `db_path` itself, so checking ownership after them
        # but before `journal_mode`/`synchronous` (the latter is also
        # connection-local, but kept adjacent to `journal_mode` for
        # readability) is safe.
        _verify_ownership(conn, db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        _ensure_schema(conn)
    except BaseException:
        # A connection that fails setup (a PRAGMA, or schema bootstrap)
        # must not be left open for garbage collection to close
        # eventually — that is not a reliable way to release SQLite's
        # file lock promptly, and a lingering open connection can cause a
        # subsequent, otherwise-healthy `connect()` call to hang or fail
        # with "database is locked". Close explicitly and re-raise the
        # original exception unchanged.
        conn.close()
        raise
    return conn


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _local_branch_exists(repo_root: str, branch: str) -> bool:
    """Whether `branch` currently exists as a local ref in `repo_root`.

    Mirrors `src/bindle/repo.py`'s narrow `_run_git`/`_git` git-shell-out
    convention rather than introducing a general-purpose shell
    abstraction — a single, read-only `git show-ref` invocation, run with
    `cwd=repo_root` (the ledger's own Git-common-directory-resolved
    `repo_root`, never the invoking worktree, per research.md's "Decision:
    storage location"). Used by `reconcile()`'s `stale_claim` check
    (FR-009) for a claim that recorded a `branch` — this deliberately
    does not use `repo.py`'s own `_git` helper, since that helper raises
    on any nonzero exit and a missing branch is an expected, ordinary
    outcome here, not an error condition to raise on. `git show-ref
    --verify --quiet` is read-only: it never creates, moves, or deletes a
    ref, preserving reconcile()'s own read-only contract.
    """
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _registered_worktree_paths(repo_root: str) -> set[str] | None:
    """Every path currently registered with Git as a live worktree of
    `repo_root` (`RepoInfo.repo_root`), per `git worktree list
    --porcelain` — used by `reconcile()`'s `stale_claim` check (FR-009)
    as a strictly more accurate signal than `os.path.isdir`, which only
    proves *some* directory exists at the recorded path, not that it is
    still a worktree Git itself knows about (data-model.md's
    "Staleness": "no longer exists as a worktree on this machine", not
    "no longer exists as a directory"). Mirrors `src/bindle/repo.py`'s
    narrow `_run_git`-style convention (plain `subprocess.run`,
    plain-text parsing, no generic git abstraction) rather than reusing
    `repo.py`'s own `_git`/`_run_git` directly — this needs to parse
    multi-line, multi-block porcelain output, a different shape than
    `repo.py`'s single-value lookups. Read-only: `git worktree list`
    never creates, moves, or deletes anything.

    Returns `None` (rather than an empty set) when `repo_root` is not
    itself a Git repository Git can enumerate worktrees for (nonzero
    exit — e.g. this repository's own `LedgerTestCase` fixture, which
    deliberately uses a plain temporary directory so most of this
    module's tests need no real Git repository at all). `None` is a
    distinct signal from "queried successfully, zero registered
    worktrees" so `reconcile()` can fall back to the older,
    directory-existence heuristic in that case rather than treating
    every recorded `worktree_path` as unconditionally stale. In real
    use `WorkLedger.repo_root` is always `RepoInfo.repo_root` — an
    actual Git common directory (this module's own docstring) — so this
    fallback is not expected to ever trigger outside of tests that
    deliberately avoid a real repository.

    Empirically verified (scratch-repository investigation) porcelain
    shape: one block per worktree, starting with a `worktree <path>`
    line, followed by attribute lines (`HEAD`, `branch`/`bare`/
    `detached`, optionally `locked [reason]` and/or `prunable
    [reason]`), blocks separated by a blank line.

    - A `locked` worktree is still live and registered (locking only
      guards against accidental removal) and is included.
    - A `prunable` worktree is excluded even though it still appears in
      the raw listing: empirically, once a worktree directory is removed
      with a bare `rm -rf` (skipping `git worktree remove`), Git's own
      per-worktree administrative entry survives until `git worktree
      prune` runs, and `git worktree list --porcelain` keeps emitting a
      `worktree <path>` block for it annotated `prunable ...` — this
      remains true even after an ordinary, unrelated directory is later
      created at that exact same path (confirmed empirically: creating
      the directory does not make Git re-examine or clear the
      `prunable` annotation). Treating a `prunable` entry as registered
      would therefore silently readmit exactly the "ordinary directory
      mistaken for a live worktree" case this check exists to close, so
      it is filtered out here rather than left for the caller to check.

    Paths are normalized with `os.path.realpath` (Git's own listing
    already reports canonicalized paths, e.g. with symlinks resolved —
    observed empirically) so a caller can compare its own
    `os.path.realpath`-normalized `worktree_path` against this set
    directly.
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
    """Wrap a multi-statement mutation in one `BEGIN IMMEDIATE` transaction.

    research.md, "Decision: transaction boundaries": every mutation that
    changes more than one related, durable fact runs inside one explicit
    transaction, so a crash or interruption mid-mutation leaves the ledger
    in exactly its pre-mutation state. `BEGIN IMMEDIATE` (not a deferred
    transaction) so lock acquisition fails fast on contention. A
    single-statement mutation does not need this — `connect()`'s
    `isolation_level=None` autocommit already makes it atomic on its own.
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

    Field presence/absence follows data-model.md's "Work Item" table
    exactly: an archived item has `title`, `description`, `source_kind`,
    `source_locator`, `source_promoted_by`, and `created_at` cleared to
    `None`, while `id`, `type`, `status`, `superseded_by`, `updated_at`,
    and `archived_at` remain populated as appropriate.

    `type` (`task` | `milestone`) and `parent_id` (a task's owning
    milestone; always `None` for a milestone) are specs/002's additions —
    see that feature's data-model.md. `parent_id` is never cleared by
    archival of the item that *holds* it (a child's own row is untouched
    by its parent's archival); it is only ever cleared by nothing at all,
    since this model has no operation that reassigns or removes it.
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

    `finding` is one of: `stale_claim` | `corrupt_claim` | `dangling_blocker`
    | `duplicate_source` | `cycle_detected` — see data-model.md's
    "Reconciliation Report" and spec.md's Edge Cases for the scenario each
    corresponds to. `item_id` is `None` when a finding concerns a set of
    items or the database as a whole (e.g. `duplicate_source`, or a
    whole-file `corrupt_claim` from `PRAGMA integrity_check`) rather than a
    single work item.
    """

    item_id: str | None
    finding: str
    detail: str


@dataclasses.dataclass(frozen=True)
class ProjectedWorkItem:
    """Coordinator-facing projection of one Work Item (contracts/coordinator-projection.md).

    Deliberately coordinator-agnostic: no Symphony-specific field names,
    no `active_states`/`terminal_states` strings (those are a specific
    external WORKFLOW.md's configuration this module never sees) — a
    future Symphony-specific adapter maps `terminal`/`eligible` onto
    whatever strings its own configuration declares.
    """

    id: str
    title: str | None
    terminal: bool
    eligible: bool


@dataclasses.dataclass(frozen=True)
class ExternalProjectionRow:
    """One row of the published, external Symphony-facing projection.

    specs/003-symphony-task-integration/data-model.md's "New WorkLedger
    methods" -> `generate_external_projection()`, and
    contracts/symphony-projection-v1.md's schema — a physically separate
    contract from `ProjectedWorkItem` above, never sharing a schema with
    it (FR-019). `status` is exposed directly as the raw, readable string
    (`open` | `done` | `superseded`) rather than as a pair of booleans an
    external reader would otherwise have to reconstruct from, and
    `dispatchable` is computed entirely inside Bindle (FR-016) so an
    external reader never needs to evaluate blocking or claim state
    itself. `identifier` (FR-015) is a non-empty, workspace-name-safe
    derivation of `id` (research.md's "Decision: identifier derivation
    for external workspace naming") — deterministic, never a second,
    independently-assigned identity. `created_at` is preserved verbatim
    from the canonical work item's own `created_at` column, never derived
    or synthesized at publish time — Symphony's dispatch ordering needs a
    real creation timestamp to rank simultaneously-eligible candidates,
    not a value invented at export time. Typed `str`, never `str | None`:
    this query is restricted to `archived_at IS NULL` rows, and v3's
    `CHECK (archived_at IS NOT NULL OR created_at IS NOT NULL)`
    (research.md's "Decision: created_at NOT NULL for live rows")
    structurally guarantees every such row carries a non-`NULL`
    `created_at` — exactly what `task_projection.created_at`'s own `NOT
    NULL` column requires.
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
    """One row of `work_item_evidence`, read back individually.

    specs/004-milestone-review-surface data-model.md: generalizes
    `has_qualifying_evidence()`'s existing `EXISTS` check into a full-row
    read — no new field, no new kind (`kind` remains one of `branch` |
    `commit` | `pull_request` | `other`, per the schema's own `CHECK`).
    """

    kind: str
    value: str
    recorded_at: str
    note: str | None


@dataclasses.dataclass(frozen=True)
class ClaimInfo:
    """The single claim row for a work item, read back individually.

    specs/004-milestone-review-surface data-model.md: generalizes
    `is_claimed()`'s existing `EXISTS` check into a full-row read.
    `worktree_path`/`branch` mirror `claim()`'s own optional-argument
    shape — `None` when not supplied at claim time.
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


# specs/002-milestone-task-work-items/data-model.md's "Dependency
# resolution — generalized to be type-aware": whether a referenced item
# (aliased `dep` in every query below) still counts as blocking, given its
# `type` and `status` — a task resolves at `done`/`superseded`; a milestone
# resolves at `accepted`/`superseded` (its `review`/`open` states do not
# resolve a dependency, unlike a task's `open`). A dangling reference
# (`dep.id IS NULL`) is conservatively still blocking, unchanged from 001.
#
# Shared by `is_blocked`, `list_available_work_items`, `is_review_ready`,
# and `generate_projection` specifically so this predicate is defined
# exactly once — specs/002's task-composition analysis (S4's "Risk /
# uncertainty") flagged that `generate_projection`'s own inline eligibility
# subquery would otherwise duplicate this rule and risk drifting from it.
_STILL_BLOCKING_CONDITION = """(
                      dep.id IS NULL OR NOT (
                        (dep.type = 'task' AND dep.status IN ('done', 'superseded'))
                        OR (dep.type = 'milestone' AND dep.status IN ('accepted', 'superseded'))
                      )
                    )"""


def is_dispatchable(status: str, claimed: bool, blocked: bool) -> bool:
    """The exact task-dispatchability rule `list_available_work_items()`'s
    own SQL encodes (`status == 'open' AND NOT claimed AND NOT blocked`),
    factored out as a pure, I/O-free function so it can be evaluated
    identically against live ledger state and against a read-only forecast
    counterfactual (specs/005-work-state-visibility). Takes no `type`
    argument because every caller already scopes to `type == 'task'` before
    calling this — the same structural precondition
    `list_available_work_items()`'s own query already applies before this
    predicate's three conjuncts.
    """
    return status == "open" and not claimed and not blocked


def _review_ready_sql(id_expr: str) -> str:
    """A boolean SQL expression: is the milestone named by `id_expr`
    review-ready (specs/002 data-model.md's "Review readiness")?

    `id_expr` is a literal SQL fragment substituted directly into the
    query text — always one of exactly two fixed internal literals, never
    caller-supplied data: `"?"` for a standalone bind-parameter query
    (`is_review_ready`, bound three times to the same `work_item_id`), or
    `"work_items.id"` for a correlated reference when this condition is
    embedded inside `mark_in_review`'s own `UPDATE ... WHERE` clause.

    That second form exists because FR-010 requires the transition into
    `review` to be permitted only when review-ready **at the moment of
    the same atomic update** — a separate `is_review_ready()` pre-check
    followed by a second `mark_in_review()` call would leave a race
    window between the two statements in which readiness could change.
    Embedding this condition directly in the guarded `UPDATE`'s `WHERE`
    clause closes that window: the row-count of one atomic statement is
    the only arbitration mechanism, exactly like every other guarded
    transition in this module.
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

    A `WorkLedger` instance is a cheap, stateless-except-for-`repo_root`
    handle — it holds no open connection and no cache. Every method opens
    its own short-lived connection (via `connect`), does its work, and
    closes it before returning.
    """

    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root

    def _connect(self) -> sqlite3.Connection:
        return connect(self.repo_root)

    def ensure_schema(self) -> None:
        """Bootstrap or verify this repository's ledger schema, eagerly.

        Every other method already gets this for free as a side effect of
        `_connect()`/`connect()`'s own bootstrap-or-verify behavior — this
        method exists only so a caller that wants schema readiness as an
        explicit, standalone step (`bindle init`: see `cli.py`) can ask for
        it without reaching into the private `_connect()` or the
        module-level `connect()` function directly, and without a second,
        drifting copy of what "valid schema" means. On a fresh repository,
        creates `.bindle-work/ledger.sqlite3` with all tables at the
        current `_SCHEMA_VERSION` and zero rows in every table. On an
        existing repository, verifies the schema, migrating it forward in
        place first if it predates `_SCHEMA_VERSION` (`_migrate_v1_to_v2`/
        `_migrate_v2_to_v3` — see their own docstrings for the exact,
        narrow compatibility/backfill transformations each applies, e.g.
        backfilling `type = 'task'` or `created_at` from `updated_at` on a
        pre-existing row) — this never creates, claims, or transitions a
        work item, and never creates or changes semantic work state:
        existing rows are preserved as-is, except for a migration's own
        defined, narrow compatibility/backfill transformations.
        """
        self._connect().close()

    # -- User Story 1: create/read -----------------------------------

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
        """Create a Work Item — the only operation that creates one (FR-002/FR-003).

        `status` is always `open` at creation. When `blocked_by` is given,
        the item and its initial dependency edges are created in one
        transaction (research.md's "Create a work item, optionally with
        initial `blocked_by` edges" mutation) — all-or-nothing, so an item
        is never recorded with only some of its declared dependencies.

        `type` defaults to `"task"` (backward-compatible with every 001
        caller). specs/002-milestone-task-work-items FR-002/FR-003: a
        `parent_id`, when given, MUST name an existing `type='milestone'`
        row that is currently `status = 'open'` — checked here (a plain
        `REFERENCES` foreign key cannot express "must be an open
        milestone," only "must exist") and raised as `ValueError` before
        any row is written; a `type='milestone'` row naming a `parent_id`
        is instead rejected by the schema's own `CHECK`
        (`sqlite3.IntegrityError`), since that restriction needs no
        cross-row lookup.

        Membership is frozen once a milestone leaves `open`
        (specs/002-milestone-task-work-items FR-003a): a task may be
        attached only while its milestone is `open`, never while `review`,
        `accepted`, or `superseded` — otherwise a milestone's accepted (or
        currently-under-review) child set could change underneath a
        decision a human already made, or after one. This is why the
        parent's `status`, not only its `type`, is validated. Unlike
        `type` (immutable once set), `status` **is** mutable — a milestone
        can move `open -> review` at any time — so this check MUST run
        inside the same `BEGIN IMMEDIATE` transaction as the `INSERT`
        below, not merely before it: a separate pre-check followed by a
        second, later `INSERT` would leave a race window in which a
        concurrent `mark_in_review()` (or any other status transition)
        could invalidate the parent's `open`-ness between the check and
        the write, the same class of check-then-act race FR-010 already
        closes for `mark_in_review` and this method's own archival
        counterpart closes for `archive_work_item`. `BEGIN IMMEDIATE`
        acquires SQLite's write lock for the whole transaction, so no
        concurrent writer can transition the parent's status between this
        `SELECT` and the `INSERT` that depends on its result.
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
        """Read a single Work Item by id, or `None` if it does not exist.

        Returns the same record structure regardless of caller worktree or
        session (contracts/work-item-record.md's Read guarantees) — a
        single `SELECT` against the shared ledger file.
        """
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
        """Re-sync a Work Item's declarative fields from a fresh source read.

        specs/003-symphony-task-integration data-model.md/research.md
        ("Decision: how a reload updates an existing work item"): a single
        guarded `UPDATE work_items SET title = ?, description = ?,
        updated_at = ? WHERE id = ? AND archived_at IS NULL`. This is the
        only mutation a reloading caller (e.g. a Spec Kit `tasks.md`
        loader) may perform against a work item whose id it already
        recognizes — it never touches `status`, `type`, `parent_id`,
        `source_kind`, `source_locator`, `source_promoted_by`, any claim,
        or any evidence, so a reload can never disturb runtime-owned
        state. Coordinator- and source-agnostic, like every other method
        here: it has no idea what `speckit_task` or any other
        `source_kind` means, only that `title`/`description` are the two
        columns a reload is ever allowed to change.

        Guarded on `archived_at IS NULL`, mirroring `mark_done`'s own
        "guarded transition, not an error, when it doesn't apply"
        convention: resyncing an archived item's already-thinned row (its
        `title`/`description` are already `NULL` by archival's own
        design) would be meaningless, so it is a true no-op here, not a
        failure. Returns `True` iff exactly one row was updated; `False`
        if `id` does not exist or names an archived item.
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

    # -- User Story 2: blocking and availability ----------------------

    def add_blocked_by(self, work_item_id: str, blocked_on_id: str) -> None:
        """Declare that `work_item_id` is blocked on `blocked_on_id` (T014).

        A single `INSERT` into `work_item_blocked_by`. No extra validation
        is performed here — the schema's own `CHECK (work_item_id !=
        blocked_on_id)` and its `FOREIGN KEY` constraints (enforced
        because `connect()` always sets `PRAGMA foreign_keys = ON`)
        already reject a direct self-cycle or a dangling target at write
        time by raising `sqlite3.IntegrityError`, per data-model.md's
        "Dependency resolution" → "Foreign key enforcement". Callers that
        need to distinguish that failure do so via that exception.
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
        """Whether `work_item_id` is currently blocked (T015).

        data-model.md's "Derived facts" → "Blocked", generalized by
        specs/002 to be type-aware (`_STILL_BLOCKING_CONDITION`): any
        `blocked_by` row for this item whose referenced item has not
        reached *its own type's* resolved terminal state — `done`/
        `superseded` for a task, `accepted`/`superseded` for a milestone —
        or resolves to no row at all (a dangling reference, treated
        conservatively as still blocking per FR-021), counts as blocking.
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
        """List the ids currently still blocking `work_item_id` (specs/004-milestone-review-surface).

        Generalizes `is_blocked()`'s existing `EXISTS` check into a full
        row read, over the identical `_STILL_BLOCKING_CONDITION`
        predicate — so this can never disagree with `is_blocked()` about
        *whether* an item is blocked, only add *which* declared
        `blocked_by` edges are the reason (spec.md Acceptance Scenario
        US1.4: "identifies the blocking dependency"). A dangling
        reference (the referenced id resolves to no row at all) is
        included exactly as declared, unresolved — treated conservatively
        as still blocking, matching `is_blocked()`'s own conservative
        posture, with nothing to substitute for the missing row. Ordered
        by `blocked_on_id` for determinism; returns `[]`, never raises,
        when `work_item_id` is not currently blocked or does not exist.
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
        """Whether `work_item_id` currently has a claim (T016).

        Claimed status is never a column on `work_items` itself — it is
        the existence of a row in `work_item_claims` (data-model.md,
        "Claims").
        """
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
        """List the ids of every **task** currently available to start (T017).

        The composite query from data-model.md's "Derived facts" →
        "Available to start": `status = 'open'` AND not claimed AND not
        blocked. Returns ids only (mirroring the data-model.md query,
        which selects only `id`), ordered by `id` for determinism.

        specs/002-milestone-task-work-items: restricted to `type = 'task'`
        rows only (`AND wi.type = 'task'`), mirroring
        `generate_projection()`'s own `type = 'task'` filter (FR-017) and
        for the same reason — a milestone is a human acceptance unit, not
        an executable/startable unit of work (data-model.md's "Milestone"),
        so an `open`, unclaimed, unblocked milestone must never be reported
        as something to "start." This is a `WHERE` predicate, not a
        post-filter a caller could bypass by reading the table directly.

        specs/005-work-state-visibility: fetches every candidate
        `type = 'task'` row's `status`/claimed/blocked facts in one
        `SELECT` (ordered by `id`, unchanged), then applies `is_dispatchable()`
        per row in Python to decide inclusion — rather than re-expressing
        the identical three-conjunct rule a second time in this query's own
        `WHERE` clause. This is the sole authoritative expression of task
        dispatchability, shared with `work_status.build_forecast()`'s own
        read-only counterfactual (research.md's "dispatchable-next shares
        one authoritative predicate"). External behavior, return value, and
        ordering are unchanged by this refactor.

        `wi.status = 'open'` stays in `WHERE`, not just in `is_dispatchable()`'s
        Python conjuncts: `claimed`/`blocked` are now correlated `EXISTS`
        subqueries in the `SELECT` list rather than `WHERE`, so without this
        filter SQLite would evaluate both subqueries for every `done`/
        `superseded` task too, even though `is_dispatchable()` always
        rejects those regardless of `claimed`/`blocked` — pure wasted
        per-row work the pre-refactor query never did (its own `status =
        'open'` `WHERE` conjunct short-circuited before either `NOT EXISTS`
        ever ran). Keeping it here is a plain candidate-narrowing filter on
        an already-fetched column, not a second expression of the claimed/
        blocked rule — `is_dispatchable()` still receives and evaluates
        `status` itself, and remains the only place that rule is decided.
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
        """Transition `work_item_id` to `done` (T018).

        A single guarded `UPDATE ... WHERE status = 'open'`
        (research.md's "Decision: transaction boundaries") — with
        `connect()`'s autocommit (`isolation_level=None`), one `UPDATE`
        statement is already atomic on its own, so no `_transaction`
        wrapper is needed. Returns `True` iff exactly one row was updated;
        `False` if the item does not exist or is not currently `open`
        (this is the guard that prevents a double-transition race from
        silently double-applying — it is a no-op, not an error).
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
        """Transition `work_item_id` to `superseded` (T018).

        Same guarded, single-statement shape as `mark_done` — see its
        docstring. `superseded_by` is required and stored alongside the
        transition, per data-model.md's `status`/`superseded_by` pairing
        `CHECK` constraint. Returns `True` iff exactly one row was
        updated; `False` if the item does not exist or is not currently
        `open`.
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

    # -- specs/002: milestone review lifecycle ------------------------

    def is_review_ready(self, work_item_id: str) -> bool:
        """Whether the milestone `work_item_id` is ready for human review.

        specs/002-milestone-task-work-items data-model.md's "Review
        readiness": true iff (a) the milestone itself is not blocked
        (`_STILL_BLOCKING_CONDITION`); (b) it has at least one child task
        (`parent_id` naming it) — an empty milestone is never review-ready;
        and (c) every child is `superseded`, or `done` with at least one
        recorded evidence pointer. Purely derived — never stored — exactly
        mirroring `list_available_work_items`'s own "Available to start"
        precedent. Meaningful only for a `type='milestone'` row; a task has
        no children by construction, so this would always report `False`
        for one (harmless, but callers should only ask it of a milestone).

        `mark_in_review` embeds this exact same condition (via
        `_review_ready_sql`) directly in its own atomic guarded `UPDATE`
        rather than relying on a caller to call this method first and then
        separately attempt the transition — this method exists for callers
        that want to inspect readiness without attempting a transition
        (e.g. deciding whether to bother), not as the sole enforcement of
        FR-010's guarantee.
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
        """Transition milestone `work_item_id` from `open` to `review`.

        FR-010: permitted only when the milestone is currently `open` AND
        review-ready **at the moment of this same atomic update** — the
        readiness condition (`_review_ready_sql`) is embedded directly in
        this `UPDATE`'s own `WHERE` clause, not checked separately
        beforehand, so there is no window between "checked ready" and
        "transitioned" in which another actor's change to a child task
        could invalidate the decision. Mirrors `mark_done`/
        `mark_superseded`'s single-winner-transition shape otherwise:
        returns `True` iff exactly one row was updated; `False` if the
        item does not exist, is not a milestone, is not currently `open`,
        or is not (or no longer) review-ready.
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

        "Changes requested" (spec.md User Story 4): touches no child task's
        status, evidence, or identity — only this milestone's own row.
        Same guarded-`UPDATE` shape as `mark_in_review`. Returns `True` iff
        exactly one row was updated; `False` if the item does not exist,
        is not a milestone, or is not currently `review`.
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

        `accepted` is the milestone's terminal-success state, playing the
        same role `done` plays for a task (FR-005). Same guarded-`UPDATE`
        shape as `mark_in_review`/`decline_review`. Returns `True` iff
        exactly one row was updated; `False` if the item does not exist,
        is not a milestone, or is not currently `review`.
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

    # -- User Story 3: claim, evidence, reconciliation ----------------

    def claim(
        self,
        work_item_id: str,
        owner: str,
        worktree_path: str | None = None,
        branch: str | None = None,
    ) -> bool:
        """Attempt to claim a Work Item (FR-007, FR-018).

        A single `INSERT INTO work_item_claims` is the sole arbitration
        mechanism (data-model.md's "Claim atomicity contract"): the
        primary key on `work_item_id` guarantees that, of any number of
        concurrent attempts against the same item, exactly one succeeds
        and every other fails immediately and unambiguously.

        Returns `True` if this call's `INSERT` committed (claim
        acquired). Returns `False` if it failed specifically because a
        claim row for `work_item_id` already exists — the ordinary,
        expected "already claimed" outcome, never surfaced as an error.
        A `work_item_id` that does not reference any row in `work_items`
        at all raises a *different* `sqlite3.IntegrityError` (a
        foreign-key violation, not a primary-key violation) and is
        re-raised rather than swallowed into a `False` return.

        The two cases are distinguished by `exc.sqlite_errorcode`
        (Python 3.11+, this repository's minimum), not by matching
        substrings of `str(exc)` — message text is not a stable API and
        is fragile to SQLite version wording changes. `work_item_claims`
        conflicts on its own `PRIMARY KEY (work_item_id)` (verified
        empirically against this schema:
        `sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY`, not the generic
        `SQLITE_CONSTRAINT_UNIQUE`), so only that specific code is
        treated as "already claimed" — any other `IntegrityError`
        (including a foreign-key violation for a nonexistent
        `work_item_id`) propagates unchanged.
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

        `DELETE FROM work_item_claims WHERE work_item_id = ? AND owner = ?`
        — deleting zero rows (already released, or `owner` does not match
        the recorded owner) is a no-op, never an error, per data-model.md's
        "Safe release" (idempotent-if-absent).
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
        `corrupt_claim` reconciliation finding (data-model.md's
        "Staleness") — a documented process expectation on the caller,
        not something this method itself verifies or enforces. Deletes
        the claim row unconditionally (no `owner` filter, since the
        recorded owner may be unreachable or unattributable) and, only
        when `note` is given, records an Evidence Pointer (`kind =
        'other'`) documenting the justification, in the same transaction
        (research.md's "Decision: transaction boundaries", "Claim
        release (override)").

        This does NOT grant the caller a claim on the item: releasing a
        claim only makes the item unclaimed and claimable again — it is
        not itself a claim, and is not combined atomically with a
        subsequent acquire (spec.md's Edge Cases). A caller that wants to
        hold the item afterward must separately call `claim()` and go
        through ordinary arbitration.
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

        Append-only: a single `INSERT` into `work_item_evidence`. No
        `UPDATE`/`DELETE` path exists for an individual pointer
        (data-model.md's Evidence Pointer invariant) — a rebased,
        squashed, or deleted branch's pointer is left exactly as
        recorded, a historical observation, never "fixed" in place.
        `kind` must be one of `branch` | `commit` | `pull_request` |
        `other`; the schema's own `CHECK` constraint enforces this, not
        re-validated here.
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
        """Whether `work_item_id` carries "qualifying mechanical evidence."

        specs/002-milestone-task-work-items data-model.md: true iff at
        least one row exists in `work_item_evidence` for it, of any of the
        four existing kinds. Purely derived, read-only — does not gate or
        change `mark_done`'s existing behavior (evidence remains optional
        to record, per 001 FR-008); consumed only by `is_review_ready`'s
        computation for a task's parent milestone.
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
        """Read back every recorded Evidence Pointer for `work_item_id` (T005).

        specs/004-milestone-review-surface data-model.md: generalizes
        `has_qualifying_evidence()`'s existing `EXISTS` check into a full
        row read, ordered by `evidence_id` (the table's own
        auto-incrementing insertion order — append-only, never
        reordered — not `recorded_at`, which can tie between two
        pointers recorded in the same instant). Returns `[]`, never
        raises, for a nonexistent `work_item_id`.
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
        """Read back the single claim row for `work_item_id`, or `None` (T006).

        specs/004-milestone-review-surface data-model.md: generalizes
        `is_claimed()`'s existing `EXISTS` check into a full row read.
        `work_item_claims.PRIMARY KEY (work_item_id)` guarantees at most
        one row, so this returns a single optional value, mirroring
        `get_work_item()`'s own `WorkItem | None` shape for "not found."
        """
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

        Compares recorded ledger state against observed repository state
        (claim `worktree_path` registration as a live Git worktree, and
        claim `branch` existence as a local ref — FR-009, checked via
        read-only `git worktree list` and `git show-ref` invocations
        shelled out against `self.repo_root`, never a mutating Git
        command) and internal consistency (claim row-shape,
        whole-database integrity, dangling blocking edges, duplicate
        sources, blocking cycles), per data-model.md's "Reconciliation
        Report". Every query below is a `SELECT`, and every Git
        invocation is read-only; this method never opens a write
        transaction and never mutates `work_items`, `work_item_claims`,
        `work_item_blocked_by`, or `work_item_evidence` — finding a claim
        stale or corrupt does not, by itself, change whether an item is
        computed as available (research.md's "Decision: claim safety").

        Scoped to the five finding types this slice has explicit task
        coverage for: `stale_claim`, `corrupt_claim`, `dangling_blocker`,
        `duplicate_source`, and `cycle_detected`. `dangling_evidence`
        (data-model.md's Reconciliation Report field list names it as a
        possible finding type) is deliberately not implemented here —
        checking whether an Evidence Pointer's own `branch`/`commit`
        value still resolves is a distinct check from the claim-branch
        existence check above (it would need to validate arbitrary
        commit SHAs and PR references too, not just local branch refs),
        and remains out of scope for this slice.
        """
        findings: list[ReconciliationFinding] = []
        conn = self._connect()
        try:
            # stale_claim: a recorded worktree_path that no longer
            # resolves to a currently registered Git worktree of this
            # repository (FR-009, data-model.md's "Staleness": "no
            # longer exists as a worktree on this machine" — not merely
            # "no longer exists as a directory"; see
            # `_registered_worktree_paths`'s own docstring for the
            # empirical basis of this check, including why a plain
            # `os.path.isdir` would be fooled by an ordinary, unrelated
            # directory later created at a properly-removed worktree's
            # old path), falling back to the plain `os.path.isdir`
            # heuristic only when `repo_root` is not itself a Git
            # repository Git can enumerate worktrees for (see that
            # function's docstring — not expected outside tests), or
            # (FR-009, data-model.md's "Staleness") a recorded branch
            # that no longer exists as a local ref. Every claim row is
            # inspected — including a branch-only claim (branch set,
            # worktree_path NULL), which the worktree check alone would
            # otherwise never flag. When both are recorded, the worktree
            # is checked first (the more common case); either signal
            # being stale produces exactly one `stale_claim` finding for
            # that claim, never two, so a caller never has to reconcile
            # duplicate/contradictory findings for one row. The branch
            # check ("Explicitly not solved by this model" in
            # data-model.md's "Staleness" section) is unrelated to this
            # fix — that documented gap is specifically about a claim
            # whose worktree/branch still exists but whose owner simply
            # stopped working, which no absence-based check can detect.
            #
            # The registered-worktree set is computed once per
            # reconcile() call (one read-only `git worktree list`
            # shell-out total, not one per claim row) and reused for
            # every claim inspected below.
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

            # corrupt_claim (a): row-shape inspection — owner/claimed_at
            # NULL or empty. This should not happen through the normal
            # claim() path (the schema's NOT NULL constraints plus
            # single-statement atomicity prevent it) — this check exists
            # for defense-in-depth against a connection that ran with
            # constraints bypassed, or file-level tampering.
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

            # dangling_blocker: a blocked_by edge whose blocked_on_id
            # resolves to no row at all (data-model.md's "Dependency
            # resolution").
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

            # duplicate_source: two or more active items sharing
            # (source_kind, source_locator) — data-model.md's exact
            # query, verbatim.
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

            # cycle_detected: indirect blocking cycles via a recursive
            # CTE — data-model.md's "Cycle detection" query, verbatim.
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

    # -- User Story 4: coordinator projection -------------------------

    def generate_projection(self) -> list[ProjectedWorkItem]:
        """Generate a disposable, coordinator-facing projection (FR-013/FR-014).

        Per contracts/coordinator-projection.md, extended by specs/002's
        contracts/coordinator-projection-v2.md: considers only
        non-archived (`WHERE archived_at IS NULL`) **task** rows
        (`AND wi.type = 'task'`) — no milestone work item is ever included,
        regardless of its status, claim, or blocking state (FR-017). This
        is a `WHERE` predicate, not a post-filter a caller could bypass by
        reading the table directly. For each such item,
        `terminal` is `True` iff `status` is `done` or `superseded`, and
        `eligible` reflects the same Available-to-start computation User
        Story 2 already defines (data-model.md's "Available to start"),
        so a blocked or claimed item is never presented as eligible even
        though an unsophisticated coordinator adapter (Symphony's shipped
        `local` tracker, per the contract's load-bearing finding) would
        not otherwise re-check blocking itself.

        Derived from **one** `SELECT`, on **one** connection, rather than
        calling `list_available_work_items()` (its own connection) and
        then opening a second connection to read `id`/`title`/`status`:
        two separate reads left a window in which a claim could land
        between them, producing a stale `eligible=True` for an item whose
        `id`/`title`/`status` were read from a *different*, later
        snapshot than the one `eligible` was computed from. Expressing
        eligibility inline as `NOT EXISTS` claim/blocking subqueries in
        the same statement that selects `id`/`title`/`status` (mirroring
        data-model.md's "Available to start" query shape) makes *that*
        two-snapshot mixing structurally impossible — both facts are
        always computed from the same SQLite read snapshot in the same
        query, so one projected row can never combine eligibility and
        item state from two different points in time.

        This guarantees internal consistency of one projection, nothing
        more. It does NOT guarantee that no claim lands immediately after
        this query's snapshot is taken and before the caller of
        `generate_projection()` acts on the result — another process can
        always issue a competing `claim()` in that gap, and this method
        cannot and does not prevent it. That is ordinary, unavoidable
        staleness inherent to any generated/disposable snapshot
        (contracts/coordinator-projection.md already describes a
        projection this way), not something a single-query fix
        eliminates. Actual dispatch/acquisition safety comes from
        `claim()`'s own atomic arbitration (the primary-key-constraint
        mechanism in data-model.md's "Claim atomicity contract"), not
        from projection freshness — a coordinator MUST still attempt
        `claim()` before treating an item as acquired; this projection is
        advisory, never a reservation.

        Purely a read: opens exactly one `SELECT` connection, and never
        mutates the ledger. Deterministic for unchanged ledger state —
        ordered by `id` — so regenerating it twice produces an equal
        (`==`) list (spec.md SC-005, Acceptance Scenario 4.2).
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

    # -- specs/003-symphony-task-integration: published, external
    # projection (User Story 2) — a separate, additional query, never a
    # modification of generate_projection()/ProjectedWorkItem above --------

    def generate_external_projection(self) -> list[ExternalProjectionRow]:
        """Generate the row set for the published, external Symphony
        projection (data-model.md's "New WorkLedger methods" ->
        `generate_external_projection()`).

        Deliberately a second, independent query from `generate_projection()`
        above, not a transformation of its result: specs/003's own
        published contract (contracts/symphony-projection-v1.md) is a
        physically separate artifact with its own shape and version, and
        must never be coupled to `generate_projection()`/`ProjectedWorkItem`'s
        own, unchanged internal contract (FR-019, research.md's "Decision:
        published projection storage location and format"). The two
        queries happen to share the same `_STILL_BLOCKING_CONDITION`
        fragment only because both need the identical "is this dependency
        still blocking" predicate — reusing that one shared fragment,
        rather than writing a second, independently-maintained copy of it,
        is the only thing they share.

        Restricted to non-archived task rows only (`WHERE wi.archived_at
        IS NULL AND wi.type = 'task'`) — a structural `WHERE` predicate,
        not a post-filter, so no milestone work item can ever appear here
        regardless of its own status, claim, or blocking state (FR-014,
        SC-007). `dispatchable` is computed inline, in the same single
        `SELECT` that reads `id`/`title`/`description`/`status`/
        `created_at`, for the same "one snapshot, not two" reason
        `generate_projection()`'s own docstring already explains in
        detail — see there rather than repeating it here. `created_at` is
        read straight off the canonical row, never derived: this query is
        the only place it is read, so there is nothing to keep in sync.

        `identifier` (FR-015) is derived purely from `id` by replacing
        every `:` with `-` (research.md's "Decision: identifier derivation
        for external workspace naming") — a fixed, deterministic string
        transform, never a second, independently-assigned identity.

        Deterministic for unchanged ledger state (`ORDER BY id`, mirroring
        `generate_projection()`'s own determinism guarantee) — regenerating
        it twice from an unchanged ledger produces an equal (`==`) list
        (SC-006).

        Purely a read: opens exactly one connection and one `SELECT`, and
        never mutates the ledger.
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

    # -- Polish: archival ----------------------------------------------

    def archive_work_item(self, id: str) -> bool:
        """Archive a terminal work item in place (T038, FR-020/FR-021, SC-008).

        data-model.md's "Archival" transaction: thins a terminal row's
        non-essential columns to `NULL`, stamps `archived_at`, and — in the
        same transaction — deletes this item's own Evidence Pointers, its
        own declared `blocked_by` edges (never edges other items declare
        against it, since those continue to resolve against this row's
        untouched `id`/`type`/`status`/`superseded_by`), and any lingering
        claim row (defensive; no claim is expected to remain). `id`,
        `type`, `status`, and `superseded_by` are never cleared, so any
        other item's blocking evaluation — or a task's `parent_id`
        resolution, per specs/002 — naming this id keeps resolving exactly
        as before archival (research.md's "Decision: retention";
        data-model.md's "Dependency resolution"). A task's terminal set is
        `done`/`superseded`; a milestone's is `accepted`/`superseded`
        (specs/002 FR-005) — both are accepted here.

        specs/002-milestone-task-work-items FR-015: archiving a
        `type='milestone'` row is refused outright while any child
        (`parent_id` naming it) has a status outside `('done', 'superseded')`
        — a child is always a `task`, which per FR-005 can never itself be
        `accepted` (that is a milestone-only status), so the child-status
        check does not list it. This precondition is embedded directly in
        the guarded `UPDATE`'s own `WHERE` clause below, inside the same
        `BEGIN IMMEDIATE` transaction as the mutation itself — mirroring
        `mark_in_review`'s own FR-010 pattern (`_review_ready_sql`) rather
        than checking it with a separate statement beforehand. A check
        performed *before* opening the transaction would leave a race
        window open: another writer could insert a new open child, or
        reopen/re-review a resolved one, between that check and this
        method's own mutation, letting a milestone be archived with an
        unresolved child underneath it — the same class of check-then-act
        race FR-010 already closes for `mark_in_review`. Embedding the
        condition inline closes that window: `BEGIN IMMEDIATE` acquires
        SQLite's write lock for the whole transaction, so no concurrent
        writer can insert or mutate a child row between the precondition's
        evaluation and the `UPDATE` that reads it — one atomic statement's
        row-count is the sole arbitration mechanism, never a check-then-act
        pair. This precondition is harmless for a task (which has no
        children by construction) and so is not conditioned on `type` here.

        specs/002-milestone-task-work-items FR-015a: the reverse direction
        of the same problem. Review-readiness (`is_review_ready`) is
        computed from each child's current status and evidence — but
        archiving an attributed, resolved (`done`/`superseded`) child task
        deletes that child's own evidence rows (see the cleanup `DELETE`s
        below), which can silently invalidate a parent milestone's
        readiness, or the evidence that justified an `open`/`review`
        milestone's readiness at the moment `mark_in_review`/
        `accept_milestone` ran, entirely underneath it. An attributed task
        (`parent_id IS NOT NULL`) is therefore refused archival while its
        parent milestone's status is `open` or `review`; it is permitted
        once the parent has reached `accepted` or `superseded` (its
        children can never change again after that point) or when the task
        has no `parent_id` at all (001's original, unattributed-task
        behavior, entirely unchanged). Same atomicity requirement and
        mechanism as the FR-015 precondition above: embedded as a
        correlated `EXISTS` against the *current* row's own `parent_id`
        directly in this `UPDATE`'s `WHERE` clause, inside the same
        `BEGIN IMMEDIATE` transaction, so a concurrent `accept_milestone`/
        `mark_in_review`/`decline_review` on the parent cannot land between
        a separate readiness check and this mutation. SQLite serializes
        writers to one at a time regardless of transaction shape (a single
        guarded `UPDATE` like `accept_milestone`'s is already atomic under
        `connect()`'s autocommit mode, exactly like this method's own
        `BEGIN IMMEDIATE`), so a concurrent `accept_milestone(parent)` and
        `archive_work_item(child)` always serialize to one of exactly two
        valid outcomes: this archival's `BEGIN IMMEDIATE` acquires the
        write lock first and evaluates the parent as still `review`
        (refused; `accept_milestone` then proceeds and succeeds
        afterward), or `accept_milestone`'s `UPDATE` commits first and this
        archival's subsequent `BEGIN IMMEDIATE` observes the already-
        `accepted` parent (archival succeeds). Archival succeeding against
        a parent that is still `open` or `review` is not a reachable
        outcome of either ordering.

        Returns `True` iff the `UPDATE` actually matched a row — i.e.
        `id` exists, was at the moment this ran in one of its type's
        terminal statuses, was not yet archived, had no unresolved child
        (if a milestone), and had no attributed parent still `open` or
        `review` (if a task with a `parent_id`). Returns `False` otherwise
        — a true, guarded no-op, not an error, mirroring `mark_done`/
        `mark_superseded`'s own "guarded transition returns whether it
        applied" convention: when the `UPDATE` does not match, the cleanup
        `DELETE`s below are skipped entirely. Re-running this on an
        already-archived item is a true no-op: the guard includes `AND
        archived_at IS NULL`, so `archived_at`/`updated_at` are left
        exactly as the first archival set them, never bumped forward
        (data-model.md's "`archived_at`... `NULL` until archived, then
        permanent").
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
