# Symphony Task Integration: task composition and Spec Kit comparison

Date: 2026-08-27. Status: **composition complete; implementation proceeds using the parallelism identified below.**

## Why this document exists

Per explicit direction for this feature, the repository's `task-composition` skill (ships in the `t-step-skills/software-engineering` plugin, present on disk at `~/.claude/plugins/cache/t-step-skills/software-engineering/0.1.3/skills/task-composition/`, not registered as an installed/invocable skill in this session) is applied directly to `specs/003-symphony-task-integration/tasks.md`'s 26 tasks, following the same workaround `plans/active/2026-08-27-milestone-task-composition-analysis.md` (specs/002) and `plans/archive/2026-08-26-work-ledger-task-composition-handoff.md` (specs/001) already used.

Unlike specs/002's own composition (which found real parallelism but chose not to exploit it, given a two-file, small-diff feature), this feature's three user stories touch three almost entirely disjoint files (`speckit_loader.py`, two new `work_ledger.py` methods, `symphony_projection.py`) with no shared implementation detail between them — a materially different topology from 002's own single-file feature. That difference is reflected in the execution recommendation below.

# Delivery Slices: Symphony Task Integration (specs/003-symphony-task-integration)

## Slices

### S1: Declarative resync primitive
- Kind: vertical delivery
- Includes: T001, T005
- Delivers: An existing work item's `title`/`description` can be updated in place from a new source read, without touching its runtime-owned state (`status`, claim, evidence) — a real, independently reusable ledger capability, not merely "add a method."
- Why grouped: T005 is this primitive's own verification checkpoint; nothing else in `tasks.md` exercises `resync_declarative_fields()` directly. Mirrors `specs/002`'s own S2 (`has_qualifying_evidence`, T008/T009) — a small, single-consumer primitive that still passes the vertical grouping test independently of its downstream consumer.
- Depends on: None.
- Parallel-safe with: S3, S4, S5 (entirely different functions/files, no shared state). Not parallel with S2, which depends on it.
- Verification checkpoint: T005 passes.
- Risk / uncertainty: None identified.

### S2: Spec Kit loader (library)
- Kind: vertical delivery
- Includes: T002, T003, T004, T006, T007, T008, T009, T010, T011, T012
- Delivers: A settled Spec Kit `tasks.md` can be idempotently loaded into canonical, correctly-attributed work items — reloading is safe (no duplicates, no runtime-state disturbance), cross-feature task-id collisions never occur, and intra-file dependency resolution is order-independent.
- Why grouped: The parser (T002) has no independently meaningful behavior until `load_feature()` (T003) consumes it; T004's edge-case handling extends the same function. T006–T012 are this slice's own comprehensive verification of every Acceptance Scenario in User Story 1 — none of them has an independent checkpoint elsewhere.
- Depends on: S1 (T003 depends on T001).
- Parallel-safe with: S3, S4, S5 (a completely separate new module, `speckit_loader.py`, touching no function any other slice touches).
- Verification checkpoint: T006–T012 all pass.
- Risk / uncertainty: None identified — the two-pass ordering strategy (research.md) is well-specified enough that no sub-boundary within this slice offers a materially earlier useful checkpoint.

### S3: External projection primitive
- Kind: vertical delivery
- Includes: T013, T015
- Delivers: The ledger can correctly compute the task-only, `dispatchable`-aware external projection row set — a real, independently verifiable capability that exists before any file-export mechanism does.
- Why grouped: T015 is this primitive's own direct verification (in `tests/test_work_ledger.py`, alongside `resync_declarative_fields`'s own test) — exactly the same shape as S1, and as `specs/002`'s own S2/S7 precedent for a small derived-query primitive with its own standalone test.
- Depends on: None.
- Parallel-safe with: S1, S2, S5. Not parallel with S4, which depends on it.
- Verification checkpoint: T015 passes.
- Risk / uncertainty: **Shared-logic hazard, mitigated by design, not by composition.** Like `specs/002`'s own S4/S10 finding, this query risks silently duplicating the blocking predicate. Unlike that prior case, this was already resolved at the *design* stage (`data-model.md`, `research.md`) by mandating reuse of the existing `_STILL_BLOCKING_CONDITION` fragment verbatim — composition confirms this was the right call rather than needing to invent a new S-to-S dependency the way `specs/002` did.

