# Implementation Plan: Milestone Review Surface

**Branch**: `spec/milestone-review-surface` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004-milestone-review-surface/spec.md`

**Baseline**: `specs/001-durable-work-ledger/`, `specs/002-milestone-task-work-items/`, and `specs/003-symphony-task-integration/` are fully implemented (`src/bindle/work_ledger.py`, `src/bindle/symphony_projection.py`, `src/bindle/cli.py`; `tests/test_work_ledger.py`, `tests/test_symphony_projection.py`, `tests/test_cli.py`; schema version 3; adopted in `docs/DECISIONS.md` D038/D039/D040). The milestone review lifecycle this feature presents — `is_review_ready()`, `mark_in_review()`, `decline_review()`, `accept_milestone()`, `has_qualifying_evidence()` — is not built here; it already exists and is already tested. This plan adds two small, generic, coordinator-agnostic read-only methods to `work_ledger.py` and one new CLI-facing module plus a new `bindle milestone` command family in `cli.py` — the same shape 003 already used for `speckit_loader.py`/`symphony_projection.py`, applied to a human-facing rather than coordinator-facing surface.

## Summary

Two pieces. (1) Two new read-only `WorkLedger` methods — `list_evidence(work_item_id) -> list[EvidencePointer]` and `get_claim(work_item_id) -> ClaimInfo | None` — each a single `SELECT` over the existing, unchanged `work_item_evidence`/`work_item_claims` tables, generalizing `has_qualifying_evidence()`/`is_claimed()`'s existing `EXISTS` checks into full row reads. No schema change, no new table, no new column, no `_SCHEMA_VERSION` bump. (2) A new module, `src/bindle/milestone_review.py`, holding a `review_milestone(ledger, id) -> MilestoneReviewResult` read composer (built entirely from existing/new `WorkLedger` reads: `get_work_item`, `list_work_items`, `is_review_ready`, `list_evidence`, `is_blocked`, `get_claim`) and five thin, type-checked wrapper functions (`enter_review`, `claim_milestone`, `release_milestone`, `accept`, `decline`) that call the corresponding existing `WorkLedger` lifecycle method and, for `accept`/`decline`, optionally `add_evidence()` afterward — mirroring `symphony_projection.py`'s existing `claim_task`/`release_task`/`complete_task` shape exactly, but for milestones instead of tasks, and exposed as a new `bindle milestone review|list|enter-review|claim|release|accept|decline` CLI family in `cli.py`, deliberately separate from `bindle work`.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from 001/002/003; matches `pyproject.toml`).

**Primary Dependencies**: None beyond the standard library — unchanged from 001/002/003. `sqlite3` (stdlib) for the two new read queries, `argparse` (stdlib, already used by `cli.py`) for the new CLI subcommands.

**Storage**: The existing internal `ledger.sqlite3` only (`ledger_path()`, unchanged). `work_items`/`work_item_blocked_by`/`work_item_claims`/`work_item_evidence` unchanged in shape; no new table, no new column, no schema version bump — the two new methods are additional `SELECT`s over tables that already carry every field they read.

**Testing**: `pytest`. Additions to `tests/test_work_ledger.py` for `list_evidence()`/`get_claim()` only (every existing test class unchanged), a new `tests/test_milestone_review.py` (mirroring the one-module-one-test-file convention `speckit_loader.py`/`test_speckit_loader.py` and `symphony_projection.py`/`test_symphony_projection.py` already establish), and additions to `tests/test_cli.py` (a new `TestMilestoneCliSubcommands` class, mirroring the existing `TestWorkCliSubcommands` at `tests/test_cli.py:2523`).

**Target Platform**: Same as 001/002/003 — local Python CLI/library, macOS/Linux.

**Project Type**: Single Python package (`src/bindle/`), unchanged; one new module added within it.

**Performance Goals**: N/A at this scale, unchanged from 001/002/003 — a repository's own handful-to-dozens of work items; the review view's per-child evidence/blocking reads are O(children) simple indexed lookups, no batching or pagination is needed.

**Constraints**: Must not modify `specs/001`, `specs/002`, or `specs/003`'s own artifacts, schema, or write surface (spec.md FR-012/FR-013). Must not add a new milestone status, persisted readiness flag, or any other newly-stored derived fact (spec.md FR-012, SC-008). Must not require a milestone to be claimed as a precondition for `enter-review`/`accept`/`decline` (spec.md FR-011). Must record a rationale-locator evidence pointer only after its transition succeeds, never on a rejected attempt (spec.md FR-010). Must reject a `task` id on every new command, and must not change `bindle work claim/release/done`'s existing categorical rejection of a `milestone` id (spec.md FR-009, User Story 5).

**Scale/Scope**: Unchanged from 001/002/003 — one repository's own work, single machine, one or more linked worktrees.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` remains the unfilled Spec Kit template (unchanged from 001/002/003's own finding, verified this session). This repository's operative constitution remains `AGENTS.md` ("Architecture rules") and `docs/PHILOSOPHY.md`, per repo-local precedence — unchanged posture from prior plans.

Gates evaluated:

| Gate | Status | Basis |
|---|---|---|
| `work_ledger.py` never becomes a coordinator- or reviewer-specific adapter (module's own docstring) | **PASS** | The two new methods (`list_evidence`, `get_claim`) stay generic and coordinator-agnostic in name and shape, exactly like `has_qualifying_evidence()`/`is_claimed()` already are — no "milestone review" framing inside `work_ledger.py` itself. All review-specific framing (the composed view, the CLI verbs) lives in the new `milestone_review.py` module, mirroring `symphony_projection.py`'s existing separation. |
| No new arbitration mechanism (spec.md FR-008) | **PASS** | `enter_review`/`claim_milestone`/`release_milestone`/`accept`/`decline` call `WorkLedger.mark_in_review()`/`claim()`/`release_claim()`/`accept_milestone()`/`decline_review()` directly and add nothing beyond a type check plus, for accept/decline, one conditional `add_evidence()` call gated on the transition's own return value — no new lock, no new table, no new state machine. |
| No new persisted state (spec.md FR-012, SC-008) | **PASS** | `list_evidence`/`get_claim` are pure `SELECT`s; nothing is written by either. The CLI wrappers write only through already-existing `WorkLedger` mutation methods. |
| No raw SQL / DB handle exposed as the contract (`AGENTS.md`, mirrors 003's same gate) | **PASS** | The new surface's public shape is library functions (fixed signatures, small result vocabularies) and CLI subcommands — nothing returns a connection or accepts arbitrary SQL. |
| Milestones/tasks remain categorically separated (spec.md FR-009, User Story 5) | **PASS** | Every new operation checks `type` first (`get_work_item(id).type == 'milestone'`) and rejects otherwise with a distinct result — the exact mirror of `claim_task`/`release_task`/`complete_task`'s existing "categorically rejected" milestone guard in `symphony_projection.py`. `bindle work claim/release/done` themselves are untouched. |
| No automatic/inferred acceptance judgment (spec.md FR-014) | **PASS** | `accept`/`decline` each require an explicit id and an explicit caller action; neither is invoked by anything in this feature except a direct CLI invocation. No scheduler, hook, or heuristic calls them. |
| Worktrees (D018) — every linked worktree sees the same ledger state | **PASS** | `milestone_review.py`'s functions take a `WorkLedger` (already resolved from `RepoInfo.repo_root`, the Git common directory) exactly like `symphony_projection.py`'s existing functions do — no new path resolution is introduced. |
| Evidence remains reused, not replaced (spec.md FR-003/FR-012, Baseline) | **PASS** | `list_evidence()` reads the existing `work_item_evidence` table verbatim; the rationale-locator mechanism (FR-010) is an ordinary `kind='other'` `add_evidence()` call, the same one `override_release_claim()` already uses for its own justification note — no new evidence kind, no new table. |

No unjustified violations. Complexity Tracking is not filled in below because none apply.

## Project Structure

### Documentation (this feature)

```text
specs/004-milestone-review-surface/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── milestone-review-surface.md
└── tasks.md             # Phase 2 output ($speckit-tasks)
```

### Source Code (repository root)

```text
src/bindle/
├── work_ledger.py          # EXTENDED — two new generic, coordinator-agnostic
│                           # read-only methods: list_evidence() (full-row
│                           # read over work_item_evidence, generalizing
│                           # has_qualifying_evidence()'s existing EXISTS
│                           # check) and get_claim() (full-row read over
│                           # work_item_claims, generalizing is_claimed()'s
│                           # existing EXISTS check). No schema/version
│                           # change. Every existing method is untouched.
├── milestone_review.py      # NEW — review_milestone() (the read-only view
│                           # composer: status, readiness, per-child
│                           # status/evidence/blocking, milestone's own
│                           # claim) and five thin write wrappers
│                           # (enter_review, claim_milestone,
│                           # release_milestone, accept, decline), each
│                           # type-checked against 'milestone' and built
│                           # directly on existing WorkLedger lifecycle
│                           # methods — mirrors symphony_projection.py's
│                           # existing claim_task/release_task/
│                           # complete_task shape.
└── cli.py                  # EXTENDED — new `bindle milestone` subcommand
                            # family (review, list, enter-review, claim,
                            # release, accept, decline), following the
                            # existing repo/skills/work nested-subparser
                            # convention. `bindle work` itself is untouched.

tests/
├── test_work_ledger.py      # EXTENDED — new test class for list_evidence()
│                           # and get_claim() only; every existing test
│                           # class unchanged.
├── test_milestone_review.py # NEW
└── test_cli.py              # EXTENDED — new TestMilestoneCliSubcommands
                            # class (mirrors TestWorkCliSubcommands at
                            # tests/test_cli.py:2523); TestWorkCliSubcommands
                            # itself unchanged.
```

**Structure Decision**: Single-project layout, unchanged from 001/002/003. One new module (`milestone_review.py`) is added because it is a genuinely new, human-review-facing concern — deliberately not folded into `symphony_projection.py` (whose own module framing and naming are Symphony/coordinator-specific, per 003's plan.md "Structure Decision": "no Spec-Kit- or Symphony-specific naming or behavior" is the bar for what belongs in `work_ledger.py` itself, and by the same logic, reviewer-specific framing does not belong in the Symphony-named module either) and not folded into `work_ledger.py` itself (whose own docstring already disclaims becoming any kind of adapter). The two new, generic, coordinator-agnostic primitives this feature needs from the ledger (`list_evidence`, `get_claim`) are added to `work_ledger.py` in place, per this repository's "extend before replace" precedent (`AGENTS.md`) — exactly the same placement decision 003 made for `resync_declarative_fields`/`generate_external_projection`.

## Complexity Tracking

Not applicable — no Constitution Check violation requires justification.
