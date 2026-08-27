# Phase 1 Data Model: Milestone and Task Work Items

This revises `specs/001-durable-work-ledger/data-model.md`'s `work_items` table only. `work_item_blocked_by`, `work_item_claims`, and `work_item_evidence` are unchanged in shape (their `REFERENCES work_items(id)` foreign keys now also implicitly span both types, since both live in the same table — no column or constraint on those three tables changes).

## Schema overview (v2)

```sql
CREATE TABLE work_items (
  id                TEXT PRIMARY KEY,
  type              TEXT NOT NULL CHECK (type IN ('task', 'milestone')),
  parent_id         TEXT REFERENCES work_items(id),
  title             TEXT,                 -- NOT NULL while active; cleared at archival
  description       TEXT,                 -- optional; cleared at archival, same lifecycle as title
  status            TEXT NOT NULL,
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
  ),
  CHECK (
    (type = 'task' AND status IN ('open', 'done', 'superseded')) OR
    (type = 'milestone' AND status IN ('open', 'review', 'accepted', 'superseded'))
  ),
  CHECK (
    (type = 'milestone' AND parent_id IS NULL) OR
    (type = 'task')
  )
);
```

`work_item_blocked_by`, `work_item_claims`, `work_item_evidence`: unchanged from 001 (see `specs/001-durable-work-ledger/data-model.md`).

**Migration note**: SQLite cannot add or alter a `CHECK` constraint on an existing table. Reaching this schema from a version-1 database requires the table-rebuild sequence described in `research.md`'s "Decision: schema migration from version 1 to version 2" — `ADD COLUMN` for `type`/`parent_id`/`description` (all nullable, permitted by `ALTER TABLE ADD COLUMN`), backfill `type='task'`, then a full rebuild (`CREATE work_items_new` with the schema above, `INSERT ... SELECT`, drop, rename) to install the two new `CHECK` constraints and `type`'s `NOT NULL`, all inside one transaction.

## Work Item (`work_items`) — new and changed columns only

| Column | Type | Required (active) | Required (archived) | Notes |
|---|---|---|---|---|
| `type` | TEXT, `CHECK` enum | yes | yes | **New.** `task` \| `milestone`. Assigned at creation; the model provides no operation to change it — immutability is enforced by omission (no `set_type`/`update_type` function exists), not by a trigger, consistent with FR-018's ban on trigger-based transition validation. |
| `parent_id` | TEXT, `REFERENCES work_items(id)` | no (tasks); always `NULL` (milestones) | preserved, never cleared | **New.** A task's owning milestone. Enforced by the third `CHECK` above (`type='milestone'` forces `parent_id IS NULL`) plus application-level validation at creation time (FR-003: the named row must exist and have `type='milestone'` — a plain FK constraint alone cannot express "must be a milestone," only "must exist"). **Survives archival of the referenced milestone** (see "Archival" below) — this is a deliberate divergence from `title`/`source_kind`/etc., which are cleared. |
| `description` | TEXT | no | cleared to `NULL` | **New.** Optional longer-form text alongside `title`. Same lifecycle as `title` — required-while-active is not imposed (unlike `title`, which 001 already requires); this feature does not change `title`'s existing requiredness. |
| `status` | TEXT | yes | yes | **Changed**: validated by the compound `(type, status)` `CHECK` above instead of 001's flat enum. Values unchanged for `type='task'`. New values `review`/`accepted` for `type='milestone'`, replacing `done` in that vocabulary (a milestone is never `done`; it is `accepted`). |

Every other column (`id`, `superseded_by`, `source_kind`, `source_locator`, `source_promoted_by`, `created_at`, `updated_at`, `archived_at`) is unchanged from `specs/001-durable-work-ledger/data-model.md` and applies identically to both types.