### S4: Projection export (publish, library)
- Kind: vertical delivery
- Includes: T014, T016, T017
- Delivers: A versioned, disposable SQLite file exists on disk that an external reader can open and query directly, independent of Bindle's own process or internal schema.
- Why grouped: T016/T017 are this slice's own verification (schema shape + version, and determinism) — no other task exercises `publish()`.
- Depends on: S3 (T014 depends on T013).
- Parallel-safe with: S1, S2, S5.
- Verification checkpoint: T016 and T017 both pass.
- Risk / uncertainty: None identified.

### S5: Write-surface functions (library)
- Kind: vertical delivery
- Includes: T018, T020, T021, T022
- Delivers: An external caller can claim, release, and complete a task — or be cleanly and distinctly rejected for a milestone or nonexistent id — using only three narrow functions, with the same atomicity guarantees the underlying ledger primitives already provide.
- Why grouped: T020–T022 are this slice's own comprehensive verification (concurrency, release/complete semantics, milestone rejection) — no other task touches `claim_task`/`release_task`/`complete_task`.
- Depends on: None. This is this feature's most independent slice: `claim_task`/`release_task`/`complete_task` need only `WorkLedger.get_work_item`/`claim`/`release_claim`/`mark_done`, every one of which already exists unchanged from 001/002 — nothing from S1–S4 is required.
- Parallel-safe with: S1, S2, S3, S4 — genuinely, and more completely than any pair `specs/002`'s own composition found for itself (that feature's slices all shared one file; these three (S2, S4, S5) share none).
- Verification checkpoint: T020, T021, T022 all pass.
- Risk / uncertainty: None identified.

