# Phase 1 Data Model: Durable Work Ledger

This is a conceptual relational data model (tables, columns, constraints, and invariants), not a full implementation. Naming details left open here (exact index names, the database file's exact path/name) are deferred to the first implementation slice; the *shape* below — the tables, their columns, their constraints, and the queries used to derive facts from them — is what this plan fixes.

**2026-08-26 persistence-model correction**: this revision replaces the original per-item-TOML-file data model (a Work Item file, a separate Claim Record file, a separate Tombstone file) with a SQLite relational schema, per `research.md`'s "Decision: storage format" and the decisions immediately following it. The domain concepts (Work Item, Claim, Blocking Reference, Evidence Pointer, Source Reference, Reconciliation Report) are unchanged from spec.md's Key Entities; what changes is how each is represented and how facts are derived. Where a domain rule genuinely simplifies under SQLite (dependency resolution across archival, in particular) that simplification is called out explicitly, per this correction's own instruction not to mechanically translate the old file-based mechanism.

## Schema overview

Four tables. No ORM, ordinary `CREATE TABLE` statements executed once at initialization (see `research.md`'s "Decision: schema versioning").

```sql
CREATE TABLE work_items (
  id                TEXT PRIMARY KEY,
  title             TEXT,                 -- NOT NULL while active; cleared at archival
  status            TEXT NOT NULL CHECK (status IN ('open', 'done', 'superseded')),
  superseded_by     TEXT REFERENCES work_items(id),
  source_kind       TEXT CHECK (source_kind IN ('speckit_task', 'plan', 'adhoc')),
                                           -- NOT NULL while active; cleared at archival
  source_locator    TEXT,                 -- NOT NULL while active; cleared at archival
  source_promoted_by TEXT,                -- optional even while active; cleared at archival
  created_at        TEXT,                 -- ISO-8601; NOT NULL while active; cleared at archival
  updated_at        TEXT NOT NULL,        -- ISO-8601; set on every mutation to this row
  archived_at       TEXT,                 -- ISO-8601; NULL until archived, then permanent
  CHECK (
    (status = 'superseded' AND superseded_by IS NOT NULL) OR
    (status != 'superseded' AND superseded_by IS NULL)
  )
);

CREATE TABLE work_item_blocked_by (
  work_item_id      TEXT NOT NULL REFERENCES work_items(id),
  blocked_on_id     TEXT NOT NULL REFERENCES work_items(id),
  PRIMARY KEY (work_item_id, blocked_on_id),
  CHECK (work_item_id != blocked_on_id)
);

CREATE TABLE work_item_claims (
  work_item_id      TEXT PRIMARY KEY REFERENCES work_items(id),
  owner             TEXT NOT NULL,
  claimed_at        TEXT NOT NULL,        -- ISO-8601
  worktree_path     TEXT,
  branch            TEXT
);

CREATE TABLE work_item_evidence (
  evidence_id       INTEGER PRIMARY KEY,  -- surrogate key; evidence has no natural id
  work_item_id      TEXT NOT NULL REFERENCES work_items(id),
  kind              TEXT NOT NULL CHECK (kind IN ('branch', 'commit', 'pull_request', 'other')),
  value             TEXT NOT NULL,
  recorded_at       TEXT NOT NULL,        -- ISO-8601
  note              TEXT
);
```

Every connection that opens this database sets `PRAGMA foreign_keys = ON` (mandatory — see `research.md`'s "Decision: connection lifecycle"); the foreign keys above are not decorative, they are the write-time half of the dependency-integrity guarantee described below.

## Work Item (`work_items`)

One decomposed, independently claimable unit of implementation work. One row per item, present in the same table for its entire lifetime — a row is never deleted by this model, only thinned in place at archival (see "Archival" below).

| Column | Type | Required (active) | Required (archived) | Notes |
|---|---|---|---|---|
| `id` | TEXT, primary key | yes | yes | Stable identifier, assigned at creation, never reused or reassigned. Independent of session/worktree/branch (FR-001). |
| `title` | TEXT | yes | cleared to `NULL` | Short human-readable summary. |
| `status` | TEXT, `CHECK` enum | yes | yes | Coarse status only (FR-005): `open` \| `done` \| `superseded`. Default `open` at creation. |
| `superseded_by` | TEXT, `REFERENCES work_items(id)` | only when `status = 'superseded'` | same | Mirrors `docs/DECISIONS.md`'s "superseded in place" convention (FR-016). Enforced paired with `status` by the table's own `CHECK` constraint — the pairing cannot be left inconsistent by any single statement. |
| `source_kind` / `source_locator` / `source_promoted_by` | TEXT | `source_kind`/`source_locator` yes, `source_promoted_by` optional | cleared to `NULL` | The Source Reference (FR-002), embedded directly as columns — no separate table, matching the original "embedded, not a separate file" shape. See "Source Reference" below. |
| `created_at` | TEXT (ISO-8601) | yes | cleared to `NULL` | Set once at creation. |
| `updated_at` | TEXT (ISO-8601) | yes | yes (set to the archival timestamp) | Set on every mutation to this row (not a mutation to a different item that merely references it, and not a mutation to this item's claim — a separate table with its own lifecycle). |
| `archived_at` | TEXT (ISO-8601) | `NULL` | yes | `NULL` until the item is archived; permanent and never cleared once set. Distinguishes "this row is a thinned, archived record" from "this row is still active" without inferring it from which other columns happen to be `NULL`. |

**`blocked_by`** is not a column on this table — it is represented by rows in `work_item_blocked_by` (below), one row per declared dependency edge, so that adding, listing, and resolving dependencies are ordinary relational operations rather than a serialized list field.

**Invariants**:
- The `status`/`superseded_by` pairing is enforced by the table's own `CHECK` constraint (above) — not by application discipline alone.
- `work_item_blocked_by`'s own `CHECK (work_item_id != blocked_on_id)` rejects a direct self-cycle at write time. Longer cycles (`A` blocked-by `B`, `B` blocked-by `A`, formed by two independently-written edges) remain a *detectability* requirement on the reader — see "Cycle detection" below — since no single-row constraint can see across rows.
- `blocked_by` edges are a **declared, historical set**, not a live "currently-blocking" list: nothing in this model prunes, rewrites, or replaces a row in `work_item_blocked_by` when the referenced item resolves. "Is this still blocking, right now" is always computed fresh (below), never by mutating the declaration.
- `work_items` rows are **never deleted** by this model. Archival thins a row in place; it does not remove it. This is the property that lets dependency resolution stay a single-table lookup — see below.

## Dependency resolution (resolving one `blocked_by` edge)

Resolving whether `work_item_id` is currently blocked by `blocked_on_id` is a single lookup, regardless of whether the referenced item is still active or has been archived-and-thinned:

```sql
SELECT status, superseded_by FROM work_items WHERE id = :blocked_on_id;
```

- **A row is returned** → its `status` governs directly: `open` → **still blocking**; `done` or `superseded` → **satisfied** (superseded counts as resolved-for-blocking-purposes, unchanged from the original rule: the named piece of work will not be produced under that identity, and if the dependency still matters, re-pointing to whatever superseded it is an explicit act, not something this model infers). This holds identically whether the row is active or has been archived and thinned, because `status` and `superseded_by` are exactly the two columns archival guarantees are never cleared (see "Archival" below) — there is no second table to fall back to.
- **No row is returned** → **Dangling** — genuinely unresolvable. Because `work_items` rows are never hard-deleted, this can now only mean the id never validly referenced a work item (a typo or write-time mistake), or the database was written to outside the normal, constrained write path (see `research.md`'s "Decision: dependency resolution across archival"). A Dangling reference is treated **conservatively as still blocking** (never silently treated as satisfied) and surfaced by reconciliation as `dangling_blocker`.

**This is the single-table simplification SQLite enables**: the original file-based model needed a two-step lookup (active item, then a separate Tombstone) specifically because archiving an item meant replacing its file with a smaller one elsewhere. Because archival here thins the same row rather than relocating the fact, there is only ever one place to look.

**Foreign key enforcement**: `work_item_blocked_by.blocked_on_id REFERENCES work_items(id)`, checked at write time whenever `PRAGMA foreign_keys = ON` (mandatory per connection). In the normal write path this means a `blocked_by` edge naming a nonexistent id is rejected immediately when declared, not merely discovered later by reconciliation. `dangling_blocker` remains a defined reconciliation finding as a defense-in-depth check for the case where a connection ran without foreign keys enabled, or the database file was modified outside Bindle's own write path — its meaning (surfaced, conservatively still-blocking) is unchanged; its expected frequency in ordinary use is now much lower.

**Derived facts** (computed on demand by query, never stored):
- **Blocked**: `work_item_id` is blocked iff any row in `work_item_blocked_by` for it resolves (above) to "still blocking" or "Dangling":
  ```sql
  SELECT EXISTS (
    SELECT 1 FROM work_item_blocked_by e
    LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
    WHERE e.work_item_id = :id
      AND (dep.id IS NULL OR dep.status = 'open')
  );
  ```
- **Claimed**: `work_item_id` is claimed iff a row exists in `work_item_claims` for it — never a column on `work_items` itself:
  ```sql
  SELECT EXISTS (SELECT 1 FROM work_item_claims WHERE work_item_id = :id);
  ```
- **Available to start** (User Story 2): `status = 'open'` AND not Claimed AND not Blocked. Staleness of an existing claim does **not** change this computation — see "Claims" → "Staleness" below; a stale claim still counts as Claimed until explicitly released. As one query enumerating every available item:
  ```sql
  SELECT id FROM work_items wi
  WHERE wi.status = 'open'
    AND NOT EXISTS (SELECT 1 FROM work_item_claims c WHERE c.work_item_id = wi.id)
    AND NOT EXISTS (
      SELECT 1 FROM work_item_blocked_by e
      LEFT JOIN work_items dep ON dep.id = e.blocked_on_id
      WHERE e.work_item_id = wi.id
        AND (dep.id IS NULL OR dep.status = 'open')
    );
  ```

**Cycle detection** (indirect cycles only — a direct self-cycle is rejected at write time by the `CHECK` constraint above): a `WITH RECURSIVE` query walks the `blocked_by` graph and reports any item that can reach itself:
```sql
WITH RECURSIVE reachable(start_id, id) AS (
  SELECT work_item_id, blocked_on_id FROM work_item_blocked_by
  UNION
  SELECT r.start_id, e.blocked_on_id
  FROM reachable r JOIN work_item_blocked_by e ON e.work_item_id = r.id
)
SELECT DISTINCT start_id FROM reachable WHERE id = start_id;
```
This is a graph-reachability query, not a scheduler or dependency/DAG solver — it computes no ordering, priority, or dispatch decision (unchanged constraint, FR-015).

## Claims (`work_item_claims`)

**A separate table, not a column on `work_items`** — this is the direct fix for the read-modify-write race a claim column on the item's own row would otherwise create (`research.md`, "Decision: claim atomicity"). Existence of a row in `work_item_claims` for a given `work_item_id` *is* the claim; there is no additional "claimed" flag anywhere else to fall out of sync with it.

| Column | Type | Required | Notes |
|---|---|---|---|
| `work_item_id` | TEXT, primary key, `REFERENCES work_items(id)` | yes | The item this claim is for; the primary key is the arbitration mechanism (see below). |
| `owner` | TEXT | yes | Identifies who claimed it — an agent/session label or a person's name; format not prescribed by this plan. |
| `claimed_at` | TEXT (ISO-8601) | yes | |
| `worktree_path` | TEXT | no | Absolute path to the worktree the claim is being worked in, when applicable. Per `docs/WORKTREES.md`, this is machine-local and not a portable identifier — it exists for reconciliation, not cross-machine addressing. |
| `branch` | TEXT | no | Descriptive only (`docs/WORKTREES.md`: "Branch names are descriptive context, never primary identity") — never used as the sole way to find the work. |

### Claim atomicity contract (FR-018)

- **Acquire**: `INSERT INTO work_item_claims (work_item_id, owner, claimed_at, worktree_path, branch) VALUES (:id, :owner, :now, :worktree_path, :branch);` The primary key on `work_item_id` is the arbitration mechanism: of any number of concurrent `INSERT` attempts against the same `work_item_id`, SQLite's own constraint enforcement plus its single-writer transaction serialization guarantee exactly one succeeds; every other attempt fails immediately with a primary-key constraint violation — never a timeout, never an ambiguous result, never a window where two callers could both believe they hold the claim.
- **Content is not the arbitration mechanism**: the *existence* of the row decides ownership; `owner`/`claimed_at`/`worktree_path`/`branch` are written as part of the same `INSERT` and are purely descriptive.
- **Crash/interruption**: a single `INSERT` statement is transactionally atomic — it either commits in full (the row exists with every `NOT NULL` column populated) or is rolled back entirely if the process crashes before commit (the row does not exist at all). There is **no reachable intermediate state**, via an ordinary application crash during acquisition, in which a claim row exists but is missing its content — this is a genuine improvement over the original file-based design's crash window, not merely a change in representation (see `research.md`'s "Decision: claim atomicity" for the full reasoning). `corrupt_claim`, as a reconciliation finding, is retained for the narrower cases that can still produce an inconsistent row: database-file-level corruption (detectable via `PRAGMA integrity_check`), or a connection that ran with constraints bypassed. It is not, under normal operation, produced by a mid-acquire crash.
- **Safe release**: releasing a claim is `DELETE FROM work_item_claims WHERE work_item_id = :id;`. Deleting a row that does not exist affects zero rows and is treated as a no-op (idempotent release, not an error). An ordinary release (by the recorded owner) is unconditional; a release by anyone else is an **override** and MUST only be performed after observing reconciliation evidence justifying it (`stale_claim` or `corrupt_claim` — see "Staleness" below) — this is a documented process expectation on the caller, not something the schema itself can cryptographically enforce, consistent with this repository's existing single-operator trust model.
- **Multi-worktree correctness**: guaranteed because claim rows live in the same Git-common-directory-scoped database as work items (unchanged storage-location decision) — every linked worktree on the machine opens the exact same file, not a per-worktree copy, so SQLite's own constraint and locking guarantees are shared across every worktree by construction.
- **Explicitly not guaranteed**: atomic claiming of *multiple different* items as one transaction (spec.md's Assumptions) — each item's claim is acquired independently via its own `INSERT`; there is no "claim these three items or none" operation. Wrapping several independent claim attempts in one SQL transaction would not change this: each `INSERT` still succeeds or fails independently within it, and this model does not introduce an operation that rolls all of them back together on a single failure.

### Staleness — does not change availability automatically

- **Staleness determination**: a claim is **stale** when its recorded `worktree_path` no longer exists as a worktree on this machine (or, when `branch` is also recorded, that branch itself is gone). This is determined *only* by checking currently observable repository/filesystem state at the moment reconciliation runs — never by elapsed time, a heartbeat, or a lease expiry. No background process is required or assumed; reconciliation issues `SELECT * FROM work_item_claims` and checks each row's `worktree_path`/`branch` against the filesystem/Git.
- **A stale (or corrupt) claim still makes the item unavailable** under the "Available to start" computation above. Reconciliation surfaces staleness; it does not clear it — reconciliation never opens a write transaction against this table. This preserves the existing "reconciliation is read-only" posture (`research.md`, "Decision: claim safety") without exception.
- **Recovery is the explicit override release** defined above: an actor who has just observed a `stale_claim` or `corrupt_claim` reconciliation finding for a specific item may `DELETE` that claim row on that basis. This can happen the instant staleness is noticed — "explicit" means "on demand, whenever someone acts," not "after waiting out a timer."
- **Release and reacquisition are two independent operations, not one atomic replacement.** Deleting a stale/corrupt claim row makes the item unclaimed and claimable again by anyone — it does not itself grant the deleting actor a claim. An actor that immediately attempts to acquire a new claim afterward is racing every other concurrent acquire attempt exactly as in any other acquisition ("Claim atomicity contract" above): it MUST check that its own `INSERT` succeeded before assuming ownership, since another actor's concurrent attempt may legitimately win instead — in which case the overriding actor's own attempt fails with the ordinary primary-key-violation result and it holds no claim on the item. No mechanism in this model makes the delete-then-insert sequence atomic across the two steps as a single unit granted to one caller; only each statement individually is atomic on its own.
- **Evidence surfaced before an override**: the specific reconciliation finding for that item — which check was performed (worktree path or branch), and that it came back absent — so an override is never performed blind. Recording *why* a specific override happened is optional, not a mandatory column: an Evidence Pointer (`kind = 'other'`) MAY be inserted noting the override, in the same transaction as the release (see `research.md`'s "Decision: transaction boundaries") — using the entity this model already has, rather than inventing a new audit-log concept.
- **Explicitly not solved by this model**: a claim whose worktree still exists but whose owner has simply stopped working (no absence to detect). This is a genuine, acknowledged gap — no automatic mechanism claims to catch it (per this feature's own constraint against leases/heartbeats/timeouts); a human noticing and applying judgment remains the only recourse, and they may still use the same override release, self-justified rather than reconciliation-justified, at their own discretion.

## Archival (thinning a terminal item in place)

Runs once a Work Item has reached `done` or `superseded` and has been reconciled (Bindle's own reconciliation-against-repository-state — never satisfied by, or waiting on, an external coordinator's projection). Archival does not create a separate artifact and does not delete the row — it thins it in place, inside one transaction (see `research.md`'s "Decision: transaction boundaries"):

```sql
BEGIN IMMEDIATE;
UPDATE work_items
  SET title = NULL, source_kind = NULL, source_locator = NULL,
      source_promoted_by = NULL, created_at = NULL,
      archived_at = :now, updated_at = :now
  WHERE id = :id AND status IN ('done', 'superseded');
DELETE FROM work_item_evidence WHERE work_item_id = :id;
DELETE FROM work_item_blocked_by WHERE work_item_id = :id;  -- edges this item declared, never edges other items declare against it
DELETE FROM work_item_claims WHERE work_item_id = :id;      -- defensive; no claim is expected to remain
COMMIT;
```

**What survives archival forever**: `id`, `status`, `superseded_by`, `archived_at`. This is the direct analogue of the original file-based model's three-field Tombstone, plus one operational timestamp (`archived_at`) the original design did not carry — a narrow, deliberate expansion, not a reintroduction of narrative history (see `research.md`'s "Decision: retention" for why this one column was added).

**What is discarded at archival**: `title`, `source_kind`/`source_locator`/`source_promoted_by`, `created_at`, every Evidence Pointer, every `blocked_by` edge this item itself declared (edges other items declare *against* it are untouched — see below), and any lingering claim.

**Why other items' edges are untouched**: `work_item_blocked_by` rows where this item is the `blocked_on_id` (i.e., another item declared a dependency on it) are not touched by this transaction — the archived item's own row still exists (thinned), so those edges continue to resolve exactly as before, via the same single-table lookup described in "Dependency resolution" above. Only edges where this item is the `work_item_id` (i.e., this item's *own* declared dependencies, which are moot once the item itself is terminal and archived) are deleted.

**Invariant**: because the row is never removed from `work_items`, there is no precondition check ("is anyone still blocked on me?") needed before archiving, and no window in which an item is gone but not yet resolvable — the transaction above either fully applies or fully does not, and the `id`/`status`/`superseded_by` columns it never touches remain resolvable throughout.

## Blocking Reference

Not a separate stored entity beyond the `work_item_blocked_by` row itself — modeled here only to name the concept precisely, since spec.md's Key Entities lists it as distinct from a Claim or Evidence Pointer: a Blocking Reference asserts *this item cannot be considered eligible until that item resolves*, nothing about ordering, priority, or who should work on either one (FR-015).

## Evidence Pointer (`work_item_evidence`)

A separate table, one row per pointer, rather than a serialized list column — so appending, listing, and (at archival) bulk-deleting an item's evidence are ordinary relational operations.

| Column | Type | Required | Notes |
|---|---|---|---|
| `evidence_id` | INTEGER, primary key | yes | Surrogate key — evidence has no natural identifier of its own. |
| `work_item_id` | TEXT, `REFERENCES work_items(id)` | yes | Which item this pointer belongs to. |
| `kind` | TEXT, `CHECK` enum | yes | `branch` \| `commit` \| `pull_request` \| `other`. |
| `value` | TEXT | yes | The pointer itself — a branch name, a commit SHA (full, per `docs/WORKTREES.md`'s own "full HEAD commit SHA" convention), a PR URL/number, or a free-form pointer for `other`. |
| `recorded_at` | TEXT (ISO-8601) | yes | |
| `note` | TEXT | no | Free-text context, e.g. why this pointer was added — including, optionally, a note explaining a stale/corrupt-claim override (see "Claims" above). |

**Invariant**: Evidence Pointers are append-only and immutable once recorded (mirroring `docs/WORKTREES.md`'s evidence-immutability rule: "Later Git operations do not rewrite existing evidence") — no `UPDATE` against this table is defined by this model. A rebased/squashed/deleted branch's pointer is left in place as a historical observation, not deleted or "fixed," except in bulk as part of the archival transaction above (D016 preservation discipline, applied at archival time, not applied by editing individual pointers beforehand).

## Source Reference

Embedded directly as columns on `work_items` (`source_kind`, `source_locator`, `source_promoted_by`) — not a separate table, matching the original "embedded, not a separate file" shape; a work item has exactly one source, so a join table would add nothing.

| Column | Type | Required | Notes |
|---|---|---|---|
| `source_kind` | TEXT, `CHECK` enum | yes (while active) | `speckit_task` \| `plan` \| `adhoc`. |
| `source_locator` | TEXT | yes (while active) | E.g. `specs/001-durable-work-ledger/tasks.md#T012`, `plans/active/2026-08-24-symphony-coordination-exploration.md#work`, or a free-form description when `source_kind = 'adhoc'`. |
| `source_promoted_by` | TEXT | no | Who/what made the explicit promotion decision (FR-003), for traceability — not a claim, not an owner. |

**Invariant**: `source_locator` is a pointer, never a copy of the source text — if the source document is later edited or superseded, the Work Item's own `source_locator` is not automatically updated (spec.md Edge Cases: "the model MUST NOT require the ledger to auto-track upstream document revisions").

**No uniqueness constraint on `(source_kind, source_locator)`, deliberately.** Two items may validly point at the same source — spec.md's own Edge Case requires that this duplication be made *visible*, not *prevented*: "The model MUST make the resulting duplication visible... rather than silently merging or silently allowing an ambiguous double-claim." A `UNIQUE` constraint would reject the second item outright, which is stronger than the spec requires and would actively break this behavior. Instead, `duplicate_source` remains a reconciliation finding, computed by query:
```sql
SELECT source_kind, source_locator, GROUP_CONCAT(id) AS item_ids
FROM work_items
WHERE archived_at IS NULL
GROUP BY source_kind, source_locator
HAVING COUNT(*) > 1;
```
This is a deliberate contrast with the `blocked_by` foreign key above, which *does* tighten a write-time guarantee — the two cases differ because a dangling blocker is always a mistake to be corrected, while a duplicate source is a legitimate, expected outcome the spec explicitly protects.

## Reconciliation Report

The read-only output of a reconciliation pass — not a stored entity, generated on demand from current `work_items`, `work_item_claims`, and `work_item_blocked_by` rows plus observed repository/filesystem state. Every query it runs is a `SELECT`; it never opens a write transaction.

| Field | Type | Notes |
|---|---|---|
| `item_id` | string | Which item this finding is about. |
| `finding` | enum: `stale_claim` \| `corrupt_claim` \| `dangling_blocker` \| `dangling_evidence` \| `cycle_detected` \| `duplicate_source` | See spec.md Edge Cases and this file's "Claims"/"Dependency resolution" sections for the scenario each finding corresponds to, and `research.md` for how the SQLite-native write-time guarantees (foreign keys, transactional claim acquisition) narrow when several of these findings can occur in practice without removing their meaning. |
| `detail` | string | Human-readable explanation, e.g. which worktree path was checked and found absent, or which `blocked_by` id resolved to no row at all. |

**Invariant**: Generating a Reconciliation Report never writes to `work_items`, `work_item_claims`, `work_item_blocked_by`, or `work_item_evidence` (FR-010). It never releases a stale/corrupt claim itself — that remains a separate, explicit act (see "Claims" → "Staleness").
