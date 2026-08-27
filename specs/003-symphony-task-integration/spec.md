# Feature Specification: Symphony Task Integration

**Feature Branch**: `spec/symphony-task-integration`

**Created**: 2026-08-27

**Status**: Draft

**Input**: User description: "Give Bindle a narrow, explicit path for durable task work to reach Symphony, without adopting milestone scheduling yet: (1) a loader that reads a settled Spec Kit tasks.md task set into canonical work_items, idempotently; (2) a published, versioned, read-only Symphony-facing SQLite projection containing task rows only; (3) the smallest supported external write surface to claim, release, and complete a task, built on the ledger's existing atomic primitives. Milestones remain orthogonal — never loaded from Spec Kit as anything but a task, never present in the published projection."

**Baseline**: This feature builds on top of `specs/001-durable-work-ledger/` and `specs/002-milestone-task-work-items/` (implemented in `src/bindle/work_ledger.py`, verified by `tests/test_work_ledger.py`, adopted in `docs/DECISIONS.md` D038). It does not reopen either feature's settled decisions — SQLite as the persistence format, INSERT-based claim arbitration, the `type`/`parent_id` milestone/task split, or the existing internal `generate_projection()` and its two contract documents (`specs/001-durable-work-ledger/contracts/coordinator-projection.md`, `specs/002-milestone-task-work-items/contracts/coordinator-projection-v2.md`), all of which remain unchanged and continue to serve their own existing purpose. This feature adds a second, purpose-built, externally-published artifact alongside them — it does not replace or generalize the existing one.

**Terminology note**: "Projection" is used for two distinct things in this document family. The existing internal `generate_projection()`/`ProjectedWorkItem` (001/002) is an in-process Python computation used however Bindle's own code likes. This feature's **published projection** is a new, physically separate artifact meant for an external process to read on its own schedule, with its own explicit shape and version. The two are related (they compute overlapping facts from the same canonical state) but are not the same artifact and do not share a schema.

## User Scenarios & Testing *(mandatory)*

<!--
  This feature's "users" are the repository maintainer (invoking the loader
  explicitly), and an external coordinator process (reading the published
  projection and using the write surface) — not an external product
  audience. "Symphony" names the coordinator this feature is built toward,
  but nothing here adopts, installs, or invokes Symphony itself.
-->

### User Story 1 - Load a settled Spec Kit task set into the durable ledger (Priority: P1)

A maintainer has a Spec Kit feature directory (`specs/NNN-slug/`) whose `tasks.md` decomposition is settled and ready to become durable, coordinator-visible work. They explicitly invoke a loading operation naming that one feature directory, and every task in it becomes a canonical work item — without disturbing any task already loaded from a prior invocation.

**Why this priority**: Nothing else in this feature has real content to project or claim until Spec Kit's task decomposition actually becomes durable ledger state. This is the foundation the other two stories build on.

**Independent Test**: Load one feature directory's `tasks.md` into an empty ledger; confirm every task line becomes a distinct work item with its title, description, and declared dependencies intact; run the same load again with no source changes and confirm the ledger's set of ids, statuses, claims, and evidence is completely unchanged.

**Acceptance Scenarios**:

1. **Given** a feature directory whose `tasks.md` contains several task lines, **When** a maintainer invokes the loading operation naming that directory, **Then** one work item of type `task` is created per task line, each `open`, each attributed back to its exact task line as its source.
2. **Given** two different feature directories that each declare a task with the same Spec Kit id (e.g. both have a "T001"), **When** both are loaded, **Then** they produce two distinct, independently identifiable work items with no collision.
3. **Given** a feature directory already loaded once, **When** the loading operation is invoked again against it with no source changes, **Then** no new work item is created and no existing work item's row changes.
4. **Given** a previously loaded task that has since been marked done or claimed, **When** the loading operation is invoked again against its feature directory, **Then** that task's status and claim are completely unaffected by the reload.
5. **Given** a task line that declares a dependency on another task id within the same `tasks.md`, **When** the feature directory is loaded, **Then** the dependent task is recorded as blocked on the referenced task's own loaded work item, regardless of the order the two lines appear in the file.
6. **Given** a `tasks.md` edited after its first load to add a title/description change or a newly declared dependency on an already-loaded task, **When** the loading operation is invoked again, **Then** the changed declarative text and the newly declared dependency are reflected, and no previously recorded dependency is removed.
7. **Given** a task line the loader cannot unambiguously parse, **When** the loading operation runs, **Then** that one line is reported as skipped with a clear reason, and every other well-formed task line in the same file still loads normally.