**New invariants**:
- A `milestone` row's `parent_id` is always `NULL` — enforced by `CHECK`, not application discipline alone (same technique 001 already uses for `status`/`superseded_by` pairing).
- A `task` row's `parent_id`, when non-`NULL`, names a row that exists, has `type = 'milestone'`, and has `status = 'open'`, all at the moment of creation — enforced by the creation function's own validation (a plain `REFERENCES` FK cannot express the type/status restriction), inside the same atomic create operation 001 already uses for `blocked_by` (all-or-nothing: creation fails entirely if `parent_id` is invalid, no partial row). The `status = 'open'` requirement (FR-003a) — membership is frozen once a milestone leaves `open` — is what makes the parent's status check load-bearing rather than incidental: unlike `type`, a milestone's `status` is mutable, so this check runs *inside* the same `BEGIN IMMEDIATE` transaction as the `INSERT`, not merely before it, closing the same class of check-then-act race FR-010 already closes for `mark_in_review`.
- `parent_id`, once validly set, is never revalidated against the parent's *current* type or status by any operation other than creation itself — exactly mirroring how `blocked_by` edges are "a declared, historical set" (001 `data-model.md`) rather than continuously re-checked. A parent later archived remains resolvable (see below); nothing re-derives or prunes the child's `parent_id`, and a milestone's later transition away from `open` never retroactively invalidates a task that was already validly attached to it.

## Dependency resolution — generalized to be type-aware

001's single-table lookup (`data-model.md`, "Dependency resolution") is unchanged in mechanism; "resolved" now depends on the resolved row's `type`:

```sql
SELECT type, status, superseded_by FROM work_items WHERE id = :blocked_on_id;
```

- `type = 'task'` and `status IN ('done', 'superseded')` → resolved (unchanged from 001).
- `type = 'milestone'` and `status IN ('accepted', 'superseded')` → resolved (new).
- Any other status for either type → still blocking.
- No row returned → Dangling, same as 001, still conservatively treated as still-blocking.

