# Milestone/task work-item model: task composition and Spec Kit comparison

Date: 2026-08-27. Status: **superseded by completion.** `specs/002-milestone-task-work-items/` is fully implemented, verified, and adopted (docs/DECISIONS.md D038). This document is retained, unedited below, as the historical record of the composition analysis — not as an open resumption point.

## Why this document exists

Per explicit direction for this feature, the repository's `task-composition` skill (ships in the `t-step-skills/software-engineering` plugin, present on disk at `~/.claude/plugins/cache/t-step-skills/software-engineering/0.1.3/skills/task-composition/`, but not registered as an installed/invocable skill in this session) is applied directly to `specs/002-milestone-task-work-items/tasks.md`'s 19 tasks — the same workaround the prior 001 session used and documented in `plans/archive/2026-08-26-work-ledger-task-composition-handoff.md`, which this document follows as precedent.

**2026-08-27 implementation correction**: while implementing S6 (`mark_in_review`), FR-010's "single guarded, atomic conditional update" requirement turned out to mean the review-readiness condition must be embedded directly in `mark_in_review`'s own `UPDATE ... WHERE` clause, not checked by a separate `is_review_ready()` call beforehand as S6's slice description below originally assumed (a real bug, caught by S8's own test failing on first run) — a caller-side pre-check followed by a separate transition statement leaves a race window FR-010 does not permit. The fix factors the readiness condition into one shared `_review_ready_sql()` helper used by both `is_review_ready` (S7) and `mark_in_review` (S6). This makes **S6 depend on S4 (blocking) and S8's underlying predicate work (S7, T010) directly**, not merely on S1 as originally analyzed below — S6 and S7 are not the parallel-safe siblings this document first concluded; they share an implementation detail exactly the way S4/S10 already did. The slice descriptions below are left as originally written (historical record, per this repository's own append-only correction convention) with this note as the authoritative correction; `tasks.md`'s T011 line has been updated to match.

# Delivery Slices: Milestone and Task Work Items (specs/002-milestone-task-work-items)

## Slices

### S1: Schema v2 foundation
- Kind: horizontal enabler
- Includes: T001, T002, T005
- Delivers: A version-2 SQLite schema exists (`type`/`parent_id`/`description` columns, compound `CHECK` constraints), a version-1 database migrates to it safely and atomically, and `WorkItem` exposes the three new fields.
- Why grouped: T002 cannot be verified independently of T001 (there is no dataclass field to test without the column existing); T005 is this slice's own verification, not a separate correctness boundary.
- Depends on: None.
- Parallel-safe with: S2 (no shared code or state — S2 only touches the pre-existing, unchanged `work_item_evidence` table).
- Verification checkpoint: T005 passes (migration test).
- Risk / uncertainty: The table-rebuild migration (SQLite cannot `ALTER` a `CHECK` in place) is the one genuinely new mechanism this feature introduces beyond 001's precedent — worth its own checkpoint before anything builds on it, per the "risk and checkpoint boundaries" guidance (new architectural mechanism, substantial downstream work depends on it).

### S2: Qualifying mechanical evidence predicate
- Kind: vertical delivery
- Includes: T008, T009
- Delivers: The ledger can answer, purely by query, whether a done task carries at least one evidence pointer.
- Why grouped: Implementation and its verification have no useful checkpoint between them.
- Depends on: None — `work_item_evidence` is unchanged from 001; this predicate needs no v2 column.
- Parallel-safe with: S1 (see above), and with every other slice below except where explicitly noted (it only reads a table nothing else in this feature restructures).
- Verification checkpoint: T009 passes.
- Risk / uncertainty: None identified. This is the topology's actual "free" parallelism — `tasks.md`'s own linear phase presentation gates T008 behind Foundational for narrative convenience, but nothing in the dependency graph actually requires that ordering.

### S3: Typed creation & attribution
- Kind: vertical delivery
- Includes: T003, T007
- Delivers: A milestone or task can be created with correct type/parent validation, and the attribution survives a fresh ledger handle (User Story 1's own Independent Test).
- Why grouped: T007 is this slice's real verification checkpoint (the vertical-grouping test's question 2); no other task exercises T003's atomic-validation behavior end to end.
- Depends on: S1.
- Parallel-safe with: S4, S6 — different functions (`create_work_item` vs. `is_blocked`/`list_available_work_items` vs. the new `mark_in_review`/`decline_review`/`accept_milestone`), no shared mutable state, no overlapping meaning between the changes.
- Verification checkpoint: T007 passes.
- Risk / uncertainty: None identified.

