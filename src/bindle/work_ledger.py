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
from collections.abc import Sequence


class SchemaVersionError(RuntimeError):
    """Raised when an existing ledger's schema version is unexpected."""


_LEDGER_DIR_NAME = ".bindle-work"
_LEDGER_FILE_NAME = "ledger.sqlite3"

# PRAGMA user_version — see research.md's "Decision: schema versioning and
# migration ownership". Bump this and add an explicit migration step keyed
# by the version it moves *from* when the schema next changes.
_SCHEMA_VERSION = 1

# data-model.md's "Schema overview", verbatim.
_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE work_items (
      id                TEXT PRIMARY KEY,
      title             TEXT,
      status            TEXT NOT NULL CHECK (status IN ('open', 'done', 'superseded')),
      superseded_by     TEXT REFERENCES work_items(id),
      source_kind       TEXT CHECK (source_kind IN ('speckit_task', 'plan', 'adhoc')),
      source_locator    TEXT,
      source_promoted_by TEXT,
      created_at        TEXT,
      updated_at        TEXT NOT NULL,
      archived_at       TEXT,
      CHECK (
        (status = 'superseded' AND superseded_by IS NOT NULL) OR
        (status != 'superseded' AND superseded_by IS NULL)
      )
    )
    """,
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


def _ensure_schema(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        # PRAGMA user_version does not accept `?` bind parameters; the
        # value here is always the fixed internal constant above, never
        # caller-provided input.
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    elif version != _SCHEMA_VERSION:
        raise SchemaVersionError(
            f"ledger at schema version {version}, expected {_SCHEMA_VERSION}"
        )


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
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 2000")
    _ensure_schema(conn)
    return conn


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


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
    exactly: an archived item has `title`, `source_kind`, `source_locator`,
    `source_promoted_by`, and `created_at` cleared to `None`, while `id`,
    `status`, `superseded_by`, `updated_at`, and `archived_at` remain
    populated as appropriate.
    """

    id: str
    title: str | None
    status: str
    superseded_by: str | None
    source_kind: str | None
    source_locator: str | None
    source_promoted_by: str | None
    created_at: str | None
    updated_at: str
    archived_at: str | None


_WORK_ITEM_COLUMNS = (
    "id",
    "title",
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

    # -- User Story 1: create/read -----------------------------------

    def create_work_item(
        self,
        id: str,
        title: str,
        source_kind: str,
        source_locator: str,
        source_promoted_by: str | None = None,
        blocked_by: Sequence[str] = (),
    ) -> None:
        """Create a Work Item — the only operation that creates one (FR-002/FR-003).

        `status` is always `open` at creation. When `blocked_by` is given,
        the item and its initial dependency edges are created in one
        transaction (research.md's "Create a work item, optionally with
        initial `blocked_by` edges" mutation) — all-or-nothing, so an item
        is never recorded with only some of its declared dependencies.
        """
        now = _now()
        insert_item = (
            "INSERT INTO work_items "
            "(id, title, status, source_kind, source_locator, source_promoted_by, "
            "created_at, updated_at) "
            "VALUES (?, ?, 'open', ?, ?, ?, ?, ?)"
        )
        params = (id, title, source_kind, source_locator, source_promoted_by, now, now)

        conn = self._connect()
        try:
            if not blocked_by:
                conn.execute(insert_item, params)
                return
            with _transaction(conn):
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
