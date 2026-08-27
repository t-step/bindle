# Phase 0 Research: Milestone and Task Work Items

This feature had no open `NEEDS CLARIFICATION` markers in plan.md's Technical Context — every technology/storage/testing choice is inherited unchanged from `specs/001-durable-work-ledger/`. The research below instead resolves the *design* questions spec.md's Assumptions flagged as deliberate deviations from the user's original illustrative sketch, plus the mechanical questions a schema evolution (rather than a fresh schema) uniquely raises.

## Decision: task status vocabulary — no `in_progress`

**Decision**: Tasks keep exactly 001's existing status vocabulary (`open`, `done`, `superseded`). No `in_progress` value is added.

**Rationale**: An independent lifecycle critique performed before spec.md was written found that a task status meaning "someone is actively working this" is indistinguishable in practice from 001's existing Claim fact — an item is already either open-and-unclaimed or open-and-claimed (`data-model.md` "Claims" section, 001). 001's own FR-004 requires coordination facts to stay orthogonal (status, blocking, claim, evidence as independent facts) and FR-005 explicitly caps the status vocabulary at exactly what's needed to distinguish not-yet-finished / finished / withdrawn — "MUST NOT require a richer status vocabulary... to represent claiming... or partial progress." Adding `in_progress` would either (a) duplicate the Claim fact under a new name, directly violating this, or (b) represent "partial progress," which the same FR also explicitly excludes.

**Alternatives considered**:
- Add `in_progress` and treat it as informational-only, ignored by every derived computation. Rejected: a status value nothing reads or depends on is dead weight that invites drift (an agent might set it inconsistently with claim state), and the whole point of FR-004's orthogonality is to prevent exactly this kind of unenforceable parallel fact.
- Derive an "in progress" *view* (open + claimed) without a stored value, for display purposes only. This is not rejected — it remains available to any future caller as a plain join over existing `status`/`work_item_claims`, requiring no schema change; this feature does not need to name or expose it explicitly since nothing in spec.md's user stories asks for it.

## Decision: milestone status vocabulary — `open`, `review`, `accepted`, `superseded`

**Decision**: Milestones use `open` → `review` → `accepted`, plus `superseded`. No `planned`/`active` split.

**Rationale**: The same orthogonality argument used above for tasks applies symmetrically. "Planned" vs. "active" would only be distinguishable by whether the milestone's children exist yet or have been started/claimed — both already fully reconstructable by querying the children themselves (this feature's own review-readiness computation, see below). The two states that are *not* reconstructable from anything else — because they represent an explicit human/agent act, not a fact about children — are `review` (someone decided this is ready for human judgment) and `accepted` (a human decided yes). `open` covers "created, not yet in review," directly mirroring how a task's `open` covers "created, not yet done" without needing a separate "started" state. Reusing the word `open` (rather than inventing `planned`) for both types' pre-terminal-decision state keeps the vocabulary minimal and avoids inventing two words for the same underlying idea (not yet at a resolved/terminal outcome).

**Alternatives considered**:
- The user's original illustrative sketch (`planned -> active -> review -> accepted`). Not adopted, flagged explicitly in spec.md's Assumptions for the requester's sign-off, since it changes proposed vocabulary rather than merely reinterpreting it — but the sketch itself explicitly invited this reconciliation ("Do not overcommit to those exact state names until you have grounded on the existing Bindle lifecycle").
- A milestone-specific `active` value gated on "at least one child claimed or done." Rejected as a stored fact for the same reason task `in_progress` was rejected — it's a derivable view over children, not new information.

## Decision: compound `(type, status)` validation, not one flat enum

**Decision**: `work_items.status`'s `CHECK` constraint becomes conditional on `type`: `CHECK ((type='task' AND status IN ('open','done','superseded')) OR (type='milestone' AND status IN ('open','review','accepted','superseded')))`.

