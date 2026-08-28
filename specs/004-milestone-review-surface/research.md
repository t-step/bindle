# Phase 0 Research: Milestone Review Surface

## Decision: no schema migration, no `_SCHEMA_VERSION` bump

**Chosen**: Neither of this feature's two new `WorkLedger` methods (`list_evidence`, `get_claim`) touches the schema. Both are `SELECT`s over `work_item_evidence`/`work_item_claims`, tables that already carry every column FR-003/FR-004 need (`kind`, `value`, `recorded_at`, `note` on the former; `owner`, `claimed_at`, `worktree_path`, `branch` on the latter — `data-model.md`, "Evidence Pointer"/"Claims" from `specs/001`). No column is added, no table is added, no `CHECK` constraint changes.

**Rationale**: `spec.md` FR-012 requires this explicitly, and the grounding in `spec.md`'s Baseline already established that the write side of both facts (`add_evidence`, `claim`) has existed since 001 — only the *read-individual-rows-back* side was missing. Adding a schema-changing feature to close a read gap would be exactly the kind of invented machinery `AGENTS.md`'s "Inherit first. Extend second. Replace deliberately. Invent last." warns against.

**Alternatives considered**: A denormalized "latest evidence" column on `work_items` for fast review-view rendering — rejected; `work_item_evidence` is already indexed by its own `work_item_id` foreign key and a milestone's review-view query touches at most a few dozen rows, so no read-performance problem exists to justify duplicating state (and duplicated state is exactly what 001's evidence-as-a-separate-append-only-table design was chosen to avoid — `specs/001-durable-work-ledger/data-model.md`, "Evidence Pointer").

## Decision: `list_evidence()` and `get_claim()` shape

**Chosen**: `list_evidence(work_item_id: str) -> list[EvidencePointer]`, ordered by `recorded_at` (insertion order, matching `work_item_evidence`'s own append-only, never-reordered semantics). `get_claim(work_item_id: str) -> ClaimInfo | None`, returning `None` when unclaimed (mirroring `get_work_item()`'s existing `WorkItem | None` shape for "not found") rather than raising.

