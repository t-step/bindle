# Data Model: Symphony Task Integration

This feature adds no new column and no new table to the internal ledger (`work_items`, `work_item_blocked_by`, `work_item_claims`, `work_item_evidence` are all unchanged from schema version 2, `specs/002-milestone-task-work-items/data-model.md`). It adds one new external artifact (a separate SQLite export file) and two new generic methods on `WorkLedger`.

## Source Reference (Spec Kit)

Not a stored entity of its own — a convention for populating the internal ledger's existing `source_kind`/`source_locator` columns (`specs/001-durable-work-ledger/data-model.md`).

| Field | Value |
|---|---|
| `source_kind` | Always `'speckit_task'` (already present in `work_items`' `CHECK` constraint, unused before this feature). |
| `source_locator` | `"{feature-directory-relative-path}/tasks.md#{task-id}"`, e.g. `specs/003-symphony-task-integration/tasks.md#T003`. `{feature-directory-relative-path}` is the `specs/NNN-slug` path relative to the repository root; `{task-id}` is the Spec Kit id exactly as written in `tasks.md` (`T003`, `T016a`, ...). |
| `source_promoted_by` | The identity string passed to the loading operation by its caller (a maintainer or automation identity) — same free-text convention 001/002 already use for this field; optional, per the existing schema. |

`work_items.id` for a loaded task is deterministically derived from this same pair: `"speckit:{feature-directory-name}:{task-id}"`, e.g. `speckit:003-symphony-task-integration:T003` (`{feature-directory-name}` is just the final path component, `003-symphony-task-integration`, not the full `specs/...` path — the `specs/` prefix and the `.md` suffix are redundant once `source_kind = 'speckit_task'` already establishes the source family). This id is a plain `TEXT PRIMARY KEY` value like any other work item's — no schema change is needed to accommodate its shape.

**Uniqueness across features (SC-004)**: Because `{feature-directory-name}` is itself unique (Spec Kit's own `create-new-feature.sh` numbering guarantees no two `specs/NNN-slug` directories share a name), and `{task-id}` is only required to be unique *within* one directory's `tasks.md`, the composite id is unique across the whole repository by construction.

## Loaded Task Work Item

An ordinary `work_items` row (`type = 'task'`) with no structural difference from any other task — distinguished only by its `source_kind`/`source_locator`/`id` shape above. Every existing 001/002 behavior (blocking, claiming, evidence, archival) applies to it unchanged.

| Field | Value at creation | Value on reload |
|---|---|---|
| `id` | Deterministic, per Source Reference above. | Unchanged (this *is* the idempotency key). |
| `type` | Always `'task'`. | Immutable, unchanged from 001/002. |
| `parent_id` | Always `NULL` — this feature never attributes a loaded task to a milestone; a maintainer may attribute it manually later via the existing `create_work_item`/ledger surface, outside this feature's scope. | Unchanged (this feature never sets or clears `parent_id`). |
| `title` | The task line's description text, up to its first sentence boundary or the whole remaining text if no clear boundary exists (loader's own parsing choice, not a schema concern). | **Declarative — re-synced** via `resync_declarative_fields()` if the source text changed. |
| `description` | The task line's full remaining text (including anything not captured in `title`), or `NULL` if the line has no content beyond a short title. | **Declarative — re-synced**, same as `title`. |
| `status` | Always `'open'` (`create_work_item()`'s own fixed behavior, unchanged). | **Runtime-owned — never touched.** |
| Claim (`work_item_claims`) | None at creation. | **Runtime-owned — never touched.** |
| Evidence (`work_item_evidence`) | None at creation. | **Runtime-owned — never touched.** |
| `blocked_by` edges | One per intra-file `Depends on:` reference resolved at load time (see research.md, "Decision: dependency loading order"). | **Additive only** — a newly declared edge not previously recorded is added; a previously recorded edge is never removed, even if the current `tasks.md` no longer declares it. |

## New `WorkLedger` methods (`src/bindle/work_ledger.py`)

Both are generic, coordinator- and Spec-Kit-agnostic additions to the existing ledger — no new table, no schema version bump.

### `resync_declarative_fields(id: str, title: str | None, description: str | None) -> bool`

A single guarded statement:

```sql
UPDATE work_items SET title = ?, description = ?, updated_at = ?
WHERE id = ? AND archived_at IS NULL
```

Returns `True` iff exactly one row was updated (mirrors `mark_done`'s own "guarded transition, returns whether it applied" convention). Touches no other column — in particular, never `status`, `type`, `parent_id`, `source_kind`, `source_locator`, or `source_promoted_by`.

### `generate_external_projection() -> list[ExternalProjectionRow]`

One `SELECT`, one connection, mirroring `generate_projection()`'s own single-query-for-snapshot-consistency shape and reusing the existing `_STILL_BLOCKING_CONDITION` SQL fragment verbatim (never a second, independently-maintained copy of the blocking predicate):

```sql
SELECT
  wi.id,
  wi.title,
  wi.description,
  wi.status,
  wi.created_at,
  (
    wi.status = 'open'
    AND NOT EXISTS (SELECT 1 FROM work_item_claims c WHERE c.work_item_id = wi.id)
    AND NOT EXISTS (
      SELECT 1 FROM work_item_blocked_by e
      LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
      WHERE e.work_item_id = wi.id AND <_STILL_BLOCKING_CONDITION>
    )
  ) AS dispatchable
FROM work_items wi
WHERE wi.archived_at IS NULL AND wi.type = 'task'
ORDER BY wi.id
```

```python
@dataclasses.dataclass(frozen=True)
class ExternalProjectionRow:
    id: str
    identifier: str   # derived: id with ':' replaced by '-'
    title: str | None
    description: str | None
    status: str        # the raw status string: 'open' | 'done' | 'superseded'
    dispatchable: bool
    created_at: str  # preserved verbatim from the canonical work item, never derived; v3's
                      # CHECK (archived_at IS NOT NULL OR created_at IS NOT NULL) on
                      # work_items structurally guarantees this for every archived_at IS
                      # NULL row this query returns (research.md, "Decision: created_at
                      # NOT NULL for live rows")
```

Deterministic for unchanged ledger state (same `ORDER BY id` guarantee `generate_projection()` already provides).

## Symphony Projection (published export file)

A wholly separate SQLite database file, not a table or view inside `ledger.sqlite3`.

**Location**: `{repo_root}/.bindle-work/symphony-projection.sqlite3`, where `repo_root` is `RepoInfo.repo_root` (the Git common directory) — the same resolution `ledger_path()` already uses, so every linked worktree sees the same file.

**Versioning**: `PRAGMA user_version = 1` for this shape (see research.md, "Decision: published projection versioning"). A future incompatible shape bumps this and ships as a new `contracts/symphony-projection-v2.md`.

**Schema** (one table, fully rewritten on every publish inside a single transaction):

```sql
CREATE TABLE task_projection (
  id           TEXT PRIMARY KEY,
  identifier   TEXT NOT NULL,
  title        TEXT,
  description  TEXT,
  status       TEXT NOT NULL,
  dispatchable INTEGER NOT NULL,  -- SQLite boolean convention: 0 or 1
  created_at   TEXT NOT NULL      -- preserved verbatim from the canonical work item
)
```

Populated directly from `WorkLedger.generate_external_projection()`'s result — one row per `ExternalProjectionRow`, no additional transformation. A milestone work item never appears here because `generate_external_projection()`'s own query already filters to `type = 'task'`, the same structural guarantee (`WHERE`, not a post-filter) `generate_projection()` already established for the existing internal contract.

**Regeneration**: `symphony_projection.publish(ledger: WorkLedger) -> str` (returns the export file's path) drops and recreates `task_projection` inside one transaction, so a reader never observes a partially-rewritten table. This is the only write path to the export file — nothing else in Bindle's code ever opens it for writing, and Bindle's own internal code never reads it back (it exists solely for an external reader).

## Write surface entities

No new stored entity — `claim_task`/`release_task`/`complete_task` (`src/bindle/symphony_projection.py`) are pure functions over the existing `work_item_claims` table via `WorkLedger.claim()`/`release_claim()`/`mark_done()`. Their only new behavior relative to those existing methods is a `type == 'task'` guard performed via `WorkLedger.get_work_item()` before delegating, rejecting a milestone id with a distinct result rather than allowing the underlying claim/release/mark_done call to proceed against it.

| Function | Delegates to | New behavior added |
|---|---|---|
| `claim_task(ledger, id, owner, worktree_path=None, branch=None)` | `WorkLedger.claim()` | Reject if `get_work_item(id)` is `None` or `type != 'task'`. |
| `release_task(ledger, id, owner)` | `WorkLedger.release_claim()` | Reject if `get_work_item(id)` is `None` or `type != 'task'`. |
| `complete_task(ledger, id)` | `WorkLedger.mark_done()` | Reject if `get_work_item(id)` is `None` or `type != 'task'`. |

Each function's return shape distinguishes "rejected: not a task / does not exist" from the underlying delegate's own success/failure result, so a caller (including the CLI) can report the correct one of the three distinct outcomes spec.md's Edge Cases and Acceptance Scenarios require (not-found, wrong-type, or the ordinary claim/release/done result).