**Rationale**: A single flat enum unioning both vocabularies (e.g. allowing a `task` row to hold `status='accepted'`) would let a task and a milestone be validated against the wrong vocabulary with no constraint catching it — status is functionally dependent on type, and 001 already uses exactly this "don't trust application discipline alone" reasoning for its existing `status`/`superseded_by` pairing `CHECK` (`data-model.md`, "Invariants": "enforced by the table's own `CHECK` constraint — not by application discipline alone"). This feature extends that same technique one level further; it introduces no new *mechanism*, only a more specific condition within the same kind of constraint 001 already relies on.

**Alternatives considered**:
- Two separate `status` columns (`task_status`, `milestone_status`), one always `NULL`. Rejected: reintroduces exactly the "nullable-depending-on-a-flag" shape the normalization critique flagged as a smell, for no benefit over a single column with a smarter `CHECK`.
- Application-level validation only (no `CHECK`). Rejected: contradicts 001's own established precedent of using `CHECK` for write-time invariants wherever the invariant is expressible as one, rather than as a defense-in-depth reconciliation finding.

## Decision: `parent_id` — plain nullable foreign key, not an edge table

**Decision**: `work_items.parent_id TEXT REFERENCES work_items(id)`, nullable.

**Rationale**: An independent normalization critique found that `work_item_blocked_by` is a separate table specifically because blocking is a genuinely many-to-many, arbitrary-graph relationship (FR-006 requires reasoning over a *declared set* of edges per item). Parent attribution as specified is single-valued per task — one task has at most one milestone — which is exactly the cardinality a plain foreign-key column expresses correctly; wrapping it in a `work_item_parents(work_item_id PK, milestone_id)` table would add a join for a fact already fully expressed by one column on the row itself, and would not gain anything an edge table earns its keep by providing (multiplicity, or an audit trail of *changed* parents — this feature does not need either).

**Alternatives considered**:
- A `work_item_parents` edge table, mirroring `work_item_blocked_by`'s shape for consistency. Rejected on the cardinality argument above; consistency-for-its-own-sake is not a reason absent a structural need.
- Encoding milestone attribution as a same-shape `work_item_dependencies`-style edge with a distinguishing `kind` column (`'parent'` vs `'blocks'`) in one shared table. Rejected: conflates two semantically different relationships (a declared blocking constraint vs. a structural grouping) into one table for no normalization benefit, and would require every blocking query to filter by `kind` to avoid accidentally treating a parent edge as a blocking edge or vice versa.

**Membership freeze (FR-003a)**: `create_work_item`'s own validation of a `parent_id` checks not only that the named row exists and is `type = 'milestone'` (FR-003) but that it is currently `status = 'open'` — attaching a task to a milestone that is `review`, `accepted`, or `superseded` is rejected outright. Without this, a milestone's reviewed child set could change after a human already accepted it (or while it is mid-review), undermining the entire point of `accept_milestone()` being an explicit judgment over a specific, fixed set of child work. This still permits the corrective-work flow FR-011 exists for: `review` → `decline_review` → `open` → attach a corrective task → `review` again — decline always returns the milestone to `open` first. Because a milestone's `status` (unlike its `type`) is mutable, this check is embedded in the same `BEGIN IMMEDIATE` transaction as the `INSERT` itself, not performed as a separate pre-check — see "Decision: milestone archival precondition" below for the identical reasoning applied to a sibling operation, and `mark_in_review`'s own inline-`WHERE`-clause precedent (FR-010) for the origin of this pattern in 001/002.

## Decision: `work_item_blocked_by` is not renamed

**Decision**: The existing table name, columns (`work_item_id`, `blocked_on_id`), and constraints (self-cycle `CHECK`, FK enforcement) are unchanged. Requirements text in this feature's spec.md refers to it as "the dependency/blocking mechanism," not `work_item_dependencies`.

