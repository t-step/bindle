# Feature Specification: Milestone and Task Work Items

**Feature Branch**: `spec/milestone-task-work-item-model`

**Created**: 2026-08-27

**Status**: Draft

**Input**: User description: "Evolve Bindle's durable work ledger (specs/001-durable-work-ledger/) to distinguish two kinds of work item within the same canonical work_items table: 'task' (an execution unit) and 'milestone' (a human acceptance unit), while keeping Symphony completely ignorant of milestone semantics. This is an evolution of the existing, fully-implemented 001 ledger — not a greenfield feature. See the full request in this feature's planning history for the complete target-shape description, lifecycle invariants, Symphony projection boundary, and explicit out-of-scope list."

**Baseline**: This feature revises and extends `specs/001-durable-work-ledger/` (implemented in `src/bindle/work_ledger.py`, verified by `tests/test_work_ledger.py`). It does **not** reopen or re-litigate 001's settled decisions: SQLite as the persistence format, repository-local/Git-common-directory storage location, INSERT-based claim arbitration, read-only reconciliation, or archival-thins-never-deletes. Every FR/SC below is additive to 001's FR-001–FR-021 and SC-001–SC-010 unless explicitly stated as a revision.

**Terminology note**: This feature's "milestone" is a **work-item type** — a human acceptance unit inside the durable ledger. It is unrelated to `docs/SCOPE.md`'s "M0–M4" **project roadmap milestones** (Workshop, Evidence, Resume, Projection, Derived indexing). The two concepts share an English word and nothing else; this document uses "milestone work item" when the distinction matters.

## User Scenarios & Testing *(mandatory)*

<!--
  This feature's "users" are engineering agents (Claude Code, Codex, and any
  future harness) and the repository maintainer, per 001's own framing —
  not an external product audience.
-->

### User Story 1 - Group tasks under a human-acceptance unit (Priority: P1)

An agent has decomposed an accepted piece of work into several execution-level tasks (as 001 already supports) and needs to additionally record that those tasks together constitute one meaningful implementation outcome a human will accept or reject as a whole — without losing 001's existing per-task durability, claiming, blocking, or evidence behavior.

**Why this priority**: Without a way to group tasks under a unit a human actually reviews, "done" has no connection to acceptance — every other scenario in this feature depends on this grouping existing.

**Independent Test**: Create a milestone work item and two task work items whose `parent_id` names it, end the session, and confirm — from a fresh session — that both tasks' attribution to the milestone is intact and that the milestone and its tasks behave exactly like 001's ordinary work items in every respect 001 already specifies (status, blocking, claims, evidence).

**Acceptance Scenarios**:

1. **Given** no existing work items, **When** an agent creates a work item with `type = 'milestone'`, **Then** the item is created with no `parent_id` and a milestone-appropriate status.
2. **Given** an existing milestone work item, **When** an agent creates a work item with `type = 'task'` and `parent_id` naming the milestone, **Then** the task is created and durably attributed to that milestone.
3. **Given** a task whose `parent_id` names an item that does not exist, or names an item whose `type` is `'task'` rather than `'milestone'`, **When** creation is attempted, **Then** creation is rejected and no row is written.
4. **Given** an item created with `type = 'task'`, **When** anything later attempts to change its `type`, **Then** the model rejects it — `type` is immutable after creation, exactly like 001's `id`.
5. **Given** a milestone that is currently `review`, `accepted`, or `superseded`, **When** an agent attempts to create a task with `parent_id` naming that milestone, **Then** creation is rejected and no row is written — a milestone's child set accepts new members only while the milestone itself is `open` (FR-003a).

---

### User Story 2 - A task reaches "done" without triggering human review (Priority: P1)

An agent completes an execution-level task. Reaching "done" must be a narrow, mechanical fact anyone can verify by inspecting the ledger — it must not, by itself, require or trigger a human semantic judgment.

**Why this priority**: This is what keeps tasks cheap to complete and keeps human attention scoped to milestones rather than every task — the core division of labor this feature introduces.

**Independent Test**: Mark a task done after recording at least one evidence pointer for it, and confirm the ledger can answer, purely by query, whether that task's completion carries qualifying mechanical evidence — without consulting anything outside the ledger and without any human-review fact being read or written.