---

### User Story 2 - Publish a minimal, versioned, task-only projection for an external coordinator (Priority: P1)

An external coordinator process needs to discover which tasks currently exist and which of them it may start, without ever touching Bindle's own internal tables, without ever seeing a milestone, and without having to re-derive eligibility itself from blocking or claim facts it cannot see.

**Why this priority**: This is the actual seam the feature is named for — the point at which durable Bindle task work becomes visible to something outside Bindle at all.

**Independent Test**: Generate the published projection over a ledger containing a mix of open, blocked, claimed, done, and milestone-attributed work items, and confirm it contains exactly the task rows, each carrying a direct status and a `dispatchable` fact matching the ledger's own "available to start" computation, with no milestone row present under any status.

**Acceptance Scenarios**:

1. **Given** a ledger containing both task and milestone work items in a mix of statuses, **When** the published projection is generated, **Then** it contains one row per non-archived task work item and zero rows for any milestone work item, regardless of that milestone's status, claim, or blocking state.
2. **Given** a task that is open, unclaimed, and unblocked, **When** the projection is generated, **Then** that task's row reports `dispatchable = true`.
3. **Given** a task that is open but currently claimed, or open but blocked by an unresolved dependency, **When** the projection is generated, **Then** that task's row reports `dispatchable = false`, without the reader having to inspect claims or blocking edges itself.
4. **Given** a task that is done or superseded, **When** the projection is generated, **Then** its row's status reflects that terminal state directly, as a readable value rather than a pair of booleans.
5. **Given** an unchanged ledger, **When** the projection is generated twice in a row, **Then** both generations produce an equivalent result.
6. **Given** the published projection's own documented shape, **When** an external reader inspects it, **Then** it can determine the projection's version without reading any of Bindle's internal ledger tables.

---

### User Story 3 - An external coordinator claims, releases, and completes a task (Priority: P2)

Having read the published projection and picked a dispatchable task, an external coordinator needs to actually acquire it, work on it, and mark it done (or release it back) — without being handed a raw database connection or a way to mutate ledger state outside these three narrow operations.

**Why this priority**: A read-only projection alone lets a coordinator look but not act; this is the smallest write surface that makes the projection actionable, deferred behind the two read-side stories above because it has no purpose without them.

**Independent Test**: Using only the operations this feature defines, claim a task read from the projection, confirm a concurrent second claim attempt against the same task fails immediately and unambiguously, release the first claim, re-claim it, and mark it done — confirming each step's result matches the ledger's own existing claim/release/mark-done guarantees.

**Acceptance Scenarios**:

1. **Given** an unclaimed, dispatchable task, **When** an external caller invokes the claim operation, **Then** the claim succeeds and is recorded exactly as an ordinary ledger claim (owner, timestamp).
2. **Given** a task already claimed by one caller, **When** a second caller invokes the claim operation against the same task, **Then** the second attempt fails immediately and unambiguously, with no window in which both callers could believe they succeeded.
3. **Given** a task claimed by a specific owner, **When** that owner invokes the release operation, **Then** the claim is removed and the task becomes claimable again; **When** a different caller invokes release against a claim it does not hold, **Then** nothing changes.
4. **Given** a task claimed by its caller, **When** that caller invokes the mark-done operation, **Then** the task transitions to done exactly as the ledger's existing guarded transition already defines; **When** the same operation is invoked against a task that is not currently open, **Then** it is rejected rather than silently reapplied.
5. **Given** a milestone work item's id, **When** any of the claim, release, or mark-done operations is invoked against it, **Then** the operation is rejected rather than silently treating the milestone as a task.

### Edge Cases

- A task line names a dependency on a Spec Kit task id that does not exist anywhere in the same `tasks.md` — the loader reports this rather than silently creating a dangling reference or silently dropping the dependency.
- A feature directory is loaded, then its `tasks.md` is edited to remove a task line entirely — the loader never deletes or archives a previously loaded work item on this basis; a task's durable existence, once loaded, is never retracted by a later reload.
- The published projection is generated while a claim or status change lands concurrently — the generated snapshot reflects whatever state existed at generation time; the write surface's own atomicity, not projection freshness, is what protects a concurrent dispatch decision.
- An external caller attempts to claim a task id that does not exist in the ledger at all — the operation reports a clear failure distinct from "already claimed."
- Loading is invoked against a feature directory whose `tasks.md` does not exist, or exists but is empty — the operation reports this clearly rather than silently creating zero work items with no explanation.

