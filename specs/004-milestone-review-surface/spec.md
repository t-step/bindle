# Feature Specification: Milestone Review Surface

**Feature Branch**: `spec/milestone-review-surface`

**Created**: 2026-08-27

**Status**: Draft

**Input**: User description: "Give a human reviewer the ability to see, for a milestone work item, whether it is mechanically ready for review, inspect the durable execution evidence (child task statuses, blocking, evidence pointers) that led there, and record an explicit accept-or-decline decision -- built entirely as a CLI/query presentation surface over the milestone review lifecycle already implemented in specs/002-milestone-task-work-items. This feature adds no new persisted lifecycle state, no new ledger table, and no new milestone status."

**Baseline**: This feature builds on `specs/001-durable-work-ledger/` and `specs/002-milestone-task-work-items/` (both implemented in `src/bindle/work_ledger.py`, verified by `tests/test_work_ledger.py`, adopted in `docs/DECISIONS.md` D038) and sits alongside `specs/003-symphony-task-integration/` (`docs/DECISIONS.md` D039/D040) without modifying it. It does **not** reopen any settled decision from those three features: SQLite as the persistence format, the `type`/`parent_id` milestone/task split, review-readiness as a derived (never stored) fact, `mark_in_review`/`decline_review`/`accept_milestone`'s existing guarded-transition semantics, or the Symphony-facing published projection's task-only shape. **002 already fully implements and tests the milestone review lifecycle itself** — `is_review_ready()`, `mark_in_review()`, `decline_review()`, `accept_milestone()`, `has_qualifying_evidence()` — this feature adds no new lifecycle behavior there. What 002 and 003 do not provide, and this feature adds, is a **human-facing way to reach that lifecycle**: every one of those methods is reachable today only through direct `WorkLedger` library access (confirmed by `specs/003-symphony-task-integration/contracts/task-write-surface.md`'s own "What this contract does not do": *"It does not add evidence recording, milestone review transitions, or any lifecycle transition beyond claim/release/complete... those remain reachable only through the existing internal `WorkLedger` API for a caller with library access, not through this external surface."*) — there is no `bindle` CLI command for any of them, and no way to read back an evidence pointer or a claim's details once recorded (only existence: `has_qualifying_evidence()`, `is_claimed()`).

## User Scenarios & Testing *(mandatory)*

<!--
  This feature's "users" are the repository maintainer, acting as the human
  reviewer of a milestone's grouped, completed work — not an external
  product audience, per 001/002's own framing. Symphony and execution
  agents are explicitly *not* users of this surface (User Story 5).
-->

### User Story 1 - See whether a milestone is ready for review, and why (Priority: P1)

A maintainer wants to know, for a specific milestone, whether it is mechanically ready for human review, and if not, exactly what is outstanding — without opening a SQLite client or reading `work_ledger.py`.

**Why this priority**: Every other story in this feature depends on a human first being able to see this. Without it, `is_review_ready()`'s already-correct boolean is invisible outside library code.

**Independent Test**: Construct a milestone with three child tasks in a mix of states (one `open` with no evidence, one `done` with evidence, one `superseded`); request the milestone's review view; confirm it reports `not ready`, names the specific child preventing readiness (the still-`open`, unevidenced one), and lists every child's id, status, and qualifying-evidence fact correctly. Mark the outstanding child `done` and record evidence for it; request the view again; confirm it now reports `ready`.

**Acceptance Scenarios**:

1. **Given** a milestone with at least one child not yet resolved, or resolved but not evidenced, **When** a maintainer requests its review view, **Then** the view reports `not ready` and identifies which child(ren) are outstanding, without requiring the maintainer to already know which children exist.
2. **Given** a milestone whose children are all resolved-or-evidenced per 002 FR-009, and which is itself unblocked, **When** a maintainer requests its review view, **Then** the view reports `ready`.
3. **Given** a milestone with zero children, **When** a maintainer requests its review view, **Then** the view reports `not ready` and states the reason is "no children" (mirrors 002's Edge Cases: an empty milestone is never review-ready).
4. **Given** a milestone that is itself blocked by an unresolved dependency, **When** a maintainer requests its review view, **Then** the view reports `not ready` and identifies the blocking dependency, even if every child is individually resolved and evidenced.
5. **Given** an id that does not exist, or that resolves to a `task` rather than a `milestone`, **When** a maintainer requests a review view for it, **Then** the request is rejected with a distinct, unambiguous result — never a partial or misleading report.

---

### User Story 2 - Inspect the durable evidence behind a resolved child task (Priority: P1)

Beyond "ready: yes/no," a reviewer needs to see *what backs* that readiness — every recorded evidence pointer for each child task, and each child's own blocking/claim state — because "the ledger says ready" is not itself the reviewer's judgment; the reviewer needs the underlying mechanical facts to form that judgment.

**Why this priority**: This is the "present enough durable execution evidence/state" half of the feature; without it, the review view degenerates into a bare boolean the reviewer has to trust blindly, which 001/002 explicitly never asked a human to do.

**Independent Test**: Record two evidence pointers of different kinds (e.g. one `commit`, one `pull_request`) against a child task, mark it done, and confirm the milestone's review view lists both pointers for that child with their kind, value, recorded time, and optional note intact and unmodified from what was recorded — and confirms a sibling child with zero evidence pointers is reported as carrying none.

**Acceptance Scenarios**:

1. **Given** a child task with one or more recorded evidence pointers, **When** the milestone's review view is requested, **Then** every pointer for that child is listed with its kind, value, recorded timestamp, and note (if any), matching exactly what `add_evidence()` recorded.
2. **Given** a child task with no recorded evidence pointers, **When** the milestone's review view is requested, **Then** that child is reported as carrying none — not silently omitted from the view.
3. **Given** a child task currently blocked by an unresolved dependency, **When** the milestone's review view is requested, **Then** that child's blocked state is reported alongside its status and evidence.
4. **Given** the milestone itself (not a child) has a current claim, **When** the milestone's review view is requested, **Then** the claim's owner and claimed-at time are reported, distinguishing "someone is reviewing this" from the milestone's status.

---

### User Story 3 - Move a milestone into review and claim it (Priority: P2)

Once a milestone's review view reports `ready`, a human explicitly moves it into `review` status and claims it, signaling who is doing the reviewing — using the CLI, not library code.

**Why this priority**: This is the first mutation this feature adds; it depends on User Story 1 existing (a human needs to see readiness before acting on it) but is lower priority than the two read-only stories because a maintainer with library access already has a (harder) way to do this today.

**Independent Test**: Move a ready milestone into review via the CLI and claim it as a named reviewer; confirm the milestone's status is `review` and its claim reports that reviewer, exactly as 002's own `mark_in_review()`/`claim()` acceptance scenarios already establish — this feature adds no new arbitration, only a CLI path to the existing one.

**Acceptance Scenarios**:

1. **Given** a review-ready milestone, **When** a maintainer invokes the CLI to move it into review, **Then** the milestone's status becomes `review`.
2. **Given** a milestone that is not review-ready (or not a milestone, or claimed by someone else's transition attempt concurrently — 002's existing guarantees), **When** the same CLI command is invoked, **Then** the transition is rejected with a reason drawn from the same diagnostic User Story 1's view already computes — no separate, inconsistent explanation.
3. **Given** a milestone now in `review`, **When** a maintainer invokes the CLI to claim it under their own name, **Then** the claim succeeds exactly as an ordinary 002 milestone claim would, and a concurrent claim attempt by someone else fails with the existing "already claimed" result.
4. **Given** an id that resolves to a `task`, **When** any command from this story is invoked against it, **Then** it is rejected with a distinct result — the mirror image of `specs/003-symphony-task-integration`'s existing "milestones are categorically rejected" guard on the task-facing write surface (`contracts/task-write-surface.md`).

---

### User Story 4 - Accept or decline a milestone, recording where the rationale lives (Priority: P2)

Having reviewed the evidence (User Story 2), the reviewer records their decision: accept the milestone as delivered, or decline it back to `open` so corrective tasks can be added — optionally pointing at where they wrote down *why*, since the ledger itself never stores that rationale (002 FR-014).

**Why this priority**: This is the actual human-judgment seam the whole feature exists for — the point where mechanical readiness becomes a recorded human decision — but it depends on Stories 1–3 already existing to be reachable at all.

**Independent Test**: Decline a milestone in review via the CLI with a rationale pointer (e.g. a `docs/DECISIONS.md` anchor); confirm the milestone returns to `open`, every child task's status/evidence/identity is byte-identical to before (002 SC-004), and the rationale pointer is recorded as an evidence pointer on the milestone itself. Separately, accept a different ready-and-in-review milestone via the CLI; confirm its status becomes `accepted` and no child is touched.

**Acceptance Scenarios**:

1. **Given** a milestone in `review`, **When** a maintainer invokes the CLI to accept it, **Then** its status becomes `accepted`, and no child task's status, evidence, or identity changes.
2. **Given** a milestone in `review`, **When** a maintainer invokes the CLI to decline it, optionally supplying a rationale locator, **Then** its status returns to `open`, no child task's status, evidence, or identity changes, and — only if a locator was supplied — an evidence pointer (`kind = other`) referencing that locator is recorded against the milestone.
3. **Given** a milestone not currently in `review`, **When** either the accept or decline CLI command is invoked, **Then** the transition is rejected, and — for decline specifically — no evidence pointer is recorded for a rationale that would describe a decision that did not actually happen.
4. **Given** an accept or decline attempt by an actor who does not currently hold the milestone's claim, **When** the command is invoked, **Then** it still succeeds — claiming and transitioning remain the orthogonal facts 002 already established (its Edge Cases); this feature does not add a "must be claimed to decide" precondition that does not exist in the underlying model.
5. **Given** a declined milestone, **When** a maintainer subsequently attaches a new corrective task to it (via the existing, unmodified `work_ledger` creation path — not part of this feature's write surface), **Then** the milestone's review view (User Story 1) recomputes readiness to include it, with no action from this feature required.
6. **Given** a milestone in `review` and a rationale locator supplied, **When** the status transition (accept or decline) succeeds but the subsequent rationale-locator recording fails, **Then** the status transition remains committed (the milestone's status reflects the decision), the failure is reported distinctly from a rejected transition, and the maintainer is not directed to re-invoke accept/decline to fix it — only to record the rationale locator separately afterward.

---

### User Story 5 - Neither surface can perform the other's mutation (Priority: P3)

An execution agent (or Symphony itself) that only ever acts through the existing task-facing write surface has no command available to it that would accept, decline, or advance a milestone; a human operating only through this feature's review surface has no command available that would mark a task done or otherwise mutate task-only state. This is a structural property of what each surface exposes, not an identity or authorization boundary — see the Assumptions section below for the precise scope of this guarantee.

**Why this priority**: Lowest priority because it is a property of the two surfaces' construction, not new behavior a user directly invokes — but it is the concrete answer to "acceptance cannot accidentally be performed by Symphony or an execution agent."

**Independent Test**: Attempt every command this feature adds against a `task` id and confirm each is rejected with a distinct, non-`task`-shaped result; separately, confirm (unchanged, already true today per D039) that `bindle work claim/release/done` still reject a `milestone` id exactly as before — this feature changes nothing about that existing guard.

**Acceptance Scenarios**:

1. **Given** a `task` work item's id, **When** any command this feature adds (review view, enter-review, claim, release, accept, decline) is invoked against it, **Then** it is rejected with a result naming the id as not-a-milestone, and no ledger state changes.
2. **Given** a `milestone` work item's id, **When** `bindle work claim`, `bindle work release`, or `bindle work done` is invoked against it, **Then** it is rejected exactly as `specs/003-symphony-task-integration` already specifies — unchanged by this feature.
3. **Given** Symphony's published projection (`specs/003-symphony-task-integration/contracts/symphony-projection-v1.md`), **When** Symphony reads it to discover ids to act on, **Then** it never observes a milestone id at all — the primary protection here is that a milestone id is structurally never surfaced to Symphony in the first place (unchanged, existing D039 guarantee); this feature's own type-check guard (Scenario 1) is a second, independent layer for a human or script using this surface directly, not the sole protection.

### Edge Cases

- What happens when the review view is requested for a milestone that has already been `accepted` or `superseded`? It is reported exactly as any other status — the view is a read-only report of current state at any point in the lifecycle, not gated to only `open`/`review` milestones; a reviewer or auditor may legitimately want to re-inspect an already-decided milestone's evidence later.
- What happens when a child task is archived (per 002 FR-015a, only possible once the parent milestone reaches `accepted`/`superseded`) — does the review view still show it? The child's row is thinned by archival (title/description/evidence/claim cleared, per 001's existing archival behavior) exactly as 001/002 already define; the review view reports whatever `get_work_item`/evidence-read currently returns for that id, which after archival is a thinned row with no evidence — this feature does not special-case archived children or attempt to reconstruct discarded evidence, consistent with 001's own "archival discards, never a `bindle` feature backfills it" posture.
- What happens when two maintainers request the review view concurrently while a third is mid-transition (`enter-review`/`accept`/`decline`)? The view is a set of independent read-only queries with no cross-query locking, mirroring how `is_review_ready()` itself already works today (002 data-model.md) — a view may reflect a state that changes microseconds later; this is the same staleness-tolerant read model 001/002 already accept for every other derived fact (e.g. "Available to start"), not a new consistency guarantee this feature must invent.
- What happens when `enter-review` is attempted and readiness was true at request time but changes before the guarded `UPDATE` commits? Unchanged from 002: the guard is embedded in the same atomic statement (`_review_ready_sql`), so the CLI command either succeeds against the state at commit time or fails cleanly — this feature adds no separate check-then-act step of its own around the existing guarded transition.
- What happens if `accept`/`decline` is invoked against a milestone that was already accepted or declined by a concurrent caller a moment earlier? The existing guarded-`UPDATE` semantics (002 FR-010/FR-012, mirrored by decline) mean the second caller's transition affects zero rows; this feature's CLI wrapper reports that as a rejection with a reason, not a crash or an ambiguous success.
- What happens to a rationale locator recorded on a declined milestone if the milestone is later reviewed again and declined a second time? Each decline that supplies a locator records a new, additional evidence pointer (append-only, per 001's existing evidence model) — the full history of rationale locators across multiple review rounds remains readable via User Story 2's evidence listing, never overwritten.
- What happens when `--evidence`/`--note` is supplied to `accept` rather than `decline`? Permitted identically — a reviewer may equally want to point at where an acceptance's rationale lives, not only a decline's; the mechanism (an evidence pointer on the milestone, `kind = other`) does not distinguish which transition it followed.
- What happens when the status transition (accept/decline) succeeds but the subsequent, separately committed rationale-locator recording then fails (e.g. a storage error on the `add_evidence()` call)? Per FR-010a, the transition stands — it is not rolled back or retried — and the failure is surfaced distinctly from a transition rejection, so the caller can tell the decision was recorded even though the locator was not; the caller reconciles the rationale locator separately (e.g. a direct `add_evidence()` call) rather than re-invoking accept/decline, which would either no-op (the milestone has already left `review`) or misread as a second attempt at the decision itself.
- What happens if the review view is requested against a repository whose ledger schema predates 002 (schema version 1, no `type` column)? `connect()`'s existing migration (`_migrate_v1_to_v2`) already runs automatically on connect for every 001/002 operation; this feature calls the same `connect()` path and requires no migration behavior of its own.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a read-only operation that, given a work item id, reports whether it is a milestone and, if so: its current status, its review-readiness (002 FR-009's exact derived fact, computed fresh — never a stored value read back), and every child task's id, title, status, and qualifying-evidence fact (002 FR-008).
- **FR-002**: When a milestone is not review-ready, the operation in FR-001 MUST report which of 002 FR-009's three conditions is unmet: the milestone itself is blocked; the milestone has no children; or naming which specific child(ren) fail the resolved-or-evidenced bar. It MUST NOT introduce a new readiness predicate beyond the one 002 FR-009 already defines — this is a presentation of the same three conditions, not a new computation.
- **FR-003**: The system MUST make it possible to read back, for any work item, every evidence pointer recorded against it — kind, value, recorded time, and note — individually, not merely whether at least one exists (002's `has_qualifying_evidence()` remains the existence check it already is; this is an additive read path over the same, unchanged `work_item_evidence` table, adding no column and no new table).
- **FR-004**: The system MUST make it possible to read back a work item's current claim, if any — owner and claimed-at time — individually, not merely whether one exists (`is_claimed()`'s existing boolean is unchanged; this is an additive read path over the same, unchanged `work_item_claims` table).
- **FR-005**: The review operation (FR-001) MUST report each child task's current blocked state (002's type-aware blocking resolution, unchanged) alongside its status and evidence.
- **FR-006**: The review operation (FR-001) MUST report the milestone's own claim (FR-004), if any, distinguishing "someone is reviewing this" from the milestone's `status`.
- **FR-007**: The system MUST provide a way to enumerate milestone work items and, for each, its status and review-readiness (FR-001's per-milestone computation, applied across every milestone) — so a reviewer can discover which milestones exist and which are ready without already knowing an id.
- **FR-008**: The system MUST provide operations, each a thin wrapper delegating directly to the corresponding existing, already-atomic `WorkLedger` method with no new arbitration mechanism, for a human to: move a milestone from `open` to `review` (`mark_in_review()`); claim a milestone (`claim()`); release a milestone claim (`release_claim()`); decline a milestone from `review` back to `open`, optionally recording a rationale-locator evidence pointer (`decline_review()`, then `add_evidence()` only on success); and accept a milestone from `review` (`accept_milestone()`, then optionally `add_evidence()` only on success).
- **FR-009**: Every operation in FR-008, and the per-milestone read in FR-001, MUST reject an id that does not exist or does not resolve to `type = 'milestone'`, with a result distinguishable from every other rejection reason (not-found vs. not-a-milestone vs. the operation's own existing failure modes such as "not review-ready" or "not currently in review") — the mirror image of `specs/003-symphony-task-integration/contracts/task-write-surface.md`'s existing categorical milestone rejection on the task-facing write surface.
- **FR-010**: The rationale-locator evidence pointer optionally recorded by decline or accept (FR-008) MUST be recorded only after the underlying status transition itself has succeeded — a rejected transition MUST leave no evidence pointer describing a decision that did not occur.
- **FR-010a**: The status transition (`accept_milestone()`/`decline_review()`) and the rationale-locator recording (`add_evidence()`) are two separately committed operations, not one atomic unit. If the transition succeeds and the subsequent rationale-locator recording then fails, the system MUST leave the transition committed (it MUST NOT be rolled back or retried on the caller's behalf), MUST report the rationale-recording failure distinctly from a transition rejection (not conflated with `not_in_review`/`not_found`/`not_a_milestone`), and MUST NOT be re-invoked against the same decision merely to retry the rationale recording — a failed rationale locator is reconciled separately afterward. The "exactly one evidence pointer is recorded" guarantee (`contracts/milestone-review-surface.md`) holds only for the case where both the transition and the rationale-locator recording succeed.
- **FR-011**: The system MUST NOT require a milestone to be claimed by the calling actor as a precondition for `enter-review`, `accept`, or `decline` — claiming and status transitions remain the orthogonal facts 002 already established (FR-004/002's Edge Cases); this feature does not introduce a new "must be claimed to act" gate.
- **FR-012**: The system MUST NOT modify `specs/001` or `specs/002`'s schema, add a column, add a table, add a milestone status value, or persist review-readiness or any other currently-derived fact as a stored value. FR-003/FR-004's new read paths query the existing `work_item_evidence`/`work_item_claims` tables exactly as they exist today.
- **FR-013**: The system MUST NOT modify `specs/003-symphony-task-integration`'s published projection, its schema, its `dispatchable` computation, or the existing task-facing write surface (`bindle work claim/release/done`) in any way — this feature adds an entirely separate, human-facing surface alongside it.
- **FR-014**: The system MUST NOT introduce an automatic, inferred, or LLM-based acceptance judgment of any kind — every accept or decline in FR-008 is an explicit action naming a specific milestone, taken by a human (or a script acting on a human's explicit behalf), never derived from readiness, evidence content, or any other mechanical fact.

### Key Entities *(include if feature involves data)*

- **Milestone Review View**: A read-only, computed-on-request report (FR-001–FR-002, FR-005–FR-006) over a single milestone's existing ledger state. Not a new entity in storage — no row, no cache, nothing persisted; recomputed fresh on every request, exactly mirroring 001/002's existing "derived, never stored" precedent for every other computed fact in this ledger (e.g. "Available to start", review-readiness itself).
- **Evidence Pointer (read path)**: The existing `work_item_evidence` row (001 data-model.md), now individually readable back (FR-003) rather than only checkable for existence. No new field, no new kind.
- **Claim (read path)**: The existing `work_item_claims` row (001 data-model.md), now individually readable back (FR-004) rather than only checkable for existence. No new field.
- **Rationale Locator**: An ordinary `kind = 'other'` Evidence Pointer (001's existing vocabulary), recorded against a milestone at accept or decline time (FR-008/FR-010), pointing at wherever the actual rationale is durably recorded (e.g. `docs/DECISIONS.md`, per `docs/DATA-OWNERSHIP.md`'s routing rules and 002 FR-014) — the ledger never stores the rationale text itself as its authoritative form, only a pointer to it, exactly as 002 FR-014 already established for this same case.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In constructed scenarios covering every combination of milestone status (`open`, `review`, `accepted`, `superseded`) and child-resolution state 002's own SC-002 already covers, the review view's reported readiness and per-child evidence facts match the ledger's own existing `is_review_ready()`/`has_qualifying_evidence()` computations in 100% of cases — this feature never disagrees with the lifecycle it presents.
- **SC-002**: In constructed scenarios recording zero, one, and multiple evidence pointers (of every existing `kind`) against a task, reading them back through this feature's new read path reproduces every recorded field (kind, value, recorded time, note) exactly, in 100% of cases.
- **SC-003**: A milestone declined through this feature's CLI, with or without a rationale locator, never changes any previously-`done` sibling task's status, evidence, or identity — verified by comparing before/after snapshots, mirroring 002 SC-004 exactly, now exercised through the CLI rather than only through direct library calls.
- **SC-004**: An accept or decline attempt against a milestone not currently in `review` is rejected in 100% of constructed test scenarios, and in 100% of the decline cases among them, no evidence pointer is recorded as a result of the rejected attempt.
- **SC-005**: In constructed scenarios where two or more concurrent CLI invocations target the same milestone's `enter-review`, `accept`, or `decline` transition, exactly one succeeds every time — inherited unmodified from 002 SC-003, exercised through this feature's CLI wrapper rather than direct library calls.
- **SC-006**: Every command this feature adds, invoked against a `task` id in constructed test scenarios, is rejected with a not-a-milestone result and leaves the task's own row completely unchanged, in 100% of cases.
- **SC-007**: `bindle work claim`, `bindle work release`, and `bindle work done`, invoked against a `milestone` id after this feature is added, continue to reject exactly as `specs/003-symphony-task-integration`'s existing test suite already verifies — unchanged in 100% of that existing suite's cases.
- **SC-008**: No requirement in this specification requires or introduces a new persisted lifecycle state, a new milestone status, a new table, or a new column — confirmed by review of the actual schema before and after implementation.

## Assumptions

- **This feature is a presentation/query and write-wrapper layer, not a data-model feature.** Grounding this feature against the actual repository (not the initial task description's framing) found that the milestone review lifecycle described by that framing — mechanical readiness, an explicit human accept/decline action, protection against agent-performed acceptance — is **already fully implemented and tested** by `specs/002-milestone-task-work-items` (`is_review_ready`, `mark_in_review`, `decline_review`, `accept_milestone`, `has_qualifying_evidence`, all in `src/bindle/work_ledger.py`, all covered by `tests/test_work_ledger.py`). What is genuinely missing is narrower than originally scoped: (1) any CLI/API surface for that lifecycle at all, and (2) the ability to read back an individual evidence pointer or claim's details once recorded (today only existence is queryable). This specification is scoped to exactly that gap, deliberately smaller than a new lifecycle/data-model feature.
- **`bindle work` and the new milestone surface remain two deliberately separate CLI command groups**, not variants of the same subcommands. This is a namespace and API-ownership boundary, not an identity or authorization boundary — nothing in this feature authenticates or authorizes a caller, and neither surface's command grouping stops a human or script that chooses to invoke the other surface's commands directly (via its CLI or via direct `WorkLedger` library access) from doing so. The guarantee this separation actually provides is narrower and structural: `specs/003-symphony-task-integration`'s supported task-facing projection and write surface exposes no operation that mutates a milestone, and this feature's milestone review surface exposes no operation that mutates a task — an execution agent that only ever acts through the surface it is actually given (D039) has no command available to it that would accept, decline, or advance a milestone, and a human using only this feature's surface has no command available that would mark a task done. Each surface's own type-guard (rejecting the other's id, `not_a_milestone`/`not_a_task`) is a second, independent layer of that same structural property, not an authentication or authorization mechanism — mirroring `specs/003`'s own reasoning for rejecting milestones on the task-facing surface (`task-write-surface.md`: "categorically rejected... never silently treated as a task").
- **Accept does not re-verify readiness at the moment of acceptance.** Once a milestone enters `review`, its child set cannot grow (002 FR-003a: a task may attach only while its milestone is `open`) and no already-resolved child's status can regress (001/002 have no "un-mark-done" operation; done/superseded are terminal), and an attributed child cannot be archived while its parent is `open`/`review` (002 FR-015a) — so readiness, once achieved and transitioned into `review`, cannot silently regress before `accept_milestone()` runs. This feature therefore does not add a redundant readiness re-check at accept time; `accept_milestone()`'s existing `status = 'review'` guard is sufficient, exactly as 002's own data-model.md concurrency analysis already establishes.
- **A milestone's review view is available at every lifecycle status, not gated to `open`/`review`.** Auditing an already-`accepted` or `superseded` milestone's evidence later is a legitimate, unprivileged read — this feature does not restrict the view to only "actionable" milestones.
- **This feature does not touch Spec Kit task ingestion, `speckit_loader.py`, or how a milestone work item itself first gets created.** Nothing in the repository's current loader creates milestone work items (003's own scope note: "Milestones remain completely orthogonal to this feature... the loader never creates one") — how a maintainer creates a milestone and attaches tasks to it (today, only through direct library calls) is unchanged and out of scope here; this feature only adds a way to review and decide on a milestone that already exists.
- **No staleness detection for evidence.** Whether a recorded `commit`/`branch`/`pull_request` pointer still resolves to something meaningful (a since-rebased branch, a deleted PR) is unchanged from 001/002's existing posture (evidence is an immutable historical observation, never revalidated) — this feature reads pointers back exactly as recorded, and does not attempt to verify them against Git or GitHub state.

## Non-Goals

- No change to `specs/001` or `specs/002`'s schema, milestone status vocabulary, or lifecycle transitions.
- No change to `specs/003-symphony-task-integration`'s published projection, write surface, or Symphony-facing contracts.
- No automatic, inferred, or LLM-based acceptance judgment.
- No requirement that task completion carry evidence — evidence remains optional to record, exactly as 001 FR-008/002 FR-008 already specify; this feature only makes already-recorded evidence readable.
- No milestone-scheduling, priority, or dispatch-ordering behavior of any kind (unchanged from 001 SC-006/002 SC-008).
- No new persisted "review ready" flag or any other newly-stored derived fact.
- No evidence-staleness detection.
- No change to how or where a milestone work item itself is created, or how tasks are attached to it.
