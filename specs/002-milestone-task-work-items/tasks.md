---

description: "Task list for Milestone and Task Work Items"
---

# Tasks: Milestone and Task Work Items

**Input**: Design documents from `specs/002-milestone-task-work-items/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/coordinator-projection-v2.md, quickstart.md

**Tests**: Included — spec.md's own Success Criteria (SC-001–SC-008) are testable claims, and the user's request explicitly listed ten required test coverage areas.

**Organization**: This feature extends exactly two existing files (`src/bindle/work_ledger.py`, `tests/test_work_ledger.py`) — no new files are created. Every task therefore targets one of those two files; `[P]` is reserved for tasks that touch genuinely independent functions/regions with no shared state, not for file-level isolation (there is only one file of each kind). See tasks.md's own "Composition note" at the bottom for how this feature's task-composition analysis (a separate, required step) groups these into actual delivery slices.

## Phase 1: Setup

No new project structure, dependency, or tooling is introduced — this feature extends an existing module in place (plan.md, "Structure Decision"). There is no Setup phase distinct from Phase 2.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The schema and dataclass changes every user story depends on. No user story task can be implemented before these land.

- [ ] T001 Bump `_SCHEMA_VERSION` to `2` and implement the v1→v2 migration (`ALTER TABLE work_items ADD COLUMN type`, `ADD COLUMN parent_id`, `ADD COLUMN description`; backfill `type='task'` for every existing row; rebuild the table via `CREATE work_items_new` / `INSERT ... SELECT` / drop / rename to install the two new `CHECK` constraints and `type NOT NULL`, per `research.md`'s "Decision: schema migration from version 1 to version 2" and `data-model.md`'s schema overview) inside the existing `_transaction` pattern, in `src/bindle/work_ledger.py`.
- [ ] T002 Extend the `WorkItem` dataclass with `type`, `parent_id`, `description` fields and update every row-mapping call site (`get_work_item`, `list_work_items`) to read the three new columns, in `src/bindle/work_ledger.py`. Depends on: T001.
- [ ] T003 Extend `create_work_item()` with `type="task"` (default, backward-compatible), `parent_id=None`, `description=None` parameters; add FR-002/FR-003/FR-003a validation (a `parent_id` must name an existing row of `type='milestone'` whose `status = 'open'`; a `milestone` may never be given a `parent_id`) inside the same atomic create transaction 001 already uses for `blocked_by` (all-or-nothing — no partial row on validation failure). The parent existence/type/status check MUST run inside that same `BEGIN IMMEDIATE` transaction as the `INSERT`, not as a separate pre-check before it — a milestone's `status`, unlike its `type`, is mutable, so a pre-check would leave a race window in which a concurrent lifecycle transition invalidates the parent's `open`-ness before the row is written, in `src/bindle/work_ledger.py`. Depends on: T002.
- [ ] T004 Generalize dependency resolution (`is_blocked`, `list_available_work_items`, and any shared blocking-resolution SQL) to the type-aware "resolved" rule from `data-model.md` (`task` → `done`/`superseded`; `milestone` → `accepted`/`superseded`); additionally restrict `list_available_work_items()` to `type = 'task'` rows only (FR-017a), mirroring `generate_projection()`'s own `type = 'task'` filter — a milestone is never "available to start," in `src/bindle/work_ledger.py`. Depends on: T001.
- [ ] T005 `TestSchemaMigration`: a fixture-constructed version-1 database opens cleanly under the new code, every pre-existing row is backfilled to `type='task'` with `parent_id IS NULL`, the compound `(type, status)` and milestone-`parent_id` `CHECK` constraints are enforced going forward, and a simulated crash mid-migration leaves the database at its original, fully-functional version-1 state (never a partially-migrated one), in `tests/test_work_ledger.py`. Depends on: T001.
- [ ] T006 `TestWorkItemTypeAndParent`: `type` has no mutator anywhere in the public API (immutability by omission); creating a task with a `parent_id` naming a nonexistent row, a row of `type='task'`, or a non-`open` milestone (`review`/`accepted`/`superseded`) is rejected atomically with no row written; creating a milestone with a `parent_id` is rejected by the schema's own `CHECK`; type-aware blocking resolution is correct for task-on-task, task-on-milestone, milestone-on-task, and milestone-on-milestone dependency edges; a concurrent milestone lifecycle transition racing a concurrent task-attach attempt cannot produce an invalid membership state, in `tests/test_work_ledger.py`. Depends on: T002, T003, T004.

**Checkpoint**: Foundation ready — every user story below can now be implemented.

---

## Phase 3: User Story 1 - Group tasks under a human-acceptance unit (Priority: P1) 🎯 MVP

**Goal**: A milestone and its child tasks can be created, durably attributed, and read back exactly like any 001 work item.

**Independent Test**: Per spec.md's own Independent Test for this story — create a milestone and two attributed tasks, then confirm from a fresh `WorkLedger` handle that the attribution and every 001-defined behavior (status, blocking, claims, evidence) is intact.

### Implementation for User Story 1

Fully delivered by Phase 2 (T002, T003) — `create_work_item`'s new parameters and validation *are* this story's entire implementation surface. No additional production code is needed.

### Tests for User Story 1

- [ ] T007 [US1] Integration test exercising spec.md's own Independent Test verbatim: create one milestone and two child tasks, close and reopen a second `WorkLedger` handle against the same database, and confirm both tasks' `parent_id` and the milestone's `parent_id is None` read back identically; confirm every existing 001 acceptance scenario (claim, evidence, blocking, list) continues to pass unmodified when exercised against a `type='milestone'` row, not only a `type='task'` row, in `tests/test_work_ledger.py`. Depends on: T003.

**Checkpoint**: User Story 1 is independently functional and testable.

---

## Phase 4: User Story 2 - A task reaches "done" without triggering human review (Priority: P1)

**Goal**: A read-only, mechanically checkable predicate exists for "does this done task carry qualifying evidence," with zero change to `mark_done`'s existing behavior.

**Independent Test**: Mark a task done with and without recorded evidence; confirm the predicate answers correctly in both cases and that nothing about reaching `done` touches any review-shaped fact.

### Implementation for User Story 2

- [ ] T008 [US2] Implement `has_qualifying_evidence(work_item_id) -> bool` (`EXISTS (SELECT 1 FROM work_item_evidence WHERE work_item_id = :id)`, per `data-model.md`), in `src/bindle/work_ledger.py`.

### Tests for User Story 2

- [ ] T009 [US2] `has_qualifying_evidence` returns `False` for a done task with no recorded evidence and `True` once any evidence pointer (any of the four existing kinds) is recorded; confirm `mark_done()`'s signature and behavior are byte-for-byte unchanged from 001 (evidence remains optional to record); confirm no review-state read or write occurs anywhere in the `mark_done` code path, in `tests/test_work_ledger.py`. Depends on: T008.

**Checkpoint**: User Stories 1 and 2 are both independently functional.

---

## Phase 5: User Story 3 - A milestone becomes ready for human review, and a human claims it (Priority: P2)

**Goal**: Review-readiness is a correct, purely derived boolean; moving a milestone into `review` is a guarded, single-winner transition; claiming a milestone reuses the existing claim mechanism unmodified.

**Independent Test**: Per spec.md — a milestone with three children shows readiness `False` while any child is unresolved or unevidenced, `True` once all are resolved-and-evidenced and the milestone is unblocked; moving it into `review` and claiming it behaves exactly like an ordinary task claim.

### Implementation for User Story 3

- [ ] T010 [US3] Implement `is_review_ready(milestone_id) -> bool` per `data-model.md`'s three-part query (milestone itself unblocked; at least one child exists; every child is `superseded` or `done`-with-qualifying-evidence), in `src/bindle/work_ledger.py`. Depends on: T004, T008.
- [ ] T011 [US3] Implement `mark_in_review(milestone_id) -> bool` — a guarded conditional `UPDATE`, with the review-readiness condition (T010's own logic, factored into a shared `_review_ready_sql` helper) embedded **directly in the same statement's `WHERE` clause** per FR-010, not checked separately beforehand (see `data-model.md`'s "Milestone lifecycle transitions" for why a two-step check-then-act would leave a race window), in `src/bindle/work_ledger.py`. Depends on: T002, T004, T008, T010 — shares T010's readiness predicate, corrected from an earlier Foundational-only dependency once the atomic-embedding requirement (FR-010) was implemented.

### Tests for User Story 3

- [ ] T012 [US3] `TestMilestoneReviewReadiness`: parametrized over 1, 2, and 5+ children in every combination of resolved/unresolved and evidenced/unevidenced states (SC-002); a milestone with zero children is never review-ready; `mark_in_review` succeeds only when both `status='open'` and readiness is true, and a simulated concurrent race for the same transition resolves to exactly one success (SC-003); `claim()`/`release_claim()`/`override_release_claim()` work against a milestone row with no code changes needed, verified by exercising 001's existing claim test scenarios against a milestone instead of a task, in `tests/test_work_ledger.py`. Depends on: T010, T011.

**Checkpoint**: User Stories 1–3 are all independently functional.

---

## Phase 6: User Story 4 - Review requests changes without rewriting completed task history (Priority: P2)

**Goal**: A milestone can be declined back to `open` or accepted from `review`, with zero mutation of any child task, and with no rationale-storage capability added to the ledger.

**Independent Test**: Decline a milestone from `review`, add a new corrective task, and confirm every previously-`done` sibling's full record is unchanged.

### Implementation for User Story 4

- [ ] T013 [US4] Implement `decline_review(milestone_id) -> bool` (`review` → `open`, guarded `UPDATE`) and `accept_milestone(milestone_id) -> bool` (`review` → `accepted`, guarded `UPDATE`, following 001's existing `superseded_by`-pairing convention where applicable), in `src/bindle/work_ledger.py`. Depends on: T011.

### Tests for User Story 4

- [ ] T014 [US4] `decline_review` leaves every child task's full record (`WorkItem` equality) byte-identical before and after (SC-004); a new task created with `parent_id` naming the declined milestone is accepted normally and `is_review_ready` recomputes to include it; `accept_milestone` fails when called from any status other than `review`; confirm no function anywhere in the public API accepts or stores review rationale text (FR-014 is satisfied by omission, not by a validated-empty field), in `tests/test_work_ledger.py`. Depends on: T013.

**Checkpoint**: User Stories 1–4 are all independently functional.

---

## Phase 7: User Story 5 - Symphony sees tasks, never milestones (Priority: P3)

**Goal**: The coordinator-facing projection never includes a milestone row under any state; milestone archival is refused while children are unresolved, and a resolved milestone's archival preserves child `parent_id` resolvability.

**Independent Test**: Generate a projection over a mixed ledger and confirm no milestone row appears in any state; attempt to archive a milestone with a live child and confirm refusal; archive once resolved and confirm children's `parent_id` still resolves.

### Implementation for User Story 5

- [ ] T015 [US5] Add a `type = 'task'` predicate to `generate_projection()`'s existing single query, alongside its existing `archived_at IS NULL` filter — no change to `ProjectedWorkItem`'s field shape, per `contracts/coordinator-projection-v2.md`, in `src/bindle/work_ledger.py`. Depends on: T004.
- [ ] T016 [US5] Extend `archive_work_item()` with the milestone precondition from `data-model.md` ("Archival"): refuse (return `False`) when `type='milestone'` and any child (`parent_id` naming it) has a status outside `('done', 'accepted', 'superseded')`. This precondition MUST be embedded directly in the guarded archival `UPDATE`'s own `WHERE` clause, inside the same `BEGIN IMMEDIATE` transaction as the mutation — not evaluated by a separate `SELECT` before the transaction opens, per FR-015's atomicity requirement (mirroring `mark_in_review`'s own FR-010 inline-precondition pattern); confirm the existing archival transaction's surviving-columns set now also preserves `type` for a milestone's thinned row, in `src/bindle/work_ledger.py`. Depends on: T002, T004.

### Tests for User Story 5

- [ ] T017 [US5] `TestProjectionExcludesMilestones`: no milestone row appears in a generated projection across every milestone status (`open`/`review`/`accepted`/`superseded`) and claim state (SC-005); a task blocked by a milestone is projected as ineligible while the blocking milestone itself never appears as a row; projection determinism (regenerate twice, equal result) still holds. `TestMilestoneArchival`: archiving a milestone with an unresolved child fails and leaves its row completely unmodified (SC-006); archiving succeeds once every child is resolved; a child's `parent_id` still resolves to the archived milestone's surviving `type`/`status` afterward (SC-007); a simulated concurrent race in which a new open child is inserted while an archival attempt is in flight resolves to the archival being refused, never to an archived milestone with a live child underneath it, in `tests/test_work_ledger.py`. Depends on: T015, T016.

**Checkpoint**: All five user stories are independently functional. Feature-complete.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T018 [P] Add `TestQuickstartEndToEndV2`, one scripted run through `quickstart.md`'s five scenarios end to end (mirroring 001's own `TestQuickstartEndToEnd` convention), in `tests/test_work_ledger.py`. Depends on: T007, T009, T012, T014, T017.
- [ ] T019 Run `bash scripts/check.sh` and resolve any lint, type, or formatting findings it surfaces in `src/bindle/work_ledger.py` / `tests/test_work_ledger.py`. Depends on: T018.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 2)**: No dependencies beyond the existing 001 implementation. BLOCKS every user story.
- **User Stories (Phase 3–7)**: All depend on Foundational (Phase 2) completing. US1 (Phase 3) has no further implementation task of its own (delivered by Foundational) — only its own verification test. US3 depends on US2's `has_qualifying_evidence` (T008) being present, since review-readiness (T010) calls it. US4 depends on US3's `mark_in_review` existing (a milestone must be able to enter `review` before `decline_review`/`accept_milestone` are meaningful to test). US5 is independent of US3/US4's transition functions (it only needs Foundational's type/blocking work) but is ordered last to match spec.md's own priority (P3).
- **Polish (Phase 8)**: Depends on every user story's tests existing.

### Parallel Opportunities

Genuinely low, and this is stated plainly rather than inflated: every implementation task targets the same single file (`src/bindle/work_ledger.py`), and every test task targets the same single test file (`tests/test_work_ledger.py`). File-level `[P]` parallelism (the literal Spec Kit definition) essentially does not exist for this feature. T018 is the only task marked `[P]` above, and only because it is additive (a new test class with no shared mutable state) relative to the other Phase 8 task — see the Composition note below for the actual agent-sized grouping, which reasons about *semantic* independence rather than file paths, per this repository's own `task-composition` skill and 001's own precedent ("parallelism here is semantic, not file-isolated").

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 2: Foundational (T001–T006).
2. Complete Phase 3: User Story 1 (T007 — verification only; implementation already lands in Phase 2).
3. **STOP and VALIDATE**: `type`/`parent_id` creation and durability work end to end with no milestone-lifecycle behavior yet.

### Incremental Delivery

1. Foundational → US1 (MVP: typed, attributed work items) → US2 (mechanical done-evidence predicate) → US3 (review readiness + transition + claim) → US4 (decline/accept, history preservation) → US5 (Symphony exclusion + milestone archival).
2. Each story adds value without breaking a previously-landed one, per spec.md's own story independence.

## Composition note

Per the user's explicit request, a separate task-composition analysis (using this repository's `task-composition` skill) is performed against this task list before implementation begins, to determine actual agent-sized delivery slices — this tasks.md's phase/story structure is the *decomposition*, not the *execution plan*; see the composition report delivered alongside this file for the grouping that actually governs implementation order.