### S4: Type-aware resolved-predicate & blocking
- Kind: vertical delivery
- Includes: T004
- Delivers: Blocking/availability computation correctly treats a milestone's terminal state (`accepted`/`superseded`) as resolved, and a task's (`done`/`superseded`) as resolved, for any cross-type dependency edge.
- Why grouped: One coherent change to the existing resolved-predicate logic; no natural sub-boundary inside it.
- Depends on: S1.
- Parallel-safe with: S3, S6 (see S3's reasoning — applies symmetrically).
- Verification checkpoint: Folded into S5's convergence test (T006) rather than given its own — nothing in `tasks.md` pairs T004 with an independent test naming only it; the earliest real verification of the type-aware predicate is the same convergence point S3's creation/validation work also needs.
- Risk / uncertainty: **Shared-logic hazard, not a shared-file hazard.** `generate_projection()` (S10, T015) contains its own inline copy of a blocking/eligibility subquery, per the original implementation-fidelity investigation ("computes eligible via an inline `NOT EXISTS` claim/blocking subquery in one SQL statement" — deliberate, for snapshot consistency). If S4 and S10 are built as truly independent parallel slices, each would need to independently reproduce the same type-aware "resolved" rule, risking drift between the two copies. **Resolution adopted for implementation**: extract the type-aware resolved condition as one shared SQL fragment/helper used by both `is_blocked`/`list_available_work_items` (S4) and `generate_projection` (S10), authored once as part of S4, consumed by S10 — this converts a would-be parallel-safety violation into an explicit S4→S10 dependency (see S10 below), which is the honest topology rather than papering over duplicated logic.

### S5: Convergence — type/parent + blocking test
- Kind: convergence/integration
- Includes: T006
- Delivers: The first point where S3's creation/validation and S4's blocking generalization are proven correct together — cross-type dependency edges (task-on-milestone, milestone-on-task, etc.) exercised against actually-created rows.
- Why grouped: A genuine correctness boundary — two independently built pieces meeting for the first time.
- Depends on: S3, S4 (both).
- Parallel-safe with: S6, S7 (different test classes, no shared fixtures beyond the ledger schema itself).
- Verification checkpoint: T006 passes.
- Risk / uncertainty: None identified.

### S6: Milestone lifecycle transitions
- Kind: vertical delivery
- Includes: T011, T013
- Delivers: A milestone can move `open → review`, `review → open` (decline), and `review → accepted`, each a guarded single-winner transition mirroring 001's existing `mark_done`/`mark_superseded` pattern.
- Why grouped: T013 (decline/accept) has no independent meaning without T011 (enter review) already existing — together they deliver the whole reviewable-milestone transition surface.
- Depends on: S1 only — these transitions need `type`/`status` and the compound `CHECK`, nothing from S2's evidence predicate or S4's blocking generalization.
- Parallel-safe with: S3, S4 (different functions; the vertical-grouping test's question 2 — "can this become-true claim be verified independently" — is satisfiable for this slice on its own once S1 lands).
- Verification checkpoint: Folded into S8 (T012) and S9 (T014) below, not verified standalone — `tasks.md` pairs the transition functions with review-readiness (T012) and history-preservation (T014) tests, not a bare transition-only test.
- Risk / uncertainty: None identified.

### S7: Review readiness
- Kind: vertical delivery
- Includes: T010
- Delivers: A milestone's review-readiness (unblocked, has children, every child resolved-and-evidenced) is computed correctly, purely by query.
- Why grouped: One coherent predicate; no sub-boundary.
- Depends on: S2 (evidence predicate), S4 (blocked check + type-aware resolution), and transitively S1 (parent_id/children).
- Parallel-safe with: S6 (different functions — review-readiness computation vs. transition guards), S3.
- Verification checkpoint: Folded into S8 (T012).
- Risk / uncertainty: None identified.

### S8: Convergence — milestone review lifecycle
- Kind: convergence/integration
- Includes: T012
- Delivers: The first point where review-readiness (S7) and the enter-review transition (S6) are proven correct together, across the full matrix spec.md's SC-002/SC-003 require (1/2/5+ children, resolved/unresolved, evidenced/unevidenced; concurrent-transition race).
- Why grouped: A genuine correctness boundary between two independently built pieces (S6, S7).
- Depends on: S6, S7 (both).
- Parallel-safe with: S9, S5.
- Verification checkpoint: T012 passes.
- Risk / uncertainty: None identified.

### S9: Decline/accept and history-preservation test
- Kind: vertical delivery (test-only; T013's implementation already landed in S6)
- Includes: T014
- Delivers: Proof that declining a milestone never mutates a child task's record, that a new corrective task is accepted and recomputes readiness, and that `accept_milestone` only succeeds from `review`.
- Why grouped: This is T013's real verification checkpoint — nothing else in `tasks.md` exercises the decline/accept paths.
- Depends on: S6.
- Parallel-safe with: S8, S5, S7 (independent of the review-readiness/enter-review convergence entirely — it only needs T013's transitions to exist).
- Verification checkpoint: T014 passes.
- Risk / uncertainty: None identified.

### S10: Projection filtering
- Kind: vertical delivery
- Includes: T015
- Delivers: `generate_projection()` never returns a milestone row, using the same shared type-aware resolved-predicate helper S4 introduced.
- Why grouped: One coherent change; its test is paired with S11's in T017, not given its own.
- Depends on: **S4** (the shared-helper resolution adopted above — see S4's "Risk / uncertainty").
- Parallel-safe with: S11 (different function — `generate_projection` vs. `archive_work_item` — no shared state).
- Verification checkpoint: Folded into S12 (T017).
- Risk / uncertainty: None identified, given the S4 dependency above is honored.

### S11: Milestone archival precondition
- Kind: vertical delivery
- Includes: T016
- Delivers: Archiving a milestone with unresolved children is refused outright; a milestone's thinned row preserves `type` alongside `status`/`superseded_by` so children's `parent_id` stays resolvable.
- Why grouped: One coherent precondition-plus-preservation change to one existing function.
- Depends on: S1 only (needs `parent_id`/`type` columns; does not need S4's blocking generalization — this precondition is a plain child-status query, not a dependency-resolution query).
- Parallel-safe with: S10, S3, S4, S6, S7 — touches a function (`archive_work_item`) none of those touch.
- Verification checkpoint: Folded into S12 (T017).
- Risk / uncertainty: None identified.

### S12: Convergence — projection & archival test
- Kind: convergence/integration
- Includes: T017
- Delivers: Proof that S10 and S11 are each correct and, together, that an archived milestone's children remain fully resolvable through the projection and blocking machinery alike.
- Depends on: S10, S11 (both).
- Parallel-safe with: S8, S9, S5.
- Verification checkpoint: T017 passes.
- Risk / uncertainty: None identified.

### S13: Final integration checkpoint
- Kind: convergence/integration
- Includes: T018, T019
- Delivers: `quickstart.md`'s five scenarios pass end to end as one coherent run, and the repository's own canonical verification gate (`scripts/check.sh`) passes.
- Depends on: S3 (T007), S2 (T009), S8 (T012), S9 (T014), S12 (T017) — every story-level test slice.
- Parallel-safe with: None — final checkpoint.
- Verification checkpoint: T018 and T019 both pass.
- Risk / uncertainty: None identified.

## Recommended execution grouping

```
Wave 1: S1 ∥ S2
Wave 2: S3 ∥ S4 ∥ S6   (each depends only on S1; S2 already independent)
Wave 3: S5 ∥ S7 ∥ S11  (S5 needs S3+S4; S7 needs S2+S4; S11 needs S1 only but has no reason to run earlier than its siblings)
Wave 4: S8 ∥ S9 ∥ S10  (S10 now explicitly depends on S4, already satisfied by Wave 2/3)
Wave 5: S12
Wave 6: S13
```

This is a dependency-respecting default ordering, not a priority call — spec.md's own P1/P2/P3 story priorities are already respected by construction (US1/US2 material lands in Waves 1–2, US5 material no later than Wave 4).

## Available parallelism

On paper, real: up to three independent branches in Waves 2–4 (e.g., S3/S4/S6, or S5/S7/S11). This is genuine semantic independence, not inflated — each pair touches a different function with no overlapping meaning in the change, per the topology reasoning under each slice above.

**Recommendation actually adopted for this feature: do not exploit it.** The entire feature is two files (`src/bindle/work_ledger.py`, `tests/test_work_ledger.py`), the total diff is small (~19 tasks, no task described above needs more than a focused function-level change), and S4's shared-helper hazard (see S4's "Risk / uncertainty") already shows that two of the "parallel" slices share an implementation detail that is easier to get right once, sequentially, than to reconcile after two agents each write it independently. Per `AGENTS.md`'s own delegation guidance ("Prefer direct work for sequential, small, or context-heavy tasks... Delegate only genuinely independent, bounded work"), this feature is implemented directly, in the wave order above, by one agent — the composition analysis's value here is in the *ordering and risk-flagging* (especially the S4/S10 coupling), not in justifying a parallel fan-out that this feature's actual size doesn't warrant.

## Bottlenecks to more parallelism

S1 is the one genuine serialization point — nothing in Wave 2 can start before it lands, because every later slice reads at least one of `type`/`parent_id`/`description` or depends on the compound `CHECK` existing. This is not a defect; a schema migration is inherently a single serialization point.

## Topology issues

- **`tasks.md`'s own linear phase numbering overstates real serialization** in two places, both corrected above: (1) T008/T009 (S2) do not actually depend on Foundational at all — `tasks.md` places them after Phase 2 for narrative convenience, not because of a real dependency; (2) T004 and T015 look independent by task ID and by which named function they touch, but share an implementation detail (the type-aware "resolved" predicate) that makes them **not** parallel-safe as originally scoped — resolved above by making S10 explicitly depend on S4 rather than treating them as siblings.
- No dependency cycles found.
- No false-parallel slices sharing an unmet prerequisite, once the S10→S4 correction above is applied.
- No invalid convergence ordering: every convergence slice (S5, S8, S9's non-convergence status noted, S12, S13) waits on everything it names.

## Out of scope

This composition does not re-decompose, re-prioritize, or re-justify `tasks.md`'s own task list, and it does not choose which slice to build first beyond the dependency-respecting default order above (spec.md's P1/P2/P3 priorities already govern that). It does not build a durable dependency-tracking system — the waves above are a one-time analysis for this feature's implementation, not a maintained artifact.

## Composition vs. Spec Kit planning/tasks — comparison

**What composition found that `tasks.md`'s own phase/story structure did not:**
- The S2 (T008/T009) independence from Foundational — a real "free parallelism" fact invisible from `tasks.md`'s linear phase presentation, which gates everything behind Phase 2 by convention.
- The S4/S10 shared-implementation-detail hazard — `tasks.md` lists T004 and T015 under different user-story phases (US3-adjacent Foundational vs. US5) with no textual link between them; only tracing what each function's SQL actually needs surfaced that they'd duplicate logic if built independently.
- That S6 (milestone transitions) is parallel-safe with S3/S4 despite `tasks.md` placing it in a later phase (Phase 5) than S3/S4 (Phase 2/Foundational) — the phase *number* implied a serialization the actual dependency graph doesn't require, the same failure mode 001's own composition handoff flagged for its S3/S4 pair.

**What `tasks.md`'s Spec Kit decomposition captured better:**
- The user-story framing itself (which composition explicitly does not second-guess, per its own input-boundary rule) — *why* each group of tasks matters, traced to a specific spec.md scenario and Success Criterion, is Spec Kit's own contribution and composition only consumes it.
- The exact test content each task needs (which fixtures, which assertions, which spec.md scenario each traces to) — composition groups tasks into slices but does not re-specify what each task's test must assert.

**Overlap**: Both agree on the fundamental phase ordering (schema before behavior, behavior before cross-cutting projection/archival concerns) and on treating tests as inseparable from their implementation task where no independent checkpoint exists (US1, S6's transitions).

**Does composition give a better implementation-unit boundary here?** Marginally, and mainly for *risk-flagging* (the S4/S10 coupling) rather than for *parallelism actually exploited* — see "Available parallelism" above. For a feature this small, `tasks.md`'s own story-ordered checklist is already a perfectly adequate implementation unit boundary for a single agent working sequentially; composition's real contribution was catching one coordination hazard a naive parallel fan-out would have hit, and confirming that the "obvious" parallelism is real but not worth spending on at this scale.

**Which decomposition governs implementation**: `tasks.md` remains canonical, per this repository's own instruction to keep the Spec Kit plan authoritative unless a compelling repository-supported reason says otherwise. This composition analysis's only actual effect on `tasks.md` is the corrected T015 dependency (now on T004, not merely "Foundational" in spirit) — reconciled into the task list below rather than left as a competing document.

**Neither approach introduced unnecessary coordination machinery** — no scheduler, dependency-graph store, or subagent-orchestration system was built or proposed; this document is itself the one-time analysis, not a maintained system, per the `task-composition` skill's own explicit refusal to build one.