The **Blocked** query (001 `data-model.md`, "Derived facts") gains the same type-aware `WHEN` in its `JOIN` condition; no other change to its shape. The **Available to start** query gains that same type-aware `WHEN`, plus one additional predicate: `AND type = 'task'` (FR-017a) — a milestone is a human acceptance unit, not an executable/startable unit of work (see "Milestone" below and `generate_projection()`'s own, analogous `type = 'task'` filter, FR-017), so an `open`, unclaimed, unblocked milestone must never be reported as available to start.

## Milestone-specific derived facts

### Qualifying mechanical evidence (of a `done` task)

```sql
SELECT EXISTS (SELECT 1 FROM work_item_evidence WHERE work_item_id = :task_id);
```

Computed only for tasks; a task's own `done`-ness (`status = 'done'`) is a separate, already-existing fact — this predicate answers "does it also carry evidence," used only by review-readiness below.

### Review readiness (of a `milestone`)

```sql
SELECT
  NOT EXISTS (  -- milestone itself not blocked
    SELECT 1 FROM work_item_blocked_by e
    JOIN work_items dep ON dep.id = e.blocked_on_id
    WHERE e.work_item_id = :milestone_id
      AND NOT (
        (dep.type = 'task' AND dep.status IN ('done', 'superseded')) OR
        (dep.type = 'milestone' AND dep.status IN ('accepted', 'superseded'))
      )
  )
  AND EXISTS (  -- at least one child
    SELECT 1 FROM work_items c WHERE c.parent_id = :milestone_id
  )
  AND NOT EXISTS (  -- no child fails the resolved-or-evidenced-done bar
    SELECT 1 FROM work_items c
    WHERE c.parent_id = :milestone_id
      AND NOT (
        c.status = 'superseded'
        OR (c.status = 'done' AND EXISTS (
              SELECT 1 FROM work_item_evidence ev WHERE ev.work_item_id = c.id
            ))
      )
  );
```

Never stored — computed fresh on every call, mirroring 001's "Available to start" precedent exactly (`data-model.md`, "Derived facts": "computed on demand by query, never stored").

## Milestone lifecycle transitions

All three follow 001's existing guarded-conditional-`UPDATE` pattern (`mark_done`/`mark_superseded`) — a single `UPDATE ... WHERE id = :id AND <precondition>` whose affected-row-count is the return value, so concurrent attempts resolve to exactly one success with no separate locking primitive:

- **Enter review** (`open` → `review`): `UPDATE work_items SET status = 'review', updated_at = :now WHERE id = :id AND type = 'milestone' AND status = 'open' AND <review-readiness condition, inline>` — per FR-010, the review-readiness condition above is embedded **directly in this same statement's `WHERE` clause**, not checked separately beforehand. An implementation that instead checked readiness with one query and then issued this `UPDATE` as a second, separate statement would leave a race window between the two — a child task's status could change in between, letting a caller transition a milestone that is no longer actually ready at the moment the `UPDATE` commits. Embedding the condition inline closes that window the same way 001's `claim()` closes its own: one atomic statement's row-count is the sole arbitration mechanism, never a check-then-act pair.
- **Decline review** (`review` → `open`): `UPDATE work_items SET status = 'open', updated_at = :now WHERE id = :id AND type = 'milestone' AND status = 'review'`. Touches no child row.
- **Accept** (`review` → `accepted`): `UPDATE work_items SET status = 'accepted', updated_at = :now WHERE id = :id AND type = 'milestone' AND status = 'review'`.

No trigger, no transition-graph table — the `WHERE`-clause precondition on each statement is the entire enforcement mechanism, identical in kind to 001's existing `mark_done`/`mark_superseded`.

## Archival — milestone precondition and `parent_id` survival

001's archival transaction (`data-model.md`, "Archival") is extended with one precondition, evaluated before the transaction begins, and one addition to what a milestone's thinned row preserves:

The unresolved-child precondition (milestones only) is embedded directly in
the guarded `UPDATE`'s own `WHERE` clause, inside the same `BEGIN IMMEDIATE`
transaction as the mutation itself — mirroring the "Enter review" transition's
own inline `<review-readiness condition>` above (FR-010), not evaluated by a
separate statement beforehand. A pre-transaction check-then-act pair would
leave a race window in which a concurrent writer could insert a new open
child, or reopen/re-review a resolved one, between the check and the
mutation — this closes that window the same way `mark_in_review` closes its
own:

```sql
BEGIN IMMEDIATE;
UPDATE work_items
  SET title = NULL, description = NULL, source_kind = NULL, source_locator = NULL,
      source_promoted_by = NULL, created_at = NULL,
      archived_at = :now, updated_at = :now
  WHERE id = :id AND status IN ('done', 'accepted', 'superseded')
    AND archived_at IS NULL
    AND NOT EXISTS (
      SELECT 1 FROM work_items c
      WHERE c.parent_id = :id
        AND c.status NOT IN ('done', 'accepted', 'superseded')
    );
-- If the UPDATE matches no row (nonexistent id, not yet terminal, already
-- archived, or — for a milestone — an unresolved child at the moment this
-- statement runs), archive_work_item returns False and the DELETEs below
-- are skipped entirely.
DELETE FROM work_item_evidence WHERE work_item_id = :id;
DELETE FROM work_item_blocked_by WHERE work_item_id = :id;
DELETE FROM work_item_claims WHERE work_item_id = :id;
COMMIT;
```

**What survives archival forever, extended**: `id`, `type`, `status`, `superseded_by`, `archived_at` — `type` is added to 001's existing surviving set specifically so a child's `parent_id` reference, once resolved, can still report *what kind* of thing it was attributed to; `status` already survived and now additionally carries a milestone's terminal value (`accepted`/`superseded`) exactly as it already carried a task's. **`parent_id` on a *child* row is never touched by its *parent's* archival** — the transaction above only ever mutates the identified item's own row (`WHERE id = :id`), so a task's `parent_id` column is untouched regardless of whether the milestone it names is later archived; only the *milestone's own* row is thinned. Resolving a task's `parent_id` after its milestone is archived is therefore the same single-row lookup 001's `blocked_by` resolution already uses, now also reading the survived `type` column when useful for display.

## Coordinator projection — type filtering only

`ProjectedWorkItem`'s shape (`id`, `title`, `terminal`, `eligible`) is unchanged. `generate_projection()`'s query gains one predicate:

```sql
SELECT id, title,
       (status IN ('done','superseded')) AS terminal,
       ... -- unchanged eligibility computation, now reading the type-aware
           -- blocking resolution above
FROM work_items
WHERE archived_at IS NULL
  AND type = 'task';
```

No milestone row is ever selected by this query, regardless of its `status`, claim, or blocking state — satisfying spec.md FR-017 by construction (a `WHERE` predicate, not a post-filter that could be bypassed by a caller reading the table directly).