**Acceptance Scenarios**:

1. **Given** a task with no recorded evidence, **When** an agent marks it done, **Then** the task's status becomes `done` (unchanged from 001's `mark_done` behavior — evidence remains optional per 001 FR-008), and a query for "does this done task carry qualifying mechanical evidence" reports no.
2. **Given** a task with at least one recorded evidence pointer, **When** an agent marks it done, **Then** the same query reports yes.
3. **Given** a done task, **When** anything inspects its status history, **Then** nothing about reaching `done` reads, writes, or requires a review-state fact anywhere in the model.

---

### User Story 3 - A milestone becomes ready for human review, and a human claims it (Priority: P2)

Once every task under a milestone has reached a resolved state (done or superseded) with qualifying evidence, and the milestone itself is not blocked, the milestone is ready for a human to review. A human or agent explicitly moves it into review and may claim it (using the same claim mechanism 001 already provides for tasks) to signal they are the one reviewing it.

**Why this priority**: This is the seam where "mechanical completion" becomes "human acceptance" — the reason milestones exist as a distinct type at all.

**Independent Test**: Construct a milestone with three child tasks; confirm review-readiness is computed as false while any child is unresolved or missing evidence, and becomes true only once every child is resolved with qualifying evidence and the milestone itself is unblocked; then move the milestone into review and claim it, confirming the claim behaves exactly like a task claim (single-winner arbitration, releasable, overridable on staleness).

**Acceptance Scenarios**:

1. **Given** a milestone with two child tasks, one still open, **When** review-readiness is computed, **Then** the answer is no, and which child is outstanding is discoverable.
2. **Given** the same milestone once both children reach `done` with qualifying evidence, **When** review-readiness is computed, **Then** the answer is yes.
3. **Given** a review-ready milestone, **When** an agent moves it into `review` status and then claims it, **Then** the claim is recorded exactly as an ordinary 001 claim (owner, timestamp, optional worktree/branch), independently of the status transition.
4. **Given** a milestone not yet review-ready, **When** an attempt is made to move it into `review` status, **Then** the transition is rejected.

---

### User Story 4 - Review requests changes without rewriting completed task history (Priority: P2)

A human reviewing a milestone decides the delivered work needs changes. The response is new, ordinary corrective tasks under the same milestone — not editing, reopening, or deleting any already-`done` task.

**Why this priority**: Preserves the append-only, evidence-immutable posture 001 already established for individual tasks, extended to the milestone level — rework must never erase what was actually completed and verified.

**Independent Test**: Move a milestone back out of `review` (declining acceptance) and add a new task under it; confirm every previously-`done` sibling task's status, evidence, and identity are completely untouched.

**Acceptance Scenarios**:

1. **Given** a milestone in `review`, **When** a reviewer declines to accept it, **Then** the milestone's status reflects that it is no longer in review (returns to its pre-review open state) and no child task's status or evidence is modified.
2. **Given** a declined milestone, **When** an agent creates a new task with `parent_id` naming it, **Then** the new task is created normally and the milestone's review-readiness is recomputed to include it.
3. **Given** a milestone review outcome (accepted or changes-requested), **When** anyone looks for the *rationale* behind that outcome, **Then** the ledger itself does not claim to hold that rationale — per `docs/DATA-OWNERSHIP.md`, the decision and its reasoning belong in `docs/DECISIONS.md`; the ledger holds only the coarse status transition and, optionally, an evidence pointer referencing where the rationale was recorded.

---

### User Story 5 - Symphony sees tasks, never milestones (Priority: P3)