## Requirements *(mandatory)*

### Functional Requirements

**Loading (User Story 1)**

- **FR-001**: System MUST provide an explicit, maintainer-invoked loading operation that takes exactly one Spec Kit feature directory as input and creates one canonical work item of type `task` for each parseable task line in that directory's `tasks.md`.
- **FR-002**: System MUST NOT create any work item as a side effect of a `tasks.md` file being created, edited, or committed — loading happens only through the explicit operation in FR-001, never automatically.
- **FR-003**: Every loaded work item MUST record source provenance sufficient to recognize the exact same Spec Kit task on a later invocation, using the ledger's existing `source_kind = 'speckit_task'` value.
- **FR-004**: The recorded source identity MUST combine the feature directory and the task's own Spec Kit id, since Spec Kit task ids are unique only within one feature directory, not across the repository's `specs/` tree.
- **FR-005**: Re-invoking the loading operation against a feature directory it has already loaded MUST NOT create a duplicate work item for any task line it has already loaded.
- **FR-006**: Re-invoking the loading operation MUST NOT alter a previously loaded task's runtime-owned state — its status, its claim, or its recorded evidence — regardless of that task's current status.
- **FR-007**: Re-invoking the loading operation MAY update a previously loaded task's declarative fields (title, description) to match the current `tasks.md` content; these are the only fields a reload may change on an existing row.
- **FR-008**: Re-invoking the loading operation MAY add a dependency edge declared in the current `tasks.md` that was not present at a prior load, but MUST NOT remove a dependency edge recorded by a prior load, even if the current `tasks.md` no longer declares it.
- **FR-009**: A declared dependency between two task lines in the same `tasks.md` MUST resolve correctly regardless of the order the two lines appear in the file, within one invocation of the loading operation.
- **FR-010**: A declared dependency naming a task id that does not resolve to any task line in the same `tasks.md` MUST be reported to the caller rather than silently discarded or silently recorded against a nonexistent work item.
- **FR-011**: A task line the loading operation cannot unambiguously parse MUST be reported as skipped, with every other well-formed task line in the same file still loaded — the operation is not required to be all-or-nothing across an entire `tasks.md`, consistent with the ledger's own existing non-goal of no transactional multi-item write (`specs/001-durable-work-ledger/contracts/work-item-record.md`).
- **FR-012**: The loading operation MUST NOT read, require, or depend on the `- [ ]`/`- [x]` checkbox state of a task line — settledness is established solely by the maintainer's explicit invocation naming the feature directory, not by any in-file marker.

**Publishing (User Story 2)**

- **FR-013**: System MUST provide an operation that generates a published projection: a distinct, versioned, read-only artifact derived entirely from current canonical ledger state, separate from the existing internal `generate_projection()`/`ProjectedWorkItem` contract.
- **FR-014**: The published projection MUST contain exactly one row per non-archived work item of type `task`, and MUST NOT contain a row for any work item of type `milestone`, under any status, claim, or blocking state.
- **FR-015**: Each published row MUST carry: a stable id, a non-empty identifier suitable for external workspace naming, a title, a description, a direct human-readable status value, a derived `dispatchable` boolean, and the canonical work item's own creation timestamp (`created_at`), preserved verbatim rather than derived or synthesized at publish time.
- **FR-016**: `dispatchable` MUST be computed entirely inside Bindle as `type = 'task' AND status = 'open' AND NOT claimed AND NOT blocked`, identical in substance to the ledger's existing "available to start" computation, and MUST require no blocking, claim, or dependency evaluation by the external reader.
- **FR-017**: The published projection MUST be a disposable, regenerable artifact: regenerating it from unchanged canonical ledger state MUST produce an equivalent result, and it MUST NOT be treated as, or required to serve as, the only record of any canonical fact.
- **FR-018**: The published projection's shape MUST carry its own version identifier, independent of Bindle's internal ledger schema version (`_SCHEMA_VERSION`), discoverable by an external reader without inspecting Bindle's internal tables.
- **FR-019**: This feature MUST NOT modify the existing internal coordinator-projection contracts (`specs/001-durable-work-ledger/contracts/coordinator-projection.md`, `specs/002-milestone-task-work-items/contracts/coordinator-projection-v2.md`) or the `ProjectedWorkItem` shape they describe.

**Write surface (User Story 3)**

