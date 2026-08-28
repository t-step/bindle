---

description: "Task list for Milestone Review Surface"
---

# Tasks: Milestone Review Surface

**Input**: Design documents from `specs/004-milestone-review-surface/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/milestone-review-surface.md, quickstart.md — all present.

**Tests**: Included. This repository's own convention (`tests/test_work_ledger.py`, `tests/test_speckit_loader.py`, `tests/test_symphony_projection.py`, `tests/test_cli.py` all carry tests for 001–003) makes tests the norm here, not an opt-in; `plan.md`'s Project Structure names the exact three files this feature touches.

**Organization**: Grouped by user story per `spec.md`'s priorities (P1: US1, US2 — read-only; P2: US3, US4 — mutations; P3: US5 — the symmetric-guard property). Two of the five stories (US2, US5) share their underlying implementation with an earlier story by design — see each phase's note.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, or a disjoint region of one already-created file, with no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Every task names its exact file path

## Path Conventions

Single Python package, unchanged from 001–003: `src/bindle/`, `tests/`, both at repository root.

---

## Phase 1: Setup

No new dependency, no new project scaffolding — this feature extends an existing package (`plan.md`'s Technical Context: "None beyond the standard library"). Nothing to do here beyond confirming the environment already used by 001–003 still works.

- [ ] T001 Confirm the existing dev environment runs the current suite cleanly before starting: `bash scripts/check.sh` from the repository root. (No code change; establishes a clean baseline to diff against.)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The two new read accessors and the new module's shared scaffolding — every user story's CLI/library surface calls into these.

**⚠️ CRITICAL**: No user story work may begin until this phase is complete.

- [ ] T002 Add `EvidencePointer` and `ClaimInfo` frozen dataclasses to `src/bindle/work_ledger.py`, placed alongside the existing `WorkItem`/`ReconciliationFinding`/`ProjectedWorkItem`/`ExternalProjectionRow` dataclasses (after `ExternalProjectionRow`), per `data-model.md`'s exact field lists.
- [ ] T003 Add a new `TestEvidenceReadAccessor` test class to `tests/test_work_ledger.py` with failing tests for a not-yet-implemented `list_evidence(work_item_id)`: zero pointers returns `[]`; one pointer of each `kind` round-trips every field (`kind`, `value`, `recorded_at`, `note`); multiple pointers on one item come back ordered oldest-first; a nonexistent `work_item_id` returns `[]` (never raises).
- [ ] T004 Add a new `TestClaimReadAccessor` test class to `tests/test_work_ledger.py` with failing tests for a not-yet-implemented `get_claim(work_item_id)`: unclaimed returns `None`; a claim with `worktree_path`/`branch` set round-trips every field; a claim with `worktree_path`/`branch` left `None` (matching `claim()`'s existing optional-argument shape) round-trips as `None`; a nonexistent `work_item_id` returns `None`.
- [ ] T005 Implement `list_evidence(self, work_item_id: str) -> list[EvidencePointer]` in `src/bindle/work_ledger.py` (`data-model.md`'s query, ordered by `evidence_id`) so T003's tests pass. Depends on: T002, T003.
- [ ] T006 Implement `get_claim(self, work_item_id: str) -> ClaimInfo | None` in `src/bindle/work_ledger.py` (`data-model.md`'s query) so T004's tests pass. Depends on: T002, T004.
- [ ] T007 Create `src/bindle/milestone_review.py`: module docstring (cross-referencing this feature and `symphony_projection.py`'s sibling shape), a shared `_resolve_milestone(ledger, id) -> tuple[WorkItem | None, str | None]` guard helper (returns `(item, None)` when `id` resolves to `type='milestone'`; `(None, 'not_found')` when it doesn't resolve at all; `(None, 'not_a_milestone')` when it resolves to `type='task'` — the single, shared implementation every wrapper function in this module calls first, so the type-guard behavior can never drift between commands), and the small frozen result dataclasses `TransitionResult`, `ClaimResult`, `ReleaseResult` (each `ok: bool`, `reason: str | None`) and `DecisionResult` (`ok: bool`, `reason: str | None`, plus `rationale_error: str | None` — per `data-model.md`'s "Write wrappers" table and its `DecisionResult` definition, spec.md FR-010a).

**Checkpoint**: `list_evidence()`, `get_claim()`, and the module skeleton exist and are tested. User story work can begin.

---

## Phase 3: User Story 1 - See whether a milestone is ready for review, and why (Priority: P1) 🎯 MVP

**Goal**: A human can request a single milestone's status, review-readiness, and (when not ready) exactly what's outstanding, plus discover which milestones exist at all.

**Independent Test**: Per `spec.md` — construct a milestone with three children in mixed states, request the review view, confirm the reported readiness and outstanding-child diagnostic; complete the outstanding child; request again; confirm `ready`.

### Tests for User Story 1

- [ ] T008 [P] [US1] Add `TestReviewMilestone` to `tests/test_milestone_review.py` (new file): not-found rejection; not-a-milestone rejection (a task id); zero-children → not ready, reason `no_children`; milestone itself blocked → not ready, reason `blocked`, reported even when every child is resolved-and-evidenced; a mix of resolved/unresolved/unevidenced children → not ready, outstanding child ids named; every condition resolved → `ready`. Assert `review_ready` always equals a direct `ledger.is_review_ready()` call on the same state (spec.md SC-001) — never a second, possibly-disagreeing computation.
- [ ] T009 [US1] Add `TestListMilestones` to `tests/test_milestone_review.py`: empty ledger → `[]`; a mix of milestones and tasks → only milestones enumerated, each with correct `status`/`review_ready`; ordering matches `list_work_items()`'s own id order. Sequential with T008 — same file, both new classes; run T008 first (it creates the file).
- [ ] T010 [P] [US1] Add `TestMilestoneCliSubcommands` to `tests/test_cli.py` (mirrors `TestWorkCliSubcommands` at `tests/test_cli.py:2523`): `bindle milestone review <id>` for not-found/not-a-milestone/not-ready/ready cases (stderr message shape `bindle milestone review: ...`, exit codes 0/1 per `contracts/milestone-review-surface.md`); `bindle milestone list` and `bindle milestone list --status open --ready-only` filtering. Parallel with T008/T009 — different file.

### Implementation for User Story 1

- [ ] T011 [US1] Implement `review_milestone(ledger, work_item_id) -> ReviewResult` in `src/bindle/milestone_review.py`: use `_resolve_milestone` (T007) for the guard; compose the view from `ledger.is_review_ready()`, `ledger.is_blocked()`, `ledger.list_work_items()` filtered to `parent_id == work_item_id` (children), `ledger.has_qualifying_evidence()`/`ledger.list_evidence()`/`ledger.is_blocked()` per child, and `ledger.get_claim()` for the milestone's own claim — per `research.md`'s "Decision: readiness diagnostic is composed from existing reads" (no new SQL predicate; `review_ready` is `is_review_ready()`'s value, read once, never recomputed independently). Depends on: T005, T006, T007. Makes T008 pass.
- [ ] T012 [US1] Implement `list_milestones(ledger) -> list[MilestoneListEntry]` in `src/bindle/milestone_review.py` (`ledger.list_work_items()` filtered to `type == 'milestone'`, `is_review_ready()` per row, per `research.md`'s "Decision: `bindle milestone list`..."). Depends on: T007. Makes T009 pass.
- [ ] T013 [US1] Add the `milestone` top-level subparser to `build_parser()` in `src/bindle/cli.py`, parallel to the existing `repo`/`skills`/`work` groups (`research.md`'s "Decision: `bindle milestone` as a new top-level command group"), with `review <id>` and `list [--status ...] [--ready-only]` subcommands wired to new `_cmd_milestone_review`/`_cmd_milestone_list` handler functions. Depends on: T011, T012. Makes T010 pass.

**Checkpoint**: A human can run `bindle milestone review <id>` and `bindle milestone list` against a real ledger. US1 is independently functional and testable.

---

## Phase 4: User Story 2 - Inspect the durable evidence behind a resolved child task (Priority: P1)

**Goal**: The review view (US1) carries every child's individual evidence pointers, blocked state, and the milestone's own claim details — not just the readiness boolean.

**Independent Test**: Per `spec.md` — record two differently-`kind`d evidence pointers on a child, confirm both are listed intact on the review view; confirm a sibling with none is reported as carrying none, not omitted.

**Note**: `data-model.md`'s `MilestoneReviewView`/`ChildTaskView` already bundle per-child evidence/blocking and the milestone's own claim into the single structure `review_milestone()` (T011) builds — `spec.md`'s Assumptions explain why this is one function serving two stories, not two competing implementations. This phase therefore adds no new production code beyond T011; it adds the specific test coverage US2's acceptance scenarios require, proving those particular fields (not just the readiness boolean) are present and correct.

### Tests for User Story 2

- [ ] T014 [P] [US2] Extend `TestReviewMilestone` in `tests/test_milestone_review.py`: a child with two evidence pointers of different `kind`s → both appear on that child's `evidence` list with kind/value/recorded_at/note intact; a child with zero pointers → `evidence == []` (present, not omitted) and `has_qualifying_evidence is False`; a child currently blocked by an unresolved dependency → `is_blocked is True` alongside its status/evidence; the milestone's own current claim (owner, claimed_at) is reported and distinguished from `status`.
- [ ] T015 [P] [US2] Extend `TestMilestoneCliSubcommands` in `tests/test_cli.py`: `bindle milestone review <id>` output includes each child's evidence pointers and blocked state, and the milestone's claim line when claimed.

### Implementation for User Story 2

No new implementation task — T011/T013 (Phase 3) already build and expose every field this story's tests exercise. If T014/T015 fail, the fix is a correction to T011's field mapping, not new functionality.

**Checkpoint**: US1 and US2 both independently pass their own tests against the same `review_milestone()`/CLI output.

---

## Phase 5: User Story 3 - Move a milestone into review and claim it (Priority: P2)

**Goal**: A human can transition a ready milestone into `review` and claim it via the CLI, with the same atomicity 002 already guarantees at the library level.

**Independent Test**: Per `spec.md` — move a ready milestone into review and claim it as a named reviewer via the CLI; confirm status and claim; confirm a not-ready or concurrent-loser attempt is rejected with the same diagnostic US1 already computes.

### Tests for User Story 3

- [ ] T016 [P] [US3] Add `TestEnterReviewClaimRelease` to `tests/test_milestone_review.py`: `enter_review()` succeeds only when ready-and-open (reuse T008's ready/not-ready fixtures) and returns `not_ready_or_not_open` otherwise; not-found/not-a-milestone guard on all three functions; `claim_milestone()`/`release_milestone()` delegate correctly (owner recorded, wrong-owner release is a no-op, matching `release_claim()`'s existing safe-release semantics); a concurrent multi-threaded `enter_review()` attempt against one ready milestone resolves to exactly one winner (mirror the existing concurrency test pattern already used for `mark_in_review` in `tests/test_work_ledger.py`, e.g. `test_concurrent_mark_in_review_has_exactly_one_winner`).
- [ ] T017 [P] [US3] Add tests to `TestMilestoneCliSubcommands` in `tests/test_cli.py`: `bindle milestone enter-review <id>`, `bindle milestone claim <id> --owner ... [--worktree ...] [--branch ...]`, `bindle milestone release <id> --owner ...` — success and each rejection reason, exit codes.

### Implementation for User Story 3

- [ ] T018 [US3] Implement `enter_review(ledger, id) -> TransitionResult`, `claim_milestone(ledger, id, owner, worktree_path=None, branch=None) -> ClaimResult`, `release_milestone(ledger, id, owner) -> ReleaseResult` in `src/bindle/milestone_review.py`, each using `_resolve_milestone` (T007) then delegating directly to `ledger.mark_in_review()`/`ledger.claim()`/`ledger.release_claim()` — no new arbitration (`contracts/milestone-review-surface.md`'s "No new arbitration mechanism" guarantee). Depends on: T007. Makes T016 pass.
- [ ] T019 [US3] Wire `enter-review <id>`, `claim <id> --owner ... [--worktree ...] [--branch ...]`, `release <id> --owner ...` subcommands onto the `milestone` subparser in `src/bindle/cli.py` (extending T013's subparser), with `_cmd_milestone_enter_review`/`_cmd_milestone_claim`/`_cmd_milestone_release` handlers following the existing `_cmd_work_claim`/`_cmd_work_release` error-message convention (`bindle milestone <verb>: <reason>` to stderr). Depends on: T013, T018. Makes T017 pass.

**Checkpoint**: A human can move a milestone into review and claim it entirely via the CLI. US1–US3 all independently functional.

---

## Phase 6: User Story 4 - Accept or decline a milestone, recording where the rationale lives (Priority: P2)

**Goal**: A human can accept or decline a milestone in review via the CLI, optionally recording a rationale-locator evidence pointer, with the pointer recorded only when the transition itself actually succeeded.

**Independent Test**: Per `spec.md` — decline a milestone in review with a rationale locator via the CLI; confirm it returns to `open`, every child is byte-identical to before, and the locator is recorded as an evidence pointer on the milestone. Separately, accept a different ready-and-in-review milestone; confirm `accepted` and no child touched.

### Tests for User Story 4

- [ ] T020 [P] [US4] Add `TestAcceptDecline` to `tests/test_milestone_review.py`: `accept()`/`decline()` succeed only from `review` and return `not_in_review` otherwise; not-found/not-a-milestone guard; supplying `evidence_locator` on a successful transition records exactly one `kind='other'` pointer (`value=<locator>`, `note=<note or None>`) on the milestone, verified via T005's `list_evidence()`, and returns `rationale_error is None`; a *rejected* transition (not in review) records **zero** evidence pointers even when `evidence_locator` was supplied (spec.md FR-010); omitting `evidence_locator` on a successful transition records nothing; `accept()`/`decline()` succeed regardless of whether the caller currently holds the milestone's claim (spec.md FR-011); a before/after snapshot of every child's full `WorkItem` record, evidence, and claim is byte-identical across a decline (spec.md SC-003, mirroring 002's own `test_decline_review_leaves_child_records_byte_identical`); a concurrent multi-threaded `accept()` attempt, and separately a concurrent multi-threaded `decline()` attempt, each against one milestone in `review`, each resolve to exactly one winner (spec.md SC-005 names all three transitions — `enter-review`'s own concurrency is T016's; this task is what closes SC-005 for `accept`/`decline`, mirroring `tests/test_work_ledger.py`'s existing `test_accept_milestone_transitions_review_to_accepted`-adjacent concurrency pattern). **Partial-failure case (spec.md FR-010a)**: with the transition set up to succeed and `evidence_locator` supplied, monkeypatch/stub `ledger.add_evidence()` to raise; assert `accept()`/`decline()` does not propagate that exception, `DecisionResult.ok is True` and `reason is None` (the transition committed — assert the milestone's `status` actually changed via `ledger.get_work_item()`), `rationale_error` is not `None` and describes the failure, and no partial/malformed evidence row exists (`list_evidence()` unchanged from before the call).
- [ ] T021 [P] [US4] Add tests to `TestMilestoneCliSubcommands` in `tests/test_cli.py`: `bindle milestone accept <id> [--evidence ...] [--note ...]` and `bindle milestone decline <id> [--evidence ...] [--note ...]` — success, `--note` without `--evidence` is a usage error caught by argument parsing (per `contracts/milestone-review-surface.md`), not-in-review rejection leaves no evidence pointer (assert via a following `bindle milestone review <id>` call). **Partial-failure case**: with `add_evidence()` stubbed to raise (same technique as T020), assert the CLI still exits `0` (the transition succeeded), the milestone's status reflects the transition (assert via a following `bindle milestone review <id>` call), and stderr carries a distinct warning naming the rationale-recording failure separate from the success output (`contracts/milestone-review-surface.md`'s "CLI exit codes").

### Implementation for User Story 4

- [ ] T022 [US4] Implement `accept(ledger, id, evidence_locator=None, note=None) -> DecisionResult` and `decline(ledger, id, evidence_locator=None, note=None) -> DecisionResult` in `src/bindle/milestone_review.py`: `_resolve_milestone` guard, then `ledger.accept_milestone()`/`ledger.decline_review()`; only if that call returns `True` and `evidence_locator` is not `None`, call `ledger.add_evidence(id, kind='other', value=evidence_locator, note=note)` (`research.md`'s "Decision: rationale locator recorded via existing `add_evidence`" — two sequential calls, gated on the first's result, never a shared transaction). Wrap that second call in `try`/`except Exception`: on success, return `DecisionResult(ok=True, reason=None, rationale_error=None)`; on an exception, do **not** propagate it and do **not** treat the transition as failed — return `DecisionResult(ok=True, reason=None, rationale_error=str(exc))` (`research.md`'s "Partial-failure semantics (FR-010a)"; `data-model.md`'s `DecisionResult`). Depends on: T007. Makes T020 pass.
- [ ] T023 [US4] Wire `accept <id> [--evidence <locator>] [--note <text>]` and `decline <id> [--evidence <locator>] [--note <text>]` subcommands onto the `milestone` subparser in `src/bindle/cli.py` (extending T019's subparser; `--note` declared as requiring `--evidence` via argparse's own dependent-argument handling, not a manual post-parse check), with `_cmd_milestone_accept`/`_cmd_milestone_decline` handlers: exit `0` whenever `DecisionResult.ok` is `True`; when `rationale_error` is also set, print the normal success line plus a distinct stderr warning line naming the rationale-recording failure (`contracts/milestone-review-surface.md`'s "CLI exit codes"), never rendered as the command's `bindle milestone <verb>: <reason>` rejection format used for `ok=False`. Depends on: T019, T022. Makes T021 pass.

**Checkpoint**: The full milestone review lifecycle (readiness → evidence → enter-review → claim → accept/decline) is reachable end-to-end via the CLI. US1–US4 all independently functional. This is the feature's complete, coherent scope per `spec.md`.

---

## Phase 7: User Story 5 - Neither surface can perform the other's mutation (Priority: P3)

**Goal**: Demonstrate, adversarially, that every command this feature adds refuses a `task` id, and that this feature changed nothing about `bindle work`'s existing refusal of a `milestone` id.

**Independent Test**: Per `spec.md` — invoke every command this feature adds against a task id; confirm each rejects distinctly. Confirm `bindle work claim/release/done` still reject a milestone id exactly as before.

**Note**: This story requires no new production code — the guard is `_resolve_milestone` (T007), already used by every function built in Phases 3–6. This phase is deliberately pure verification, matching `spec.md`'s own framing: "a property of the two surfaces' construction, not new behavior a user directly invokes."

### Tests for User Story 5

- [ ] T024 [P] [US5] Add `TestMilestoneOnlyGuard` to `tests/test_milestone_review.py`: a single parametrized test invoking `review_milestone`, `list_milestones` (trivially not applicable — skip or assert task ids never appear), `enter_review`, `claim_milestone`, `release_milestone`, `accept`, `decline` against a `type='task'` id, asserting every one returns `not_a_milestone` and leaves the task's own `WorkItem` row, evidence, and claim state completely unchanged.
- [ ] T025 [P] [US5] Add `TestMilestoneCommandsRejectTasks` to `tests/test_cli.py`: the CLI-level mirror of T024 — every `bindle milestone <verb>` invoked against a task id, exit code 1, `not a milestone` in stderr, no ledger state change. Also runs (unmodified) the existing `TestWorkCliSubcommands` milestone-rejection cases and confirms they still pass, demonstrating `bindle work claim/release/done`'s existing guard is untouched by this feature (spec.md Acceptance Scenario US5.2, SC-007).

### Implementation for User Story 5

No new implementation task — see Note above. If T024/T025 fail, the fix is restoring `_resolve_milestone`'s guard behavior in whichever function regressed it, not new functionality.

**Checkpoint**: All five user stories pass independently. Feature-complete per `spec.md`.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T026 [P] Run `bash scripts/check.sh` (this repository's canonical verification gate, per `AGENTS.md`) and resolve any lint/type/test findings across the files this feature touched.
- [ ] T027 [P] Manually execute `quickstart.md`'s three walkthroughs (A: readiness → evidence → enter-review → claim → accept; B: decline with a rationale locator, then corrective work; C: symmetric type-guard) against a scratch repository, confirming actual CLI output matches what `quickstart.md` documents; correct either the code or the doc if they've drifted.
- [ ] T028 Add a new decision entry to `docs/DECISIONS.md` recording this feature's adoption once implementation lands, mirroring D038/D039/D040's style (what was added, what was deliberately not touched — no schema change, `bindle work` untouched, no automatic acceptance). Depends on: T001–T027 complete and merged.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. **Blocks every user story** — `list_evidence`/`get_claim`/`_resolve_milestone` are used by all five.
- **User Stories (Phases 3–7)**: All depend on Foundational. Phases 3 and 5 and 6 form the feature's real incremental spine (US1 → US3 → US4); Phase 4 (US2) and Phase 7 (US5) are test-only phases layered onto Phase 3's and every phase's implementation respectively — they can be done immediately after the phase they extend, not necessarily last.
- **Polish (Phase 8)**: Depends on all desired user stories being complete. T028 additionally depends on the feature actually being merged (a decision-log entry describes what shipped, not what is planned).

### User Story Dependencies

- **US1 (P1)**: Depends only on Foundational. No dependency on any other story.
- **US2 (P1)**: Shares its implementation with US1 (see Phase 4's Note) — its tests can only be written meaningfully once T011 exists, but add no new implementation dependency.
- **US3 (P2)**: Depends only on Foundational (uses `_resolve_milestone` from T007; does not depend on US1/US2's `review_milestone`). Independently testable without US1/US2 having landed, though a human would naturally use US1's view before US3's transition in practice.
- **US4 (P2)**: Depends only on Foundational, same reasoning as US3.
- **US5 (P3)**: Depends on Phases 3, 5, and 6 having landed (it tests their guard behavior) — the only story with a real cross-story dependency, because it is explicitly a property *of* the other four stories' construction rather than independent new behavor.

### Within Each User Story

- Tests before implementation (tests fail first, then the implementation task makes them pass — noted per-task above).
- `milestone_review.py` functions before their `cli.py` wiring (a CLI handler cannot be written against a function that doesn't exist yet).
- `cli.py` subparser tasks (T013, T019, T023) are sequential with each other — one shared file, one shared `build_parser()` function — never marked `[P]` against one another, per `plan.md`'s own note.

### Parallel Opportunities

- T003 and T004 touch the same file (`tests/test_work_ledger.py`) but disjoint new classes — sequence them (not marked `[P]`) to avoid a two-writer collision on one file in the same phase; both can be handed to the same implementer back-to-back quickly.
- Within Phase 3: T008 and T009 both target the same new file (`tests/test_milestone_review.py`, two different classes) and are sequential with each other (T008 creates the file); T010 (`tests/test_cli.py`) is a different file and is `[P]` relative to both.
- Within Phase 4: T014 (extends `test_milestone_review.py`) and T015 (extends `test_cli.py`) are genuinely parallel — different files, and each extends a class Phase 3 already created, with no overlapping edit region.
- Within Phase 5: T016/T017 — same pattern, genuinely parallel (different files).
- Within Phase 6: T020/T021 — same pattern, genuinely parallel (different files).
- Within Phase 7: T024/T025 — same pattern, genuinely parallel (different files).
- Once Foundational (Phase 2) is complete, US1 (Phase 3) and US3 (Phase 5) and US4 (Phase 6)'s *test-writing* tasks could start in parallel by different implementers (they touch different new test classes), but their *implementation* tasks (T011/T012, T018, T022) and *CLI-wiring* tasks (T013, T019, T023) all serialize through the same two shared files (`milestone_review.py`, `cli.py`'s `build_parser()`) — real parallelism here is at the test-authoring level, not the implementation level, given this feature's small size.

---

## Parallel Example: User Story 1

```bash
# After Phase 2 (Foundational) is complete:
Task: "Add TestReviewMilestone to tests/test_milestone_review.py (T008)"
Task: "Add TestListMilestones to tests/test_milestone_review.py (T009)"   # sequential with T008 -- same file
Task: "Add TestMilestoneCliSubcommands to tests/test_cli.py (T010)"      # parallel with T008/T009 -- different file
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (trivial) and Phase 2 (Foundational).
2. Complete Phase 3 (US1): `bindle milestone review`/`list` exist and work.
3. **STOP and VALIDATE**: run Walkthrough A's first half from `quickstart.md` (readiness reporting only) by hand.
4. This alone already answers the task's original framing's core question ("is this milestone mechanically ready for me to review") — Phases 5–6 add the ability to *act* on that answer through the CLI rather than library code.

### Incremental Delivery

1. Foundational → US1 (readiness visible) → US2 (evidence visible, same code, more tests) → US3 (enter-review/claim reachable via CLI) → US4 (accept/decline reachable via CLI, feature-complete) → US5 (adversarial confirmation) → Polish.
2. Each checkpoint above is independently mergeable and independently valuable — a maintainer gets real use out of US1+US2 alone (read-only visibility) even before US3/US4 land, since `accept_milestone()`/`decline_review()` remain reachable via direct library calls in the meantime, exactly as they are today.