A future Symphony integration (still not built — out of scope here, per 001's own User Story 4) must never be able to observe a milestone work item as something to dispatch, and must never need to understand blocking, review, or milestone status vocabulary to know a task is safe to run.

**Why this priority**: Lowest priority because no Symphony adapter exists yet (unchanged from 001), but it is the reason the type distinction cannot leak into the one artifact an external coordinator will eventually consume.

**Independent Test**: Generate a projection over a ledger containing a mix of milestones and tasks, some blocked, some claimed; confirm the projection contains only task rows, and that exactly the unblocked/unclaimed/non-terminal tasks are marked eligible — identical in spirit to 001's own User Story 4 Independent Test, now additionally proving milestone exclusion.

**Acceptance Scenarios**:

1. **Given** a ledger containing both milestone and task work items, **When** a coordinator-facing projection is generated, **Then** no milestone work item appears in it, regardless of its status.
2. **Given** a task blocked by an unresolved milestone (a task may declare a dependency on a milestone, e.g. "do not start until this milestone is accepted"), **When** a projection is generated, **Then** that task is not marked eligible, and the milestone that blocks it still never itself appears in the projection.
3. **Given** the same ledger state, **When** a projection is generated twice, **Then** the two projections are equivalent (unchanged from 001 SC-005).

### Edge Cases

- What happens when someone tries to set `parent_id` on a milestone (a milestone naming another milestone as its parent)? Rejected — this feature does not support nested milestones; a milestone's `parent_id` MUST be `NULL`.
- What happens when a task's `parent_id` names an archived milestone? The reference MUST remain resolvable — the milestone's thinned row still carries `id`/`type`/`status`, exactly mirroring how 001's `blocked_by` resolution survives archival. The task's attribution to that milestone is never lost or made ambiguous by the milestone's archival.
- What happens when a milestone is archived while it still has unresolved (non-terminal) children? This is a genuine new precondition 001 did not need: unlike 001's archival (which only ever ran against a single terminal item with no children concept), archiving a milestone MUST be refused while any child is not yet resolved (done or superseded) — silently orphaning live children's attribution is not acceptable.
- What happens to a task's `blocked_by`/dependency edges that name a milestone, once that milestone is archived? Unchanged from 001's existing dependency-resolution rule: the referenced row's `status` still resolves (archival never clears `status`/`superseded_by`), so a task blocked on a since-accepted-and-archived milestone still correctly resolves as unblocked.
- What happens when a `blocked_by`/dependency edge is declared between a task and a milestone (in either direction)? It is permitted — blocking is item-to-item, not type-scoped — but "resolved" for blocking purposes now depends on the referenced item's *type*: a task is resolved when `done` or `superseded`; a milestone is resolved when `accepted` or `superseded`. `review` and the milestone's pre-review open state are **not** resolved states for blocking purposes.
- What happens when someone attempts to mark a task `done` and it is currently claimed by someone else, or attempts to move a milestone into `review` while it is claimed? Claiming and status transitions remain the orthogonal, independent facts 001 already established (FR-004) — a status transition is never blocked or permitted based on claim state, and this feature does not change that.
- What happens when a milestone has zero children at the moment its review-readiness is computed? It is **not** review-ready — "required child work complete" cannot be vacuously true over an empty set for a unit whose entire purpose is grouping completed child work; a milestone must have at least one resolved child to be review-ready.
- What happens when two agents concurrently attempt to move the same milestone into `review`? The status-transition guard (a conditional `UPDATE ... WHERE status = 'open'`, mirroring 001's existing `mark_done`/`mark_superseded` pattern) guarantees at most one succeeds; the other observes zero rows affected and MUST NOT assume its transition took effect.
- What happens when a milestone is declined from `review` and its readiness was only true because of children that have since been superseded rather than done — does re-review require them to be genuinely `done`? No new rule beyond User Story 3's readiness definition: superseded children continue to count as resolved for readiness, exactly as they do for blocking (001's existing precedent that superseded counts as resolved-for-dependency-purposes carries over unchanged).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The model MUST classify every work item with a `type` of exactly `task` or `milestone`, assigned at creation and immutable thereafter.
- **FR-002**: The model MUST allow a `task` work item to record a `parent_id` naming exactly one `milestone` work item ("its milestone"), or no `parent_id` at all (an unattributed task). A `milestone` work item's `parent_id` MUST always be absent — nested milestones are out of scope for this feature.
- **FR-003**: Creating a `task` with a `parent_id` MUST reject the creation outright (no partial row written) if the named item does not exist or is not itself of `type = 'milestone'`.
- **FR-003a**: A task MUST be attachable to a milestone (via `parent_id` at creation) only while that milestone's `status` is `open`. Creating a task whose `parent_id` names a milestone that is currently `review`, `accepted`, or `superseded` MUST reject the creation outright (no partial row written), exactly like FR-003's existing type/existence checks. This preserves the corrective-work flow a decline already enables (`review` → `decline_review` → `open` → attach a corrective task → `review` again, FR-011) while preventing a milestone's reviewed child set from changing underneath, or after, an `accepted`/`superseded` determination. The parent's existence/type/status check and the task's creation MUST be atomic with respect to a concurrent milestone lifecycle transition — a separate pre-check followed by a later, separate creation would leave a race window in which the milestone's status could change in between, the same class of check-then-act race FR-010 already closes for `mark_in_review`.
- **FR-004**: The model MUST allow a `task` and a `milestone` work item to coexist in the same canonical table and be enumerated, queried, and read back through the same operations 001 already defines for a plain work item, except where this feature explicitly states a difference.
- **FR-005**: The model MUST validate `status` against a vocabulary that depends on the item's `type`, never against one flat vocabulary shared unconditionally by both types:
  - `type = 'task'`: `open`, `done`, `superseded` — **unchanged from 001's existing FR-005**. No `in_progress` or similar value is introduced for tasks (see Assumptions for why).
  - `type = 'milestone'`: `open`, `review`, `accepted`, `superseded`. `accepted` is the milestone's terminal-success state, playing the same role `done` plays for a task. No `planned`/`active` distinction is introduced for milestones (see Assumptions for why).
- **FR-006**: The model MUST define "resolved" for dependency/blocking purposes as type-dependent: a referenced `task` is resolved when its status is `done` or `superseded`; a referenced `milestone` is resolved when its status is `accepted` or `superseded`. This generalizes, and does not narrow, 001's existing FR-006/FR-020/FR-021 dependency-resolution guarantees (including resolution after archival).
- **FR-007**: The model MUST allow a dependency/blocking declaration between any two work items regardless of their respective types (task-on-task, task-on-milestone, milestone-on-task, milestone-on-milestone), using the same declared-edge mechanism 001 already defines. This feature does not introduce type-scoped blocking rules.
- **FR-008**: The model MUST make it possible to compute, purely by query and without any stored flag, whether a given `done` task carries "qualifying mechanical evidence" — defined as at least one recorded evidence pointer (of any kind 001 already defines: `branch`, `commit`, `pull_request`, `other`) attached to that task. This is a read-only derived predicate; it does not gate or change 001's existing `mark_done` behavior (evidence remains optional to record, per 001 FR-008).
- **FR-009**: The model MUST make it possible to compute, purely by query and without any stored flag, whether a `milestone` work item is "review-ready" — true if and only if: (a) the milestone itself is not currently blocked (FR-006/FR-007 above); (b) the milestone has at least one child task; and (c) every child task (`parent_id` naming it) is either `superseded`, or `done` with qualifying mechanical evidence (FR-008). Review-readiness MUST NOT be stored as a column — it is derived fresh, exactly mirroring 001's existing "Available to start" derivation for tasks.
- **FR-010**: The model MUST only permit a milestone's transition into `review` status when it is currently `open` and review-ready (FR-009) at the moment of transition, using a single guarded, atomic conditional update (mirroring 001's existing `mark_done`/`mark_superseded` guard pattern) so that concurrent attempts by different actors resolve to exactly one success, consistent with 001's existing single-winner-transition precedent.
- **FR-011**: The model MUST allow a milestone in `review` to be moved back to `open` ("changes requested") without modifying any child task's status, evidence, or identity, and without deleting the milestone's own record.
- **FR-012**: The model MUST allow a milestone in `review` to be moved to `accepted` (terminal), following the same guarded-transition and superseded-by-pairing conventions 001 already applies to `done`/`superseded` on a task.
- **FR-013**: The model MUST allow the existing claim mechanism (001 FR-007/FR-018/FR-019) to be used, unmodified, against a milestone work item exactly as it is used against a task — "a human is actively reviewing this milestone" is represented by claiming it, not by a new stored fact.
- **FR-014**: The model MUST NOT store a milestone's review acceptance/rejection rationale — per `docs/DATA-OWNERSHIP.md`'s routing rules, that rationale belongs in `docs/DECISIONS.md` (or another owning durable record). The ledger MAY record an evidence pointer (kind `other`) referencing where that rationale lives, exactly as 001 already allows for a claim-override note; it MUST NOT be required to reproduce the rationale itself.
- **FR-015**: The model MUST refuse to archive a milestone work item (extending 001's existing archival operation) while any of its child tasks has a status other than `done`, `accepted`, or `superseded` — archival of a milestone with unresolved children is rejected outright, not silently allowed to orphan live children's attribution. This precondition and the archival mutation itself MUST be atomic with respect to a concurrent writer: a separate pre-check followed by a later, separate archival mutation would leave a race window in which an unresolved child could be added (or a resolved one reopened) in between, the same class of check-then-act race FR-010 already closes for `mark_in_review`.
- **FR-016**: When a milestone work item is archived (all children resolved, per FR-015), the model MUST preserve `parent_id` resolvability for every child exactly as 001 already preserves `blocked_by` resolvability across archival: the milestone's thinned row retains `id`, `type`, `status`, and `superseded_by` permanently, so a child's `parent_id` reference never becomes dangling or ambiguous.
- **FR-017**: A coordinator-facing projection (001 FR-013/FR-014) MUST include only `task` work items. No `milestone` work item MUST ever appear in a generated projection, regardless of its status, claim, or blocking state.
- **FR-017a**: 001's "Available to start" query (`list_available_work_items()`) MUST include only `task` work items, for the same reason as FR-017: a milestone is a human acceptance unit, not an executable/startable unit of work (see Key Entities → Milestone), so an `open`, unclaimed, unblocked milestone MUST NOT be reported as available to start.
- **FR-018**: The model MUST NOT require or introduce any transition-validating state machine, workflow engine, or trigger-enforced sequencing beyond the single-row `CHECK` constraints and guarded conditional updates already used throughout 001 and extended by FR-010/FR-012 above.
- **FR-019**: The model MUST NOT introduce a `priority` field, a `branch_name` field on `work_items` itself, or any stored `dispatchable`/`review_ready`/`blocked`/`eligible`-shaped column — all such facts remain derived by query (FR-006, FR-008, FR-009), consistent with 001's existing "Derived facts" precedent and FR-015 (scheduling-priority prohibition).

### Key Entities *(include if feature involves data)*

- **Work Item** *(revised from 001)*: Now additionally carries a `type` (`task` | `milestone`, immutable) and an optional `parent_id` (a task's owning milestone; always absent for a milestone). Its `status` vocabulary is now type-dependent (FR-005) rather than one shared vocabulary. Every other 001 property (stable identifier, source pointer, evidence, claim, `superseded_by`) is unchanged and applies identically to both types.
- **Milestone**: A `type = 'milestone'` Work Item representing a human acceptance unit — a meaningful implementation outcome grouping one or more child tasks. Reaches `review` only when review-ready (FR-009), and `accepted` only from `review`. Never itself a Symphony-facing projected item (FR-017).
- **Task**: A `type = 'task'` Work Item representing an execution unit — behaviorally identical to every 001 work item, optionally attributed to one milestone via `parent_id`. Reaching `done` remains exactly as narrow and human-review-free as 001 already specified.
- **Review Readiness**: A derived fact about a milestone (FR-009), never stored — analogous to 001's "Available to start" derived fact for tasks.
- **Qualifying Mechanical Evidence**: A derived fact about a `done` task (FR-008), never stored — the minimum mechanical bar a task's completion must clear to count toward its milestone's review-readiness.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In constructed scenarios with a mix of milestone and task work items, every operation 001 already specifies (create, read, list, claim, release, evidence, reconcile, archive-a-task) behaves identically whether performed against a `task` or against a `milestone`, except for the differences this feature explicitly states — verified by exercising 001's existing acceptance scenarios against both types.
- **SC-002**: In constructed scenarios covering a milestone with 1, 2, and 5+ child tasks in every combination of resolved/unresolved and evidenced/unevidenced states, review-readiness (FR-009) matches the expected boolean in 100% of cases.
- **SC-003**: In constructed scenarios where two or more concurrent attempts target the same milestone's transition into `review`, exactly one succeeds every time, mirroring 001 SC-004a's task-claim guarantee.
- **SC-004**: A milestone declined from `review` and given a new corrective task never causes any previously-`done` sibling task's status, evidence rows, or identity to change, verified by comparing before/after snapshots of every sibling task's full record.
- **SC-005**: A coordinator-facing projection generated over a ledger containing both types never includes a milestone row, in 100% of constructed test scenarios, including scenarios where the milestone is `accepted` or otherwise appears "done-like."
- **SC-006**: Archiving a milestone with at least one unresolved child fails in 100% of constructed test scenarios, and the milestone's row is left completely unmodified by the failed attempt.
- **SC-007**: After a milestone is archived (all children resolved), every child's `parent_id` still resolves to a `type`/`status` for that milestone, in 100% of constructed test scenarios, mirroring 001 SC-008's archived-dependency guarantee.
- **SC-008**: No requirement in this specification requires computing a dispatch order, retry count, concurrency limit, or milestone ordering/priority among work items — confirmed by review, extending 001 SC-006 to cover milestones.

## Assumptions

- **`in_progress` is deliberately not introduced for tasks.** An independent lifecycle critique of this feature's draft found that a task status meaning "someone is actively working this" would restate 001's existing Claim fact (an item is already distinguishable as open-and-unclaimed vs. open-and-claimed) under a new name, which 001's own FR-004/FR-005 forbid (claiming must remain a fact orthogonal to status, not folded into it). The user's original request offered `open -> in_progress -> done` as an illustrative sketch, explicitly inviting reconciliation against the existing lifecycle rather than adoption verbatim; this spec resolves that reconciliation by keeping task status exactly as 001 defined it.
- **`planned`/`active` are deliberately collapsed into a single milestone `open` state.** The same orthogonality argument applies: "planned" vs. "active" would only be distinguishable by whether child tasks exist or have been claimed/started — a fact already fully derivable from the children themselves (FR-009's own readiness computation) without a separate stored milestone status. The genuinely new, non-derivable, explicit-human-act states are `review` and `accepted`; `open` covers everything before a milestone is explicitly moved into review, mirroring how `open` already covers a task from creation until it is explicitly marked done. This is a deliberate deviation from the user's illustrative `planned -> active -> review -> accepted` sketch; flagged here for explicit sign-off since it changes the vocabulary the user proposed, not just its justification.
- **`work_item_blocked_by` is not renamed to `work_item_dependencies`.** The user's request itself treated this rename as conditional ("if the rename is adopted"). A normalization critique found it to be a pure relabeling with identical semantics; renaming a stable, fully-tested, already-implemented table for a cosmetic reason contradicts this repository's own "inherit first, extend second, replace deliberately" tooling precedence (`AGENTS.md`) and would touch every reference across `src/bindle/work_ledger.py` and `tests/test_work_ledger.py` for zero behavioral gain. This feature only adds columns to `work_items`; the existing blocking table's name and shape are unchanged.
- **Symphony-facing field renaming (e.g., `eligible` → `dispatchable`) is deferred, not applied to `ProjectedWorkItem` now.** 001's `generate_projection()` is deliberately coordinator-agnostic in its field naming; this feature's only change to it is filtering to `type = 'task'` (FR-017). A future Symphony-adapter-specific translation layer — mapping `eligible` to whatever field name a real adapter needs — remains future work, consistent with 001's own scope boundary (no Symphony adapter implementation here) and this feature's own out-of-scope list.
- **A task may be created without a `parent_id`** (unattributed to any milestone), exactly as 001's work items exist today with no grouping concept at all — this feature adds milestone attribution as optional, not mandatory, so 001's existing single-type usage pattern continues to work unchanged.
- **A milestone must have at least one child task to ever become review-ready** (Edge Cases) — an empty milestone has nothing for a human to accept.
- This specification does not require, assume, or preclude any particular number of milestones, tasks per milestone, or nesting depth beyond the explicit one-level (task → milestone, no milestone → milestone) restriction in FR-002.