**Rationale**: The user's own request treated the rename as conditional ("if the rename is adopted"). A normalization critique found the proposed `work_item_dependencies(work_item_id, depends_on_work_item_id)` to be a column-for-column relabeling with identical semantics and identical constraints — no behavioral or normal-form gain. Renaming a table that 1108 lines of implementation and 1567 lines of already-passing tests reference throughout, for a cosmetic naming preference, contradicts `AGENTS.md`'s explicit tooling precedence ("Inherit first. Extend second. Replace deliberately.") — this table is neither broken, unsafe, contradictory, nor abandoned.

**Alternatives considered**: Renaming with a compatibility view/alias. Rejected: 001 has no external consumers of the raw table name yet (it's an internal implementation detail behind `WorkLedger`'s API), so a compatibility shim would exist purely to serve a rename with no consumer requiring it — pure overhead.

## Decision: "qualifying mechanical evidence" — defined predicate

**Decision**: A `done` task has qualifying mechanical evidence iff at least one row exists in `work_item_evidence` for it (any `kind`). Expressed as `EXISTS (SELECT 1 FROM work_item_evidence WHERE work_item_id = :id)`.

**Rationale**: The user's request asked for "a task being done should mean something narrow and mechanically defensible... completed and its required mechanical evidence is satisfied," but did not ask for a configurable, per-item or per-type notion of *which* evidence kinds are required — introducing that would require new schema (an evidence-requirements concept per item or per source) with no concrete current need, which spec.md's Assumptions and the normalization critique both counsel against ("avoid speculative entities"). The simplest predicate that is (a) purely derived, (b) uses only the existing `work_item_evidence` table, and (c) gives milestones something non-vacuous to depend on is "at least one evidence pointer exists." This mirrors 001's own precedent of using existence-of-a-row as the signal (e.g., `is_claimed`).

**Alternatives considered**:
- Require a specific evidence `kind` (e.g., only `commit` or `pull_request` count, not `other`). Rejected: nothing in spec.md or the FRs distinguishes evidence kinds by mechanical weight, and 001's own evidence model treats all four kinds as equally valid pointers; inventing a stronger bar than the source spec asks for is scope creep.
- Gate `mark_done()` itself on this predicate (refuse to mark done without evidence). Rejected: 001's FR-008 explicitly keeps evidence optional at the point of marking done; changing that would revise a settled 001 decision this feature is not chartered to reopen. The predicate is read-only and additive, consumed only by the new review-readiness computation.

## Decision: "review readiness" — defined predicate, and the empty-milestone rule

**Decision**: A milestone is review-ready iff: not blocked (existing blocking computation, generalized per FR-006 below); has at least one child task; and every child task is either `superseded` or (`done` AND has qualifying mechanical evidence).

**Rationale**: Mirrors 001's existing "Available to start" derivation almost exactly (`data-model.md`, "Derived facts") — a boolean computed fresh by one query, never stored. The empty-milestone rule (zero children ⇒ never review-ready) exists because "required child work complete" is only a meaningful claim when there is required child work; treating an empty set as vacuously satisfying it would let a milestone with nothing under it enter human review, which defeats the entire premise of a milestone being a *grouping* of completed work.

**Alternatives considered**: Allow an empty milestone to be reviewed and accepted directly (as a way to record a decision with no decomposed sub-work). Rejected: nothing in the user's request or spec.md's user stories describes this use case, and it would blur milestones into a general-purpose decision-log entry, which `docs/DATA-OWNERSHIP.md` already assigns to `docs/DECISIONS.md`, not the ledger (spec.md FR-014).

## Decision: dependency resolution generalized to be type-aware

**Decision**: "Resolved" (for blocking purposes) becomes: task → `done`/`superseded`; milestone → `accepted`/`superseded`. The existing single-table lookup (`data-model.md`, "Dependency resolution") is unchanged in *mechanism* — it now additionally reads `type` from the same row to pick which status values count as resolved.

