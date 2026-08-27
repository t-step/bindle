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

from .work_ledger import WorkLedger, ledger_path

_PROJECTION_FILE_NAME = "symphony-projection.sqlite3"

# The published export file's own `PRAGMA user_version` — independent of
# the internal ledger's `_SCHEMA_VERSION` (research.md's "Decision:
# published projection versioning"). A future incompatible shape change
# ships as `contracts/symphony-projection-v2.md` alongside a bump of this
# constant, mirroring the `coordinator-projection.md` ->
# `coordinator-projection-v2.md` precedent specs/002 already established.
_PROJECTION_VERSION = 1

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
    rows = ledger.generate_external_projection()

    conn = sqlite3.connect(export_path, isolation_level=None)
    try:
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
            # PRAGMA user_version does not accept `?` bind parameters; the
            # value here is always the fixed internal constant above,
            # never caller-provided input.
            conn.execute(f"PRAGMA user_version = {_PROJECTION_VERSION}")
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
