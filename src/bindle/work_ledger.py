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

        data-model.md's "Derived facts" → "Blocked", exactly: any
        `blocked_by` row for this item that resolves to an `open`
        dependency, or to no row at all (a dangling reference, treated
        conservatively as still blocking per FR-021), counts as blocking.
        A dependency resolved as `done` or `superseded` — whether still
        active or archived-and-thinned, since `status` is never cleared by
        archival — does not block.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT EXISTS (
                  SELECT 1 FROM work_item_blocked_by e
                  LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
                  WHERE e.work_item_id = ?
                    AND (dep.id IS NULL OR dep.status = 'open')
                )
                """,
                (work_item_id,),
            ).fetchone()
            return bool(row[0])
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
        """List the ids of every item currently available to start (T017).

        The composite query from data-model.md's "Derived facts" →
        "Available to start": `status = 'open'` AND not claimed AND not
        blocked. Returns ids only (mirroring the data-model.md query,
        which selects only `id`), ordered by `id` for determinism.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id FROM work_items wi
                WHERE wi.status = 'open'
                  AND NOT EXISTS (
                    SELECT 1 FROM work_item_claims c WHERE c.work_item_id = wi.id
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM work_item_blocked_by e
                    LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
                    WHERE e.work_item_id = wi.id
                      AND (dep.id IS NULL OR dep.status = 'open')
                  )
                ORDER BY wi.id
                """
            ).fetchall()
            return [row[0] for row in rows]
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
        foreign-key violation, not a uniqueness violation) and is
        re-raised rather than swallowed into a `False` return — SQLite's
        own error messages distinguish the two ("UNIQUE constraint
        failed" vs. "FOREIGN KEY constraint failed").
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
            if "UNIQUE constraint failed" in str(exc):
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

    def reconcile(self) -> list[ReconciliationFinding]:
        """Run a read-only Reconciliation Report (FR-010).

        Compares recorded ledger state against observed repository state
        (currently: claim `worktree_path` existence) and internal
        consistency (claim row-shape, whole-database integrity, dangling
        blocking edges, duplicate sources, blocking cycles), per
        data-model.md's "Reconciliation Report". Every query below is a
        `SELECT`; this method never opens a write transaction and never
        mutates `work_items`, `work_item_claims`, `work_item_blocked_by`,
        or `work_item_evidence` — finding a claim stale or corrupt does
        not, by itself, change whether an item is computed as available
        (research.md's "Decision: claim safety").

        Scoped to the five finding types this slice has explicit task
        coverage for: `stale_claim`, `corrupt_claim`, `dangling_blocker`,
        `duplicate_source`, and `cycle_detected`. `dangling_evidence`
        (data-model.md's Reconciliation Report field list names it as a
        possible finding type) is deliberately not implemented here — it
        would require Git-branch-existence checking this module does not
        otherwise perform, and is out of scope for this slice.
        """
        findings: list[ReconciliationFinding] = []
        conn = self._connect()
        try:
            # stale_claim: a recorded worktree_path that no longer exists
            # as a directory. A claim with worktree_path IS NULL is not
            # checked by this signal — this module does not shell out to
            # Git to check branch-only existence (data-model.md's
            # "Staleness": a documented, acknowledged gap, not an
            # omission).
            for work_item_id, worktree_path in conn.execute(
                "SELECT work_item_id, worktree_path FROM work_item_claims "
                "WHERE worktree_path IS NOT NULL"
            ).fetchall():
                if not os.path.isdir(worktree_path):
                    findings.append(
                        ReconciliationFinding(
                            item_id=work_item_id,
                            finding="stale_claim",
                            detail=f"worktree_path {worktree_path!r} does not exist",
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