**Rationale**: 001's existing resolution query already reads the full row (`status`, `superseded_by`); reading `type` from the same row costs nothing extra and requires no new lookup. This is a strict generalization of 001's FR-006/FR-020/FR-021 — every existing task-on-task scenario resolves identically to before, since the task-side rule is unchanged.

**Alternatives considered**: Forbid cross-type blocking edges (a task may only block/be-blocked-by another task; a milestone only by another milestone). Rejected: nothing in spec.md's user stories or the user's request calls for this restriction, and User Story 5's Acceptance Scenario 2 explicitly exercises a task blocked on a milestone as a legitimate case Symphony must never see the milestone-shaped reason for.

## Decision: milestone archival precondition

**Decision**: `archive_work_item` gains a precondition when `type = 'milestone'`: refuse (return `False`, matching 001's existing no-op-on-guard-failure convention) if any child task's status is not in `('done', 'accepted', 'superseded')`. Task archival is otherwise unchanged from 001. This precondition is embedded directly in the guarded archival `UPDATE`'s own `WHERE` clause, inside the same `BEGIN IMMEDIATE` transaction as the mutation — not evaluated by a separate `SELECT` before the transaction opens.

**Rationale**: 001's archival never had a "children" concept — every archivable item was a leaf. A milestone with live children is not safely archivable without inventing a rule for what happens to those children's `parent_id` pointers; refusing outright (rather than cascading, orphaning, or nulling) is the minimal rule that requires no new behavior for children at all — they are simply untouched, and the milestone stays active until they resolve. This mirrors 001's own general posture of guarding operations with a `WHERE`-clause precondition rather than introducing cascading side effects.

A pre-transaction, separate-statement precondition check was the first implementation and is deliberately not the shipped shape: it leaves a check-then-act window between "confirmed no unresolved children" and "archived" in which a concurrent writer could insert a new open child (or reopen/re-review a resolved one), producing an archived milestone with live, unresolved child work underneath it — exactly the class of race FR-010 already closes for `mark_in_review` via its own inline `WHERE`-clause precondition. Embedding the same `NOT EXISTS (...)` condition directly in the archival `UPDATE`'s `WHERE` clause closes this window identically: `BEGIN IMMEDIATE` holds SQLite's write lock for the transaction's duration, so no concurrent writer can insert or mutate a child row between the precondition's evaluation and the `UPDATE` that reads it.

**Alternatives considered**: Cascade-archive resolved children automatically when their milestone archives. Rejected: 001's archival is per-item and explicit by design (`docs/DECISIONS.md`'s "capture requires a reason" discipline applied to *removal* too) — an implicit cascade would archive items without a direct, explicit call naming them, a new kind of implicit side effect this ledger has never had.

## Decision: schema migration from version 1 to version 2

