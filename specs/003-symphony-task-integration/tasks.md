---

description: "Task list for Symphony Task Integration"
---

# Tasks: Symphony Task Integration

**Input**: Design documents from `specs/003-symphony-task-integration/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/{speckit-task-load.md,symphony-projection-v1.md,task-write-surface.md}, quickstart.md

**Tests**: Included — spec.md's own Acceptance Scenarios and Success Criteria are testable claims, and this feature's own brief explicitly listed required test coverage areas.

**Organization**: Tasks are grouped by user story (spec.md's User Story 1–3, priorities P1/P1/P2). Unlike `specs/002-milestone-task-work-items/tasks.md`, this feature has no shared schema migration every story depends on (data-model.md: no new column or table) — each story's own new primitive is scoped entirely within that story's own phase, so there is no Foundational phase distinct from the story phases below.

## Phase 1: Setup

No new project structure, dependency, or tooling is introduced. No Setup phase distinct from the per-story implementation below.

## Phase 2: Foundational

None. No change to `work_items`' schema or `_SCHEMA_VERSION` is needed anywhere in this feature (data-model.md) — every user story below is independently buildable once its own small, story-scoped addition lands.

---

## Phase 3: User Story 1 - Load a settled Spec Kit task set into the durable ledger (Priority: P1) 🎯 MVP

**Goal**: A maintainer can explicitly load one Spec Kit feature directory's `tasks.md` into canonical, idempotently-reloadable work items.

**Independent Test**: Load a fixture feature directory's `tasks.md`; confirm every task line becomes a distinct work item; reload it unchanged and confirm nothing new is created and no existing row changes.

### Implementation for User Story 1

- [x] T001 [US1] Add `resync_declarative_fields(id: str, title: str | None, description: str | None) -> bool` to `WorkLedger` in `src/bindle/work_ledger.py`: a single guarded `UPDATE work_items SET title = ?, description = ?, updated_at = ? WHERE id = ? AND archived_at IS NULL`, returning whether it matched a row, per `data-model.md`'s exact statement.
- [x] T002 [US1] Create `src/bindle/speckit_loader.py` with a narrow, regex-based `tasks.md` line parser (per `research.md`'s "Decision: tasks.md line parsing strategy"): recognizes `- [ ]`/`- [x]` task lines of the shape `T\d{3}[a-z]?` + optional bracketed tag + description, extracts an optional trailing `Depends on: T\d{3}[a-z]?(?:, T\d{3}[a-z]?)*\.` clause separately, and returns a per-line parse result distinguishing a successfully parsed task from an unparseable line (checkbox state itself is parsed but never surfaced as meaningful, per FR-012).
- [x] T003 [US1] Implement `load_feature(ledger: WorkLedger, feature_dir: str, source_promoted_by: str | None = None) -> LoadResult` in `src/bindle/speckit_loader.py`: derive `id = f"speckit:{feature_dir_name}:{task_id}"` and `source_locator = f"{feature_dir}/tasks.md#{task_id}"` per `data-model.md`'s "Source Reference"; pass 1 attempts `create_work_item(...)` for each parsed task and catches the `sqlite3.IntegrityError`/`SQLITE_CONSTRAINT_PRIMARYKEY` case (per `research.md`'s "Decision: idempotent reload mechanism") to fall back to `resync_declarative_fields(...)` instead; pass 2 resolves every `Depends on:` reference against this same file's own derived ids and calls `add_blocked_by()` for any edge not already recorded (reading the task's current edges first), tolerating a duplicate-edge `IntegrityError` as "already present." Depends on: T001, T002.
- [x] T004 [US1] Extend `load_feature()` to report, rather than silently ignore, two edge cases from `spec.md`: a `Depends on:` reference naming a task id absent from the same `tasks.md` (FR-010), and a named feature directory whose `tasks.md` is missing or contains zero parseable task lines (Edge Cases) — both surfaced as distinct fields on the returned `LoadResult`, in `src/bindle/speckit_loader.py`. Depends on: T003.

### Tests for User Story 1

- [x] T005 [P] [US1] `TestResyncDeclarativeFields`: confirms the method updates only `title`/`description`/`updated_at`, leaves `status`/`work_item_claims`/`work_item_evidence`/`source_kind`/`source_locator` completely untouched, and is a no-op (returns `False`) against an archived or nonexistent id, in `tests/test_work_ledger.py`. Depends on: T001.
- [x] T006 [US1] `TestLoadFeatureBasic`: loading a fixture `tasks.md` (several task lines) creates one `type='task'` work item per line with the correct derived `id`/`source_kind='speckit_task'`/`source_locator`, each `open` (Acceptance Scenario 1.1), in `tests/test_speckit_loader.py`. Depends on: T003.
- [x] T007 [US1] `TestLoadFeatureCrossFeatureCollision`: two fixture feature directories that each declare a "T001" load as two distinct, independently identifiable work items with no collision (Acceptance Scenario 1.2, SC-004), in `tests/test_speckit_loader.py`. Depends on: T003.
- [x] T008 [US1] `TestLoadFeatureIdempotentReload`: reloading an unchanged fixture a second time creates zero new work items and leaves every existing row byte-for-byte unchanged (Acceptance Scenario 1.3, SC-002), in `tests/test_speckit_loader.py`. Depends on: T003.
- [x] T009 [US1] `TestLoadFeaturePreservesRuntimeState`: mark one previously loaded task done and claim a second, then reload the same feature directory; confirm both tasks' status/claim are completely unaffected (Acceptance Scenario 1.4, FR-006, SC-003), in `tests/test_speckit_loader.py`. Depends on: T003.
- [x] T010 [US1] `TestLoadFeatureDependencyOrderIndependence`: a fixture whose dependent task line appears *before* the task line it depends on in file order still resolves the `blocked_by` edge correctly (Acceptance Scenario 1.5, FR-009), in `tests/test_speckit_loader.py`. Depends on: T003.
- [x] T011 [US1] `TestLoadFeatureDeclarativeResyncAndAdditiveDependencies`: editing a fixture's task title/description text and adding a new `Depends on:` reference to an already-loaded task between two loads is reflected on reload; a previously recorded dependency is never removed even if a later edit stops declaring it (Acceptance Scenario 1.6, FR-007, FR-008), in `tests/test_speckit_loader.py`. Depends on: T003.
- [x] T012 [US1] `TestLoadFeatureUnparseableLineAndMissingFile`: a fixture containing one line that looks like an attempted task line but doesn't fully match the parser's shape is reported as skipped while every other well-formed line still loads (Acceptance Scenario 1.7, FR-011); a feature directory with a missing or empty `tasks.md` is reported clearly rather than silently producing zero work items (Edge Cases, FR-012 checkbox-independence also covered here), in `tests/test_speckit_loader.py`. Depends on: T004.

**Checkpoint**: User Story 1 is independently functional and testable.

---

## Phase 4: User Story 2 - Publish a minimal, versioned, task-only projection for an external coordinator (Priority: P1)

**Goal**: A published, versioned SQLite export exists containing task-only rows with a direct status and a correctly derived `dispatchable` fact.

**Independent Test**: Generate the published projection over a mixed ledger and confirm it contains exactly the task rows with correct `dispatchable`/`status`, no milestone row under any status, and that regenerating it twice is deterministic.

### Implementation for User Story 2

- [x] T013 [US2] Add `generate_external_projection() -> list[ExternalProjectionRow]` and the `ExternalProjectionRow` dataclass (`id`, `identifier`, `title`, `description`, `status`, `dispatchable`, `created_at`) to `WorkLedger` in `src/bindle/work_ledger.py`, per `data-model.md`'s exact query — one `SELECT`, reusing the existing `_STILL_BLOCKING_CONDITION` fragment verbatim, filtered to `archived_at IS NULL AND type = 'task'`, `identifier` derived by replacing `:` with `-` in `id`, `created_at` preserved verbatim from the canonical row.
- [x] T014 [US2] Create `src/bindle/symphony_projection.py` with `publish(ledger: WorkLedger) -> str`: resolves the export path as `{ledger.repo_root}/.bindle-work/symphony-projection.sqlite3` (mirroring `ledger_path()`'s own convention), opens/creates that file, drops and recreates `task_projection` inside one transaction from `generate_external_projection()`'s current result, sets `PRAGMA user_version = 1`, and returns the resolved path. Depends on: T013.

### Tests for User Story 2

- [x] T015 [P] [US2] `TestGenerateExternalProjection`: over a ledger with a mix of open/blocked/claimed/done/superseded tasks and milestones in every status, confirms task-only rows, `dispatchable` matching the existing "available to start" computation exactly, and `status` exposed as the raw string rather than a boolean pair (Acceptance Scenarios 2.1–2.4), in `tests/test_work_ledger.py`. Depends on: T013.
- [x] T016 [US2] `TestPublish`: `publish()` writes a `task_projection` table matching `contracts/symphony-projection-v1.md`'s schema exactly, readable via a `mode=ro` URI connection, with `PRAGMA user_version` reporting `1` from the export file alone (Acceptance Scenario 2.6, FR-018), in `tests/test_symphony_projection.py`. Depends on: T014.
- [x] T017 [US2] `TestPublishDeterminism`: two `publish()` calls against an unchanged ledger produce an equal `task_projection` result both times (Acceptance Scenario 2.5, SC-006), in `tests/test_symphony_projection.py`. Depends on: T014.

**Checkpoint**: User Stories 1 and 2 are both independently functional.

---

## Phase 5: User Story 3 - An external coordinator claims, releases, and completes a task (Priority: P2)

**Goal**: A narrow, type-checked write surface exists over the ledger's existing atomic claim/release/mark-done primitives, reachable by both library and CLI.

**Independent Test**: Using only the defined operations, claim a task, confirm a concurrent second claim fails immediately, release it, re-claim it, mark it done, and confirm a milestone id is rejected by all three operations.

### Implementation for User Story 3

- [x] T018 [US3] Implement `claim_task(ledger, id, owner, worktree_path=None, branch=None)`, `release_task(ledger, id, owner)`, and `complete_task(ledger, id)` in `src/bindle/symphony_projection.py`, per `contracts/task-write-surface.md`: each first calls `ledger.get_work_item(id)` and returns a distinct `not_found`/`not_a_task` result when it is `None` or has `type != 'task'`, otherwise delegates unchanged to `WorkLedger.claim()`/`release_claim()`/`mark_done()` and passes their result through in a small result type distinguishing success from each existing failure mode (e.g. `already_claimed`, guard-not-met).
- [x] T019 [US3] Add a `bindle work` subcommand family to `src/bindle/cli.py` — `load-speckit <feature_dir>`, `publish`, `claim <id> --owner <owner> [--worktree PATH] [--branch NAME]`, `release <id> --owner <owner>`, `done <id>` — following the existing `repo`/`skills` nested-subparser convention (`work_parser`/`work_subparsers`/`_cmd_work_*` handlers, dispatched from a new `if args.command == "work":` block in `main()`), each handler calling `load_feature`/`publish`/`claim_task`/`release_task`/`complete_task` and translating the result to the existing `0` success / `1` failure exit-code convention with a `bindle work <verb>: ...` stderr message on failure. Depends on: T003, T014, T018.

### Tests for User Story 3

- [x] T020 [P] [US3] `TestClaimTaskConcurrency`: N concurrent `claim_task()` attempts against one never-before-claimed task, exactly one succeeds and every other receives an immediate, unambiguous rejection — mirroring `tests/test_work_ledger.py`'s own existing real multi-threaded claim-race test technique (Acceptance Scenario 3.2, SC-008), in `tests/test_symphony_projection.py`. Depends on: T018.
- [x] T021 [US3] `TestReleaseAndCompleteTask`: `release_task()` by the recorded owner succeeds and is a no-op when the claim is already absent or held by someone else; `complete_task()` transitions an open, claimed task to done and is rejected (not silently reapplied) against a task that is not currently open (Acceptance Scenarios 3.1, 3.3, 3.4), in `tests/test_symphony_projection.py`. Depends on: T018.
- [x] T022 [US3] `TestWriteSurfaceRejectsMilestone`: `claim_task`/`release_task`/`complete_task` each return a `not_a_task` result against a milestone id rather than silently treating it as a task (Acceptance Scenario 3.5, FR-024), in `tests/test_symphony_projection.py`. Depends on: T018.
- [x] T023 [US3] `TestWorkCliSubcommands`: `bindle work load-speckit`, `publish`, `claim`, `release`, and `done` each produce the correct exit code (`0`/`1`) and stderr message for one success case and at least one rejection case (already-claimed for `claim`, not-a-task for `done`), in `tests/test_cli.py`. Depends on: T019.

**Checkpoint**: All three user stories are independently functional. Feature-complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T024 [P] Update `docs/SYMPHONY.md` per `research.md`'s "Decision: docs/SYMPHONY.md update scope": correct the two stale "Non-scope" sentences (the "create, read, or translate work items for any Symphony tracker" clause and the "couple its own SQLite work-item model... to Symphony's tracker/storage... in any way" clause) and add a short new section pointing at `contracts/symphony-projection-v1.md` and `contracts/task-write-surface.md` as the canonical reference — mirroring how `specs/002`/D038 added the existing "Scheduling boundary" section to the same document. Leave "Canonical repository," "Pinned reference," and "What Symphony requires before first execution" untouched. Depends on: T014, T019.
- [x] T025 Add `TestQuickstartEndToEnd`, one scripted run through `quickstart.md`'s five scenarios end to end (mirroring 001/002's own `TestQuickstartEndToEnd`/`TestQuickstartEndToEndV2` convention), in `tests/test_symphony_projection.py`. Depends on: T012, T017, T023.
- [x] T026 Run `bash scripts/check.sh` and resolve any lint, type, or formatting findings it surfaces across `src/bindle/work_ledger.py`, `src/bindle/speckit_loader.py`, `src/bindle/symphony_projection.py`, `src/bindle/cli.py`, and their test files. Depends on: T024, T025.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup/Foundational (Phase 1–2)**: None — this feature has no shared schema migration or cross-story prerequisite, unlike `specs/002` (see the note under "Organization" above).
- **User Stories (Phase 3–5)**: US1 (Phase 3) and US2 (Phase 4) each depend only on their own new `WorkLedger` method (T001, T013 respectively) — they share no code and can be built in either order or concurrently. US3 (Phase 5) needs no new `WorkLedger` method at all (`claim_task`/`release_task`/`complete_task` operate on any existing task via `get_work_item`/`claim`/`release_claim`/`mark_done`, all of which already exist) and is therefore independent of US1/US2's own implementation, though its CLI wiring (T019) does call `load_feature`/`publish` for the `load-speckit`/`publish` subcommands and so textually depends on T003/T014 landing first.
- **Polish (Phase 6)**: Depends on every user story's implementation and tests existing.

### Parallel Opportunities

Real, and larger than `specs/002` found for itself: US1 (T001–T012) and US2 (T013–T017) touch entirely different new code (`speckit_loader.py` vs. the `generate_external_projection`/`publish` pair) and share no function, table, or fixture — they can be built fully in parallel. US3's own write-surface functions (T018) likewise share no code with US1/US2's implementation (only its CLI task, T019, has a textual dependency on artifacts from both). Within Phase 6, T024 (documentation) has no code dependency on T025 (quickstart test) and is marked `[P]`.

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 3: User Story 1 (T001–T012).
2. **STOP and VALIDATE**: Spec Kit task loading works end to end, idempotently, with no projection or write surface yet.

### Incremental Delivery

1. User Story 1 (loading) → User Story 2 (publishing) → User Story 3 (write surface) — each addable independently and in any order after the first, per the Parallel Opportunities above; delivered here in spec.md's own priority order (P1, P1, P2).
2. Each story adds value without breaking a previously-landed one.

## Composition note

Per this repository's own precedent for a feature of this shape (`plans/active/2026-08-27-milestone-task-composition-analysis.md`, following the `task-composition` skill), a separate task-composition analysis is performed against this task list before implementation begins, to determine actual agent-sized delivery slices and flag any shared-implementation-detail or false-serialization hazard this linear phase/story presentation might obscure — this tasks.md's phase/story structure is the *decomposition*, not the *execution plan*; see the composition report delivered alongside this file for the grouping that actually governs implementation order.
