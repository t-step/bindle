---

description: "Task list template for feature implementation"
---

# Tasks: Durable Work Ledger

**Input**: Design documents from `/specs/001-durable-work-ledger/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. spec.md gives every user story an explicit "Independent Test," and quickstart.md is itself framed as "a validation guide for the model... to be re-used as the shape of real tests once the first implementation slice exists" — tests are the natural derivation here, not an optional addition.

**Organization**: Tasks are grouped by user story (spec.md's User Story 1–4, priorities P1/P1/P2/P3) to enable independent implementation and testing of each story.

**2026-08-26 note**: This file was generated after this feature's original scope deferred task generation (`plan.md`'s "task-generation scope correction"). No source file existed before this generation; `src/bindle/work_ledger.py` and `tests/test_work_ledger.py` are both net-new. All tasks below target those two files, per `plan.md`'s Structure Decision (single-project layout, one purpose-built module, one test file) — this is a genuine, un-optimized constraint of the accepted plan, not an artifact of how these tasks were split.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Single-project layout per `plan.md`'s Structure Decision:
- `src/bindle/work_ledger.py` — the entire ledger module (schema init, read/list/create/claim/reconcile/archive/project functions over stdlib `sqlite3`)
- `tests/test_work_ledger.py` — the entire test suite

Both are single files for this feature; most tasks below therefore target one of these two files and are sequential with respect to each other, not because of artificial task splitting, but because that is what the accepted plan's file layout actually implies.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure. No new dependencies — `sqlite3` is Python stdlib, matching this repository's existing zero-dependency posture (research.md, "Decision: storage format").

- [x] T001 Create `src/bindle/work_ledger.py` module skeleton, following the existing flat per-provider module convention (`src/bindle/repo.py`, `projectmem.py`, `qmd.py`)
- [x] T002 [P] Create `tests/test_work_ledger.py` test file skeleton with `pytest` imports and a temp-directory-backed fixture for a fake Git common directory

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Storage-location resolution, connection lifecycle, and schema bootstrap — every user story's functions open the same database through this layer.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T003 Implement ledger database path resolution in `src/bindle/work_ledger.py` (resolve from the Git common directory via `RepoInfo`/`repo_root` in `src/bindle/repo.py`, per research.md's "Decision: storage location" — not the invoking worktree)
- [x] T004 Implement a short-lived per-operation connection helper in `src/bindle/work_ledger.py` (opens a `sqlite3` connection, sets `PRAGMA foreign_keys = ON`, `PRAGMA journal_mode = WAL`, `PRAGMA synchronous = NORMAL`, `PRAGMA busy_timeout = 2000`, and closes on completion — no long-lived connection or daemon, per research.md's "Decision: connection lifecycle and concurrency")
- [x] T005 Implement schema initialization in `src/bindle/work_ledger.py` (`CREATE TABLE` for `work_items`, `work_item_blocked_by`, `work_item_claims`, `work_item_evidence` exactly per data-model.md's "Schema overview," including all `CHECK`/`FOREIGN KEY`/`PRIMARY KEY` constraints)
- [x] T006 Implement schema-version bootstrap and check in `src/bindle/work_ledger.py` (read `PRAGMA user_version`; `0` → run T005's schema creation and set `user_version = 1`; nonzero → compare against the expected version, per research.md's "Decision: schema versioning and migration ownership")
- [x] T007 Test schema bootstrap, mandatory PRAGMA settings, and version-check idempotency (a fresh db initializes all four tables and their constraints; reopening an already-initialized db does not re-create or reset the schema) in `tests/test_work_ledger.py` (depends on T003–T006)

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - Decompose accepted work into durable items (Priority: P1) 🎯 MVP

**Goal**: An agent can explicitly promote a plan/spec/task item into a durable work item carrying a stable identifier, a summary, and a source pointer — recoverable by a fresh session in a different worktree with zero information from the creating session.

**Independent Test**: Create several work items from a plan's decomposition, end the session, and confirm — from a fresh session with no memory of the first — that the same items, with the same identity and source pointer, are still discoverable and intelligible.

### Implementation for User Story 1

- [x] T008 [US1] Implement `create_work_item(id, title, source_kind, source_locator, source_promoted_by=None)` in `src/bindle/work_ledger.py` (single `INSERT` into `work_items` with `status = 'open'`, `created_at`/`updated_at` set — the only operation that creates a Work Item, per FR-002/FR-003; depends on T003–T006)
- [x] T009 [US1] Implement `get_work_item(id)` in `src/bindle/work_ledger.py` (single-row `SELECT` by `id`, returning the same record structure regardless of caller worktree/session, per contracts/work-item-record.md's Read guarantees)
- [x] T010 [US1] Implement `list_work_items()` in `src/bindle/work_ledger.py` (`SELECT` across all rows, active and archived)

### Tests for User Story 1

- [x] T011 [US1] Test that creating a work item stores a stable `id`, `title`, and source pointer (Acceptance Scenario 1.1) in `tests/test_work_ledger.py`
- [x] T012 [US1] Test that a created work item's identity, source pointer, and coordination facts are fully recoverable through a second, independent connection to the same database file, with no state carried from the creating connection (simulates a fresh session in a different worktree; Acceptance Scenario 1.2, SC-001) in `tests/test_work_ledger.py`
- [x] T013 [US1] Test that no work item is created merely by the existence or editing of an upstream `tasks.md` — only an explicit `create_work_item` call creates one (Acceptance Scenario 1.3) in `tests/test_work_ledger.py`

**Checkpoint**: User Story 1 is fully functional and independently testable — items can be created and are durably recoverable.

---

## Phase 4: User Story 2 - Resume and determine what's actually available (Priority: P1)

**Goal**: An agent can determine, from repository state alone, which recorded work items are currently safe to start — not claimed, not blocked, not done, not superseded.

**Independent Test**: Construct a ledger containing a mix of open/unclaimed, open/claimed, blocked, done, and superseded items, including at least one chain of two or more blocking relationships, and confirm that the set of items correctly identified as "available to start" excludes every claimed, blocked, done, and superseded item and includes every other one.

### Implementation for User Story 2

- [x] T014 [US2] Implement `add_blocked_by(work_item_id, blocked_on_id)` in `src/bindle/work_ledger.py` (single `INSERT` into `work_item_blocked_by`; relies on the Foundational schema's `CHECK`/`FOREIGN KEY` constraints to reject a direct self-cycle or a dangling target at write time; depends on T008)
- [x] T015 [US2] Implement `is_blocked(work_item_id)` in `src/bindle/work_ledger.py` (the derived `EXISTS` query per data-model.md's "Dependency resolution": any `blocked_by` row resolving to an open dependency, or to no row at all, counts as still blocking)
- [x] T016 [US2] Implement `is_claimed(work_item_id)` in `src/bindle/work_ledger.py` (`EXISTS` query against `work_item_claims` — claimed status is never a column on `work_items` itself)
- [x] T017 [US2] Implement `list_available_work_items()` in `src/bindle/work_ledger.py` (the composite query: `status = 'open'` AND NOT claimed AND NOT blocked, per data-model.md's "Available to start")
- [x] T018 [US2] Implement `mark_done(work_item_id)` and `mark_superseded(work_item_id, superseded_by)` in `src/bindle/work_ledger.py` (guarded `UPDATE ... WHERE status = 'open'` transitions per research.md's "Decision: transaction boundaries," so a double-transition race fails the row-count check rather than silently double-applying)

### Tests for User Story 2

- [x] T019 [US2] Test a chain of three or more blocking relationships correctly excludes the blocked items from availability (Acceptance Scenario 2.1, SC-002) in `tests/test_work_ledger.py`
- [x] T020 [US2] Test an unblocked, unclaimed item is reported available (Acceptance Scenario 2.2) in `tests/test_work_ledger.py`
- [x] T021 [US2] Test marking a blocking item done removes it as a blocker for its dependents (Acceptance Scenario 2.3) in `tests/test_work_ledger.py`
- [x] T022 [US2] Test full-set availability enumeration against a constructed ledger mixing open/unclaimed, open/claimed, blocked, done, and superseded items matches the expected set exactly (User Story 2's own Independent Test) in `tests/test_work_ledger.py` — **construct the open/claimed fixture row by inserting directly into `work_item_claims` (the SQLite persistence boundary), not by calling US3's `claim()` (T023).** This task tests availability computation over a given valid ledger state, not claim acquisition; proving that `claim()` itself produces that state is US3's own responsibility (T029/T028). Direct-insert construction keeps US2 free of any implementation dependency on US3, preserving the S3 ∥ S4 parallel-execution opportunity — see `plans/active/2026-08-26-work-ledger-task-composition-handoff.md`.

**Checkpoint**: User Stories 1 and 2 both work independently — items can be created, decomposed with dependencies, and correctly evaluated for availability.

---

## Phase 5: User Story 3 - Claim, work, and reconcile across worktrees without collision (Priority: P2)

**Goal**: Two agents (or the same agent across sessions) can each claim and work a different item, in different worktrees, without one claim affecting the other's record; a claim whose worktree has disappeared becomes visible as stale rather than silently trusted.

**Independent Test**: Record two claims against two different items from two different (simulated) worktrees, confirm neither claim affects the other item's record, then delete one claimed item's worktree/branch and confirm that reconciliation against actual repository state flags that claim as stale rather than treating the item as still in progress or, worse, as done.

### Implementation for User Story 3

- [x] T023 [US3] Implement `claim(work_item_id, owner, worktree_path=None, branch=None)` in `src/bindle/work_ledger.py` (single `INSERT` into `work_item_claims`; the primary key on `work_item_id` is the sole arbitration mechanism for concurrent attempts, per FR-018 and research.md's "Decision: claim atomicity")
- [x] T024 [US3] Implement `release_claim(work_item_id, owner)` in `src/bindle/work_ledger.py` (ordinary release by the recorded owner; `DELETE` is a no-op, not an error, if the row is already absent)
- [x] T025 [US3] Implement `override_release_claim(work_item_id, note=None)` in `src/bindle/work_ledger.py` (one transaction: `DELETE` the claim row, plus an optional `kind = 'other'` Evidence Pointer `INSERT` documenting the justification, per FR-019 and research.md's "Decision: transaction boundaries"; depends on T023, T027)
- [x] T026 [US3] Implement `add_evidence(work_item_id, kind, value, note=None)` in `src/bindle/work_ledger.py` (append-only `INSERT` into `work_item_evidence` — no `UPDATE` path is defined, per data-model.md's Evidence Pointer invariant)
- [x] T027 [US3] Implement `reconcile()` in `src/bindle/work_ledger.py` (read-only report over current state plus observed repository/filesystem state, producing `stale_claim` (worktree/branch existence check), `corrupt_claim` (via `PRAGMA integrity_check` plus row-shape inspection), `dangling_blocker` (`LEFT JOIN` against `work_items`), `duplicate_source` (`GROUP BY source_kind, source_locator HAVING COUNT(*) > 1`), and `cycle_detected` (the `WITH RECURSIVE` reachability query) findings, per data-model.md's "Reconciliation Report"; never opens a write transaction, per FR-010)

### Tests for User Story 3

- [x] T028 [US3] Test two independent claims against two different items, from two simulated worktrees, do not affect each other's stored record (Acceptance Scenario 3.1, SC-004) in `tests/test_work_ledger.py`
- [x] T029 [US3] Test that many concurrent claim attempts against the same currently-unclaimed item resolve to exactly one success and every other attempt receives an immediate, unambiguous failure, repeated across many trials (FR-018, SC-004a) in `tests/test_work_ledger.py`
- [x] T030 [US3] Test that reconciliation reports a claim as stale once its recorded worktree path no longer exists, without mutating the claim row or the item's computed availability (Acceptance Scenario 3.2, SC-003) in `tests/test_work_ledger.py`
- [x] T031 [US3] Test that reconciliation reports a corrupt claim distinctly from a stale claim, and that the item remains computed as unavailable in both cases until an explicit release (SC-010) in `tests/test_work_ledger.py`
- [x] T032 [US3] Test that an override release does not itself grant the releasing actor a claim — a racing concurrent acquire may still legitimately win the immediately following `claim()` attempt (spec.md Edge Case on override release) in `tests/test_work_ledger.py`
- [x] T033 [US3] Test that an Evidence Pointer is left unchanged after its referenced branch is later rebased, squashed, or deleted (Acceptance Scenario 3.3) in `tests/test_work_ledger.py`

**Checkpoint**: User Stories 1, 2, and 3 all work independently — claims, releases, and reconciliation are correct and multi-worktree-safe.

---

## Phase 6: User Story 4 - Materialize a schedulable view for an external coordinator (Priority: P3)

**Goal**: Generate a disposable, regenerable projection of currently-runnable work items sufficient for a future external coordinator to dispatch one, without reshaping the ledger around that coordinator's schema.

**Independent Test**: Given a ledger with a mix of blocked and unblocked items, generate a projection and confirm it marks exactly the unblocked, unclaimed, non-terminal items as eligible, and that regenerating the projection from the same ledger state twice produces the same result.

### Implementation for User Story 4

- [ ] T034 [US4] Implement `generate_projection()` in `src/bindle/work_ledger.py` (derives `id`, a coarse active/terminal classification, and computed eligibility from `list_available_work_items()`/`is_blocked()`/`is_claimed()`, per contracts/coordinator-projection.md; withholds any blocked or claimed item from eligibility; computes and persists no dispatch order, priority, or concurrency limit, per FR-015)

### Tests for User Story 4

- [ ] T035 [US4] Test that a blocked work item is not presented as eligible in a generated projection, even though the illustrative target adapter would not otherwise re-check blocking itself (Acceptance Scenario 4.1) in `tests/test_work_ledger.py`
- [ ] T036 [US4] Test that regenerating a projection twice from the same, unchanged ledger state produces an equivalent projection both times, and that generating a projection performs no write to the ledger (Acceptance Scenario 4.2, SC-005) in `tests/test_work_ledger.py`
- [ ] T037 [US4] Test that every user-facing coordination fact (status, blocking, claim, evidence) remains fully available when no projection has ever been generated (Acceptance Scenario 4.3) in `tests/test_work_ledger.py`

**Checkpoint**: All four user stories are independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Archival, the remaining spec.md Edge Cases not owned by a single user story above, and an end-to-end quickstart pass.

- [ ] T038 Implement `archive_work_item(id)` in `src/bindle/work_ledger.py` (single transaction thinning a `done`/`superseded` row in place to `id`/`status`/`superseded_by`/`archived_at`, deleting that item's own `blocked_by` edges, its evidence, and any lingering claim, per data-model.md's "Archival"; depends on T018, T023–T027, T038 itself touches T014's edges table and T026's evidence table)
- [ ] T039 Test that archiving a satisfied prerequisite leaves every dependent item's blocked evaluation still correctly reporting it as satisfied (SC-008) in `tests/test_work_ledger.py`
- [x] T040 Test that a `blocked_by` reference to an id that never validly identified a work item is reported unresolvable (`dangling_blocker`), and is distinguishable in reconciliation detail from a reference to an item that was genuinely completed and archived (SC-009) in `tests/test_work_ledger.py`
- [x] T041 Test that two items promoted from the same underlying source are surfaced by reconciliation as `duplicate_source` rather than silently merged or rejected (spec.md Edge Case on duplicate promotion) in `tests/test_work_ledger.py`
- [x] T042 Test that an indirect blocking cycle (`A blocked_by B`, `B blocked_by A`, via two independently-written edges) is detected by `reconcile()`'s `cycle_detected` finding (spec.md Edge Case on circular blocking) in `tests/test_work_ledger.py`
- [ ] T043 Run quickstart.md Scenarios 1–5 end-to-end as a single integration test tying together creation, availability, claim/reconcile/override, and projection generation in `tests/test_work_ledger.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup (T001) completion — BLOCKS all user stories.
- **User Stories (Phase 3–6)**: All depend on Foundational (Phase 2) completion.
  - User Story 2 additionally depends on `create_work_item` (T008, US1) existing, since blocking/availability tests need work items to exist — in practice, US2 cannot be meaningfully tested without US1's creation path, even though its own derived-fact logic (`is_blocked`, `is_claimed`) does not itself call US1's functions. **User Story 2 has no implementation or test dependency on User Story 3**: T022's claimed-item fixture is constructed by direct `work_item_claims` insertion, not via US3's `claim()` (see T022's own line above) — this was flagged as an open ambiguity during task-composition analysis and is now resolved in this direction specifically to keep US2 and US3 independently implementable.
  - User Story 3's claim/evidence/reconcile functions operate on work items that must already exist (T008) but do not depend on US2's blocking logic.
  - User Story 4's projection depends on US2's `list_available_work_items()`/`is_blocked()` (T015, T017) and US3's `is_claimed()` (T016) to compute eligibility — this is a real, not incidental, dependency.
- **Polish (Phase 7)**: `archive_work_item` (T038) depends on US2's status transitions (T018) and touches the same tables US2 (blocked_by), US3 (claims), and the evidence table populate — it cannot be implemented before those exist. The Edge Case tests (T039–T042) depend on the specific mechanisms they exercise (archival, dangling blockers, duplicate sources, cycle detection) already existing.

### User Story Dependencies (restated plainly)

- **User Story 1 (P1)**: Depends only on Foundational. No dependency on other stories.
- **User Story 2 (P1)**: Depends on Foundational and, for any test to construct a non-trivial scenario, on US1's `create_work_item`. Its own derived-fact functions do not call US3 or US4 code, and its one test that needs a claimed item (T022) constructs that fixture by direct SQLite insertion rather than calling US3's `claim()` — US2 has no dependency, implementation or test, on US3.
- **User Story 3 (P2)**: Depends on Foundational and US1 (items must exist to be claimed). Does not depend on US2, and is not depended on by US2 (see T022's note above) — US2 and US3 are independently implementable, a real S3 ∥ S4 parallel-execution opportunity (see `plans/active/2026-08-26-work-ledger-task-composition-handoff.md`).
- **User Story 4 (P3)**: Depends on Foundational, US1, US2, and US3 — its projection function directly calls availability/blocking/claim functions from all three.

### Within Each User Story

- Implementation tasks before test tasks (tests exercise the functions implemented earlier in the same phase).
- Within US1: `create_work_item` (T008) before `get_work_item`/`list_work_items` (T009, T010), since the latter have nothing to read otherwise.
- Within US2: `add_blocked_by` (T014) before `is_blocked` (T015); both before `list_available_work_items` (T017), which composes them with `is_claimed` (T016).
- Within US3: `claim` (T023) before `release_claim`/`override_release_claim` (T024, T025); `add_evidence` (T026) before `override_release_claim` (T025), since the override's optional evidence insert reuses it; `reconcile` (T027) last, since it reads state every prior task in this phase produces.

### Parallel Opportunities

Genuinely limited by this plan's own file layout (a single implementation module and a single test file — plan.md's Structure Decision), not by how these tasks were split:

- T002 (`tests/test_work_ledger.py` skeleton) can run in parallel with T001 (`src/bindle/work_ledger.py` skeleton) — different files, no dependency between them.
- No other [P] pairs are identified. Every implementation task after T002 edits `src/bindle/work_ledger.py`; every test task edits `tests/test_work_ledger.py`; and within each file, later tasks in a phase generally read or build on functions/fixtures an earlier task in the same phase just added. Marking additional tasks `[P]` here would not reflect a real absence of file contention or dependency — it would just be wrong.
- This `[P]` marker tracks file-level independence only (per this template's own definition above). It is a narrower question than whether two *phases* are semantically independent enough to implement concurrently in separate sessions/agents despite sharing a file — User Story 2 (T014–T022) and User Story 3 (T023–T033) are exactly this case: no `[P]` marker connects them (both edit the same two files), but they have no functional dependency on each other (see "User Story Dependencies" above and T022's own fixture-construction note) and are the first candidate parallel-agent wave. See `plans/active/2026-08-26-work-ledger-task-composition-handoff.md` for that composition-level analysis — it is deliberately not re-encoded into this file's `[P]` markers, which retain their narrower, file-level meaning.

---

## Parallel Example: Setup Phase

```bash
# The only genuinely parallel pair in this task list:
Task: "Create src/bindle/work_ledger.py module skeleton"
Task: "Create tests/test_work_ledger.py test file skeleton with pytest imports and a temp Git-common-directory fixture"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: Confirm work items are created and durably recoverable, independent of everything else in this task list.

### Incremental Delivery

1. Setup + Foundational → storage/connection/schema exist.
2. + User Story 1 → items can be created and read back (MVP).
3. + User Story 2 → availability/blocking is computable.
4. + User Story 3 → claims and reconciliation are correct across worktrees.
5. + User Story 4 → a coordinator-facing projection can be generated.
6. + Polish → archival and the remaining spec.md Edge Cases are covered, plus one end-to-end quickstart pass.

Each increment adds value without breaking the previous one — but note (per "User Story Dependencies" above) this is a naturally near-linear P1→P1→P2→P3 chain for this particular feature, not four independently launchable stories: US2 needs US1 to be testable, US3 needs US1 to have items to claim, and US4 needs US2 and US3's functions directly. Only User Story 1 is a true standalone starting point.

## Notes

- [P] tasks = different files, no dependencies — used sparingly here because this plan's own file layout genuinely offers little file-level independence.
- [Story] label maps task to specific user story for traceability.
- This feature's four user stories are not independently parallelizable the way spec-kit's template assumes multi-story features often are — see "User Story Dependencies" above.
- Verify tests fail before implementing, when following a TDD discipline for a given task pair.
- Avoid: vague tasks, same-file conflicts, cross-story dependencies that break independence beyond what's stated above.