**Rationale**: Both generalize an existing `EXISTS`-only method (`has_qualifying_evidence`, `is_claimed`) into a full-row read, using the exact same connection-per-call, no-ORM style every other `WorkLedger` method already uses (module docstring: "a handful of narrow methods over plain SQL"). `list_evidence` returns a list (zero or more, an item may carry many pointers) where `get_claim` returns an optional single value (a work item has at most one claim, per `work_item_claims`'s own `PRIMARY KEY (work_item_id)`) — the plural/singular distinction mirrors the underlying table's own cardinality exactly, not an arbitrary API choice.

**Alternatives considered**: Returning raw tuples instead of a new frozen dataclass — rejected for consistency; every other multi-field `WorkLedger` read (`WorkItem`, `ReconciliationFinding`, `ProjectedWorkItem`, `ExternalProjectionRow`) is already a `@dataclasses.dataclass(frozen=True)`, and two more (`EvidencePointer`, `ClaimInfo`) following that exact precedent costs nothing and keeps the module internally consistent.

## Decision: readiness diagnostic is composed from existing reads, not a new combined query

**Chosen**: FR-002's "which condition is unmet" diagnostic is computed by `milestone_review.py`'s `review_milestone()` calling three already-existing (or newly added, per above) reads independently — `is_blocked(milestone_id)`, `list_work_items()` filtered to `parent_id == milestone_id` (children), and `has_qualifying_evidence(child_id)` per child that is `done` — and assembling the three-way diagnostic itself in Python, rather than adding a fourth SQL variant of `is_review_ready()`'s own query that also explains *why*.

**Rationale**: `is_review_ready()`'s existing query (`_review_ready_sql`, `work_ledger.py`) is a single boolean `AND` of the same three conditions FR-002 needs to name individually; decomposing it into three separate calls that `review_milestone()` already needs for other reasons (children need to be listed anyway for FR-001; blocking needs to be checked anyway for FR-005/FR-006) avoids a fourth, near-duplicate SQL statement that could drift from `_review_ready_sql`'s own condition over time. `review_milestone()` still calls `is_review_ready()` itself for the headline yes/no (spec.md FR-002: "MUST NOT introduce a new readiness predicate") — the diagnostic decomposition is presentation-layer composition of already-true facts, not a second readiness computation that could disagree with the first.

**Alternatives considered**: A new `is_review_ready_detail()` method on `WorkLedger` returning a structured reason — rejected as unnecessary surface: nothing about the diagnostic requires a new SQL statement or a new atomic guarantee (unlike `mark_in_review`'s guarded transition, this is a pure read with no race to close), so composing it in the CLI-facing module keeps `work_ledger.py` itself free of yet another milestone-review-specific method, consistent with the Constitution Check's "no coordinator-/reviewer-specific adapter" gate.

## Decision: children enumerated via `list_work_items()` + filter, not a new `list_children()` method

**Chosen**: `review_milestone()` calls the existing `list_work_items()` (no filter parameters today) and filters to `parent_id == milestone_id` in Python.

**Rationale**: At this repository's stated scale (`plan.md`'s Technical Context: "a handful-to-dozens of work items"), an unindexed client-side filter over the full work-item list costs nothing measurable, and avoids adding a new parameterized query method to `work_ledger.py` for a filter `mark_in_review`'s own inline SQL already expresses ad hoc (`work_ledger.py`, the `_review_ready_sql` children subquery) without needing a public method of its own.

**Alternatives considered**: A new `list_children(parent_id)` method — deferred, not rejected outright; if a future feature needs the same filter elsewhere, it can be added then (`AGENTS.md`: "Extend existing tooling before introducing a parallel mechanism" — extend when a second real caller appears, not preemptively for one).

## Decision: rationale locator recorded via existing `add_evidence(kind='other', ...)`, sequenced after the transition

**Chosen**: `accept`/`decline` in `milestone_review.py` call `WorkLedger.accept_milestone()`/`decline_review()` first; only if that call returns `True` do they optionally call `add_evidence(milestone_id, kind='other', value=<locator>, note=<note>)`. Two separate calls, not one transaction.

**Rationale**: `add_evidence()` itself is a single, already-atomic `INSERT` with no transactional coupling to any status transition anywhere else in `work_ledger.py` (`override_release_claim()` is the one existing precedent that *does* couple a claim-delete and an evidence-insert in one transaction — but that method owns both statements itself; here, the transition method (`accept_milestone`/`decline_review`) is a separate, already-published, already-tested primitive this feature must not modify). Sequencing the two calls (transition, then evidence, gated on the transition's own boolean result) satisfies FR-010 ("no evidence pointer describing a decision that did not occur") without requiring either existing method to grow a new parameter or a shared transaction — a genuine two-statement sequence is acceptable here specifically because the two facts (the transition succeeded; a locator exists) are independently, individually true or false, and 001's own evidence model already treats every pointer as an independent, individually-added fact (never a required, all-or-nothing bundle with the status change it documents).

**Alternatives considered**: Adding an optional `note`/`evidence` parameter directly to `accept_milestone()`/`decline_review()` — rejected: this would modify `specs/002`'s own settled, tested public methods for a concern that method never had (spec.md FR-013's own boundary: "MUST NOT modify... `specs/001` or `specs/002`'s schema" extends in spirit to not modifying their already-accepted method signatures either); wrapping instead of extending keeps 002's contract exactly as published.

## Decision: `bindle milestone` as a new top-level command group, not `bindle work milestone`

**Chosen**: A new top-level `milestone` subparser in `cli.py`'s `build_parser()`, parallel to the existing `repo`/`skills`/`work` groups — not a nested `bindle work milestone ...` under the existing `work` group.

**Rationale**: `spec.md`'s Assumptions section states this explicitly as part of the design, not an implementation detail: the separation is what makes User Story 5 ("neither surface can perform the other's mutation") true by construction — a human reviewer's command vocabulary and Symphony's task-write vocabulary never share a parent namespace, mirroring `specs/003-symphony-task-integration/contracts/task-write-surface.md`'s own reasoning for rejecting milestones on the task-facing surface rather than silently accepting them. This also avoids overloading `bindle work`'s existing, already-documented meaning ("the smallest supported external write surface" for Symphony, D039) with a second, unrelated audience.

**Alternatives considered**: Nesting under `work` with an argument-level guard only — rejected: nothing structurally prevents future confusion between `bindle work <task-verb>` and `bindle work milestone <verb>` sharing a prefix, and the existing `contracts/task-write-surface.md` already frames `work` as categorically task-only; adding a milestone-shaped subcommand under it would blur that existing, published boundary for no benefit.

## Decision: `bindle milestone list` reuses `review_milestone()`'s readiness computation per row, no batch query

**Chosen**: `bindle milestone list` calls `list_work_items()`, filters to `type == 'milestone'`, and calls `is_review_ready()` once per milestone found.

**Rationale**: Same scale reasoning as "children enumerated via `list_work_items()` + filter" above — this repository's scope (`docs/SCOPE.md`'s own milestones are unrelated roadmap labels, not a signal about ledger-milestone volume, but 001-003's own stated scale assumption of "one repository's own work" applies identically here) does not justify a batched, single-SQL-statement readiness-for-all-milestones query; N individual calls to an already-correct, already-tested method is simpler and cannot disagree with `bindle milestone review <id>`'s own per-milestone answer, since both call the identical underlying method.

**Alternatives considered**: A dedicated `list_review_ready_milestones()` batch query — deferred for the same "extend when a second real caller appears" reasoning as `list_children()` above; nothing today needs the query performance a batched version would buy.