**Decision**: `_SCHEMA_VERSION` becomes `2`. On connecting to an existing version-1 database, run a one-time forward migration inside the same explicit transaction pattern 001 already uses for fresh bootstrap (`_transaction`, per `data-model.md`'s bootstrap-atomicity fix): `ALTER TABLE work_items ADD COLUMN type TEXT`, `ALTER TABLE work_items ADD COLUMN parent_id TEXT REFERENCES work_items(id)`, backfill `UPDATE work_items SET type = 'task' WHERE type IS NULL`, then rebuild the table (SQLite cannot `ALTER` a `CHECK` constraint in place) via the standard SQLite pattern: create `work_items_new` with the full v2 schema (including the compound `CHECK` and `NOT NULL` on `type`), `INSERT INTO work_items_new SELECT ... FROM work_items`, drop the old table, rename the new one, recreate any dependent objects, then set `PRAGMA user_version = 2`. All inside one transaction so a crash mid-migration leaves the database at its original version-1 state, not a partially-migrated one — mirroring the exact bootstrap-atomicity guarantee 001 already built for fresh initialization.

**Rationale**: This is new work 001 did not need (it only ever bootstrapped a fresh schema). Every pre-existing row must become `type = 'task'` with `parent_id = NULL` — the only sensible backfill, since every 001-era work item was, definitionally, an undifferentiated unit of work with no milestone concept to attribute it to; treating pre-existing items as tasks (not milestones) preserves their existing behavior (claimable, done/superseded, projected to Symphony) exactly as before.

**Alternatives considered**:
- Require a manual/out-of-band migration step (a separate CLI command). Rejected: 001's `connect()` already self-heals a fresh database into existence transparently; requiring an operator to run something extra before the ledger works again after an upgrade contradicts that existing zero-ceremony posture and risks a confusing `SchemaVersionError` for every caller until someone remembers to run it.
- Leave `type` nullable and treat `NULL` as an implicit "task" without ever writing the backfill. Rejected: this reintroduces exactly the "meaning inferred from which columns are `NULL`" anti-pattern 001's own `data-model.md` explicitly rejected for `archived_at` ("Distinguishes... without inferring it from which other columns happen to be `NULL`"). An explicit backfill keeps `type` `NOT NULL` and unambiguous for every row, old or new.

## Decision: projection filtering — extend the existing function, no new one

**Decision**: `generate_projection()`'s existing single `SELECT` gains one additional predicate, `type = 'task'`, alongside its existing `archived_at IS NULL` filter. `ProjectedWorkItem`'s fields (`id`, `title`, `terminal`, `eligible`) are unchanged.

**Rationale**: 001's projection is already a single, snapshot-consistent query specifically to avoid a claim landing between two separate reads (`data-model.md`/implementation comments). Adding a `type='task'` predicate to that same query preserves the snapshot-consistency property for free; a separate "list only tasks" pass composed afterward would not. `docs/SYMPHONY.md`'s pinned-fork contract (`contracts/coordinator-projection.md`, 001) already establishes that field-name translation into Symphony's own vocabulary is a future adapter's job, not this projection's — so no field is renamed here.

**Alternatives considered**: A separate `generate_task_projection()` function alongside the existing one. Rejected: 001's own FR-013/FR-014 define exactly one coordinator-facing projection concept; a second, differently-scoped function would fragment that into two things callers must know to choose between, for a filter that's one `WHERE` clause.

## Decision: `list_available_work_items()` also filters to `type = 'task'`

**Decision**: `list_available_work_items()` (001's "Available to start" query) gains the same `AND type = 'task'` predicate `generate_projection()` gains above (FR-017a).

**Rationale**: An initial draft of this feature generalized the "Available to start" query's blocking `JOIN` to be type-aware (per "Dependency resolution" above) but left its `type` scope unchanged, on the theory that it is a generic ledger query no different from `is_blocked`/`is_claimed` and 002 should not narrow an existing 001 caller's contract without a demonstrated need. On review, this was judged wrong: `list_available_work_items()`'s own name and 001's "Available to start" concept both mean *startable, executable work* — exactly what `generate_projection()` (FR-017) already restricts to tasks, for the identical reason (Key Entities → "Milestone": "a human acceptance unit," never itself dispatched or claimed for implementation work). Leaving `list_available_work_items()` unfiltered would let an `open`, unclaimed, unblocked milestone be reported as "available to start" by one public method while `generate_projection()` — built from the same underlying facts — correctly withholds it, a semantic inconsistency between two methods answering closely related questions. No existing caller (001's own test suite, or this feature's) asserts a milestone must appear in this list, so applying the same restriction here breaks nothing already relied upon.

**Alternatives considered**: Leave `list_available_work_items()` unfiltered and instead rename or re-document it as a generic, type-agnostic "open, unclaimed, unblocked" ledger query, distinct from "startable work." Rejected: no concrete caller was found that needs a milestone to appear in this list, so introducing a second, more permissive concept purely to preserve a behavior nothing depends on adds a distinction without a use — the "smallest correct mechanism" here is simply to match `generate_projection()`'s own precedent.