- **FR-020**: System MUST provide an explicit operation for an external caller to claim a specific task by id, built directly on the ledger's existing atomic claim arbitration, with no additional arbitration mechanism introduced.
- **FR-021**: System MUST provide an explicit operation for an external caller to release a claim it holds; this operation MUST NOT release a claim on behalf of a different owner, except through the ledger's existing reconciliation-justified override path.
- **FR-022**: System MUST provide an explicit operation for an external caller to mark a claimed task done, rejecting the transition when the task is not currently open, mirroring the ledger's existing guarded-transition semantics.
- **FR-023**: None of the operations in FR-020–FR-022 MUST expose raw SQL, a direct database handle, or any mutation of ledger state beyond that single named operation.
- **FR-024**: Each of the operations in FR-020–FR-022 MUST reject an attempt made against a work item of type `milestone`, rather than silently treating it as a task.

**Cross-cutting**

- **FR-025**: This feature MUST NOT introduce any milestone-scheduling policy, priority, or ranking into the `dispatchable` derivation, and MUST NOT change how milestone work items themselves behave outside of this feature's own read/write surfaces.
- **FR-026**: This feature MUST NOT install, start, stop, configure, or otherwise supervise Symphony, and MUST NOT build a Symphony-specific tracker-format adapter — it ends at a documented, versioned, Bindle-owned interface.

### Key Entities

- **Loaded Task Work Item**: An existing `work_items` row (type `task`) created by the loading operation, distinguished from any other task only by carrying `source_kind = 'speckit_task'` and a source identity that combines its originating feature directory and Spec Kit task id.
- **Symphony Projection Row**: A row in the new published projection artifact — id, identifier, title, description, status, dispatchable, created_at — computed fresh at generation time and never itself a source of durable truth.
- **Source Reference (Spec Kit)**: The pairing of a feature directory path and a Spec Kit task id that together give one Spec Kit task a stable identity across repeated loads.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A maintainer can turn a settled Spec Kit feature's entire task list into durable, independently queryable ledger work items in one explicit action.
- **SC-002**: Loading the same feature directory a second time, with no source changes, leaves the ledger's set of task ids, statuses, claims, and evidence completely unchanged.
- **SC-003**: A task that has reached done, or been claimed, before a reload retains that exact state across any number of subsequent reloads of its source feature directory.
- **SC-004**: Two different Spec Kit feature directories that each declare a task with the same Spec Kit id load as two distinct, independently identifiable work items, with zero collisions observed across repeated loads.
- **SC-005**: An external reader can determine, from the published projection alone, exactly which tasks are currently eligible to start, without issuing any query against Bindle's internal tables.
- **SC-006**: Regenerating the published projection twice from unchanged ledger state produces an equivalent result both times.
- **SC-007**: No milestone work item appears in the published projection, in any status, at any point this was tested.
- **SC-008**: Of any number of concurrent external claim attempts issued against one never-before-claimed task, exactly one succeeds and every other receives an immediate, unambiguous rejection.
- **SC-009**: An external caller can complete a full claim-to-done lifecycle for a task discovered through the published projection using only this feature's defined operations, with zero raw SQL and zero direct database access.

## Assumptions

- "Settled," for a Spec Kit task set, means the maintainer has decided this `tasks.md` is ready to become durable ledger state — established solely by their explicit invocation of the loading operation naming that feature directory. The system does not parse or trust the `- [ ]`/`- [x]` checkbox state as a settledness signal, since nothing in Spec Kit's own tooling treats that state as machine-checked today.
- The one input shape this loader parses is the task-line format already used by `specs/001-durable-work-ledger/tasks.md` and `specs/002-milestone-task-work-items/tasks.md` (`- [ ] T### [optional story tag] Description. ... Depends on: T00X, T00Y.`). A differently structured Markdown task list is out of scope for this feature.
- Loading, publishing, and the write surface all operate against the same repository's ledger `specs/001`/`specs/002` already define (the Git common directory) — this feature does not add cross-repository loading or a remote ledger.
- "External coordinator" in this document means any future reader of the published projection and user of the write surface, whether or not it is ultimately Symphony — this feature does not adopt, install, or invoke Symphony itself, and does not build a translation layer into Symphony's own local JSON tracker format.
- Milestone work items are unaffected by this feature in every respect other than continuing to be excluded from any coordinator-facing projection, exactly as `specs/002-milestone-task-work-items` already established for the existing internal projection.
- The write surface's exposure mechanism (CLI, library function, or both) is an implementation decision for the planning phase, not a product-scope question this specification needs to settle — either satisfies every functional requirement above identically.