### S6: CLI scaffolding
- Kind: horizontal enabler
- Includes: the `work_parser = subparsers.add_parser("work", ...)` / `work_subparsers = work_parser.add_subparsers(...)` skeleton and its `if args.command == "work":` dispatch stub in `cli.py` — a small slice of `tasks.md`'s T019, extracted.
- Delivers: A `bindle work` subcommand namespace exists for any leaf subcommand to register into.
- Why it should exist independently: without it, S7/S8/S9 below (see next slices) would each need to create the same `work_parser`/`work_subparsers` object, which is not itself divisible three ways — one of them would have to "win" and the others would silently depend on that choice, an implicit, unnamed coupling exactly the kind this skill's convergence-representation rule exists to avoid.
- What it enables: S7, S8, S9 (named below) — three separate downstream CLI-leaf slices.
- Does it increase parallelism: yes — with it landed first, S7/S8/S9 can each add their own subcommand leaf concurrently, touching the same growing `cli.py` file only in independent, non-overlapping `add_parser(...)`/`_cmd_work_*` additions (an extension-point pattern this skill's own parallel-safety guidance explicitly treats as compatible with concurrent editing of one file).
- Depends on: None.
- Parallel-safe with: S1–S5 (a few lines in `cli.py`, touching no other slice's file).
- Verification checkpoint: `bindle work --help` lists the (as yet unimplemented) subcommand names with no crash.
- Risk / uncertainty: None identified.

### S7: CLI leaf — `load-speckit`
- Kind: vertical delivery
- Includes: the `load-speckit` portion of T019 and T023.
- Delivers: A maintainer can invoke `bindle work load-speckit <feature_dir>` from a shell and get the same result User Story 1's library path already provides, with the repository's standard exit-code/stderr convention.
- Why grouped: implementation and its own CLI-level test belong together — no useful checkpoint exists between wiring the subcommand and proving it works from the command line.
- Depends on: S2 (needs `load_feature()`), S6 (needs the `work` namespace).
- Parallel-safe with: S8, S9 (independent `add_parser`/`_cmd_work_*` additions to the same file — see S6's reasoning).
- Verification checkpoint: its slice of T023 passes.
- Risk / uncertainty: None identified.

### S8: CLI leaf — `publish`
- Kind: vertical delivery
- Includes: the `publish` portion of T019 and T023.
- Delivers: An operator can invoke `bindle work publish` to regenerate the Symphony-facing export file from a shell.
- Why grouped: same reasoning as S7.
- Depends on: S4 (needs `publish()`), S6.
- Parallel-safe with: S7, S9.
- Verification checkpoint: its slice of T023 passes.
- Risk / uncertainty: None identified.

### S9: CLI leaf — `claim` / `release` / `done`
- Kind: vertical delivery
- Includes: the `claim`/`release`/`done` portion of T019 and T023.
- Delivers: An external coordinator (or a human standing in for one) can claim, release, and complete a task entirely from the command line, with the same guarantees S5's library functions provide.
- Why grouped: three thin, near-identical CLI leaves over the three S5 functions — no independent checkpoint exists between any two of them worth a separate slice.
- Depends on: S5 (needs `claim_task`/`release_task`/`complete_task`), S6.
- Parallel-safe with: S7, S8.
- Verification checkpoint: its slice of T023 passes.
- Risk / uncertainty: None identified.

### S10: Documentation correction
- Kind: vertical delivery
- Includes: T024.
- Delivers: `docs/SYMPHONY.md` no longer asserts something this feature makes false — an accuracy property independent of any code slice.
- Why grouped: one coherent, self-contained doc edit; no sub-boundary.
- Depends on: **None of S1–S9.** `tasks.md`'s own stated "Depends on: T014, T019" is broader than the real dependency: the update only needs this feature's *design* to be settled (the exact stale sentences and their replacement, already fixed in `research.md`'s own "Decision: docs/SYMPHONY.md update scope"), not its implementation. This is a genuine topology correction — see "Topology issues" below.
- Parallel-safe with: every other slice, including S1–S9, from the very start of implementation.
- Verification checkpoint: manual review against `research.md`'s decision (no automated test covers prose accuracy).
- Risk / uncertainty: None identified.

### S11: Quickstart end-to-end convergence
- Kind: convergence/integration
- Includes: T025.
- Delivers: Proof that all three user stories work together, through the same interfaces (CLI and library) an actual external coordinator would use, in one coherent run.
- Why grouped: a genuine correctness boundary — the first point every independently-built piece (loader, projection export, write surface, and their CLI leaves) is exercised together.
- Depends on: S2, S4, S5, S7, S8, S9 (every story's library and CLI surface).
- Parallel-safe with: None — it is the convergence point for everything except S10/S12.
- Verification checkpoint: T025 passes.
- Risk / uncertainty: None identified.

### S12: Final integration checkpoint
- Kind: convergence/integration
- Includes: T026.
- Delivers: The repository's own canonical verification gate passes with this feature's code included.
- Depends on: S10, S11 (everything).
- Parallel-safe with: None — final checkpoint.
- Verification checkpoint: `bash scripts/check.sh` passes.
- Risk / uncertainty: None identified.

## Recommended execution grouping

```
Wave 1: S1 ∥ S3 ∥ S5 ∥ S6 ∥ S10   (five fully independent starting points)
Wave 2: S2 (needs S1) ∥ S4 (needs S3)   (S5 already finished in Wave 1; S6/S10 already finished)
Wave 3: S7 ∥ S8 ∥ S9   (each needs its own story slice + S6, all satisfied by Wave 2)
Wave 4: S11
Wave 5: S12
```

This is a dependency-respecting default ordering, not a priority call — spec.md's own P1/P1/P2 story priorities are already respected by construction (every task in US1 and US2 lands no later than Wave 3, matching their shared P1; US3's own material lands in the same wave, one priority tier below but with no dependency forcing it later).

## Available parallelism

Real, and larger than either `specs/001` or `specs/002` found for themselves: **five independent branches in Wave 1** (S1, S3, S5, S6, S10), collapsing to **three** in Wave 2 (S2, S4 — S5/S6/S10 already done) and **three again** in Wave 3 (S7, S8, S9). This is not inflated — S1/S3/S5 touch three different functions/files with zero shared state (confirmed directly against `plan.md`'s Project Structure: `work_ledger.py`'s two new methods are independent of each other and of the two new modules; the two new modules share no function), and S6/S10 touch, respectively, a few lines of `cli.py` and one unrelated doc file.

## Bottlenecks to more parallelism

S6 (CLI scaffolding) is the one genuine, if small, serialization point for the CLI-facing half of the feature: S7/S8/S9 cannot add their own subcommand leaf until the shared `work` namespace exists, though this bottleneck is trivial in size (a handful of lines) and resolves in Wave 1 alongside four other independent slices, so it costs nothing in practice. S11 is a necessary, unavoidable final convergence point for the same reason `specs/001`/`specs/002`'s own quickstart-integration slices were — no way to prove three independently-built stories work together except by actually running them together.

## Topology issues

- **`tasks.md`'s own T019/T023 bundle all five CLI subcommands into one task each, which overstates real serialization.** Composition found these decompose cleanly into S6 (shared scaffolding) plus three fully independent leaves (S7, S8, S9) — the CLI portion of this feature has *more* real parallelism than `tasks.md`'s own linear task numbering suggests, the same failure mode `specs/002`'s own composition flagged for its S6-vs-S3/S4 phase-numbering mismatch.
- **`tasks.md`'s stated dependency for T024 ("Depends on: T014, T019") is broader than necessary.** The documentation correction only depends on this feature's design being settled (already true as of Phase 1), not on any code landing — corrected above to "None" in S10.
- No dependency cycles found.
- No false-parallel slices sharing an unmet prerequisite, once the S6/S7/S8/S9 split above is applied.
- No invalid convergence ordering: S11 waits on every story's full surface (library + CLI); S12 waits on S11 and S10.

## Out of scope

This composition does not re-decompose, re-prioritize, or re-justify `tasks.md`'s own task list beyond the two corrections named under "Topology issues" (splitting T019/T023's CLI bundle into S6–S9; loosening T024's stated dependency), and it does not choose which slice to build first beyond the dependency-respecting default order above (spec.md's P1/P1/P2 priorities already govern that, and are already satisfied by the waves above). It does not build a durable dependency-tracking system — the waves above are a one-time analysis for this feature's implementation, not a maintained artifact.

## Composition vs. Spec Kit planning/tasks — comparison

**What composition found that `tasks.md`'s own phase/story structure did not:**
- The CLI bundle split (T019/T023 → S6 + S7/S8/S9) — `tasks.md` presents `bindle work`'s five subcommands as one implementation task and one test task per story-adjacent grouping, but tracing what each subcommand leaf actually touches shows three of them are mutually independent once a small shared scaffolding step lands — a materially larger parallel-execution opportunity than the task list's own grouping implies.
- T024's real dependency is narrower than stated — a small but real correction, since accepting `tasks.md`'s own "Depends on: T014, T019" at face value would have delayed a zero-code documentation fix until the very end of implementation for no reason.
- The overall scale of *safe* parallelism available in this feature (five independent Wave 1 branches) — invisible from `tasks.md`'s linear phase/story presentation, which reads top-to-bottom as User Story 1 → 2 → 3 in sequence.

**What `tasks.md`'s Spec Kit decomposition captured better:**
- The user-story framing itself (why each group of tasks matters, traced to a specific spec.md scenario and Success Criterion) — Spec Kit's own contribution, which composition only consumes and does not second-guess.
- The exact test content each task needs (which acceptance scenario, which fixture shape, which edge case) — composition groups tasks into slices but does not re-specify what each task's test must assert.

**Overlap**: Both agree on the fundamental grouping of implementation with its own directly-associated tests (no split between "write the code" and "prove it works" tasks), and both correctly identify User Story 3 (the write surface) as needing nothing from User Stories 1/2's own implementation.

**Does composition give a better implementation-unit boundary here?** More than `specs/002`'s own composition found for itself — there, composition's contribution was mainly risk-flagging (the S4/S10 shared-logic hazard) rather than exploitable parallelism, because that feature was a single small file. Here, this feature's own three-module structure (per `plan.md`'s Project Structure) makes the parallelism real and worth using: five genuinely independent starting slices, not a theoretical dependency-graph permission.

**Which decomposition governs implementation**: `tasks.md` remains canonical for *what* each task must do and *how it's verified*; this composition analysis governs the *order and grouping* actual implementation work is organized into — the two corrections above (CLI bundle split, T024 dependency) are reconciled into how implementation proceeds without editing `tasks.md`'s own task content.

Neither approach introduces unnecessary coordination machinery — no scheduler, dependency-graph store, or persistent orchestration system was built or proposed; this document is itself the one-time analysis, not a maintained system, per the `task-composition` skill's own explicit refusal to build one.
