# Implementation Plan: Milestone and Task Work Items

**Branch**: `spec/milestone-task-work-item-model` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-milestone-task-work-items/spec.md`

**Baseline**: `specs/001-durable-work-ledger/` is fully implemented (`src/bindle/work_ledger.py`, `tests/test_work_ledger.py`, schema version 1). This plan extends that same module and schema in place — no new file, no new persistence technology, no new storage location.

## Summary

Add a `type` (`task` | `milestone`) and `parent_id` column to the existing `work_items` table, replace its flat `status` `CHECK` with a compound `(type, status)` `CHECK` covering both vocabularies, and add derived-query support for "qualifying mechanical evidence" (a done task) and "review readiness" (a milestone) — no new stored facts. Extend the existing guarded-transition pattern (`mark_done`/`mark_superseded`) with milestone-specific transitions (`mark_in_review`, `decline_review`, `accept_milestone`) and two archival preconditions (`archive_work_item` refuses when a milestone still has unresolved children, and separately refuses to archive an attributed task while its parent milestone is still open or in review, since archival deletes the task's own evidence and could otherwise invalidate the parent's review-readiness underneath it). Extend `generate_projection()` to filter to `type = 'task'` only. Bump `_SCHEMA_VERSION` to 2 with a forward migration for existing databases (`ALTER TABLE` to add columns, backfill `type = 'task'` for all pre-existing rows, replace the `CHECK` constraint via SQLite's table-rebuild pattern since SQLite cannot `ALTER` a `CHECK` in place). No new module, no new top-level dependency, no new CLI surface.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from 001; matches `pyproject.toml`).

**Primary Dependencies**: None beyond the standard library — unchanged from 001. `sqlite3` (stdlib) only.

**Storage**: The same single SQLite database file at the Git-common-directory-resolved location 001 already established (`ledger_path()` in `src/bindle/work_ledger.py`, unchanged). This feature adds `type` and `parent_id` columns to `work_items` and does not add a new table (per spec.md's Assumptions: no rename of `work_item_blocked_by`, no subtype tables).

**Testing**: `pytest`, extending `tests/test_work_ledger.py` in place (unchanged framework and file, per 001's own convention of one implementation module and one test module).

**Target Platform**: Same as 001 — local Python CLI/library, macOS/Linux.

**Project Type**: Single Python package (`src/bindle/`), unchanged.

**Performance Goals**: N/A at this scale, unchanged from 001 — a milestone's review-readiness query joins over a repository's own handful-to-dozens of work items, not a scale requiring indexing beyond existing primary/foreign keys.

**Constraints**: Must not require a running coordinator, daemon, or network access (unchanged from 001). Must not break any existing 001 caller: every existing 001 public function signature (`create_work_item`, `get_work_item`, `list_work_items`, `add_blocked_by`, `is_blocked`, `is_claimed`, `list_available_work_items`, `mark_done`, `mark_superseded`, `claim`, `release_claim`, `override_release_claim`, `add_evidence`, `reconcile`, `generate_projection`, `archive_work_item`) must continue to work unchanged for `type = 'task'` items with no `parent_id` — 001's own test suite (`tests/test_work_ledger.py`, all 8 existing test classes) must continue to pass without modification to its assertions, only extended with new test classes/cases for the new behavior. An existing on-disk schema-version-1 database must open cleanly under the new code via a forward migration, not require manual intervention or data loss.

**Scale/Scope**: Unchanged from 001 — one repository's own work, single machine, one or more linked worktrees.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` remains the unfilled Spec Kit template (verified this session). This repository's operative constitution remains `AGENTS.md` ("Architecture rules") and `docs/PHILOSOPHY.md`, per repo-local precedence — unchanged posture from 001's own plan.

Gates evaluated:

| Gate | Status | Basis |
|---|---|---|
| No generalized workflow engine (`AGENTS.md`) | **PASS** | spec.md FR-018 explicitly forbids introducing a transition-validating state machine beyond the guarded-`UPDATE` pattern 001 already uses for `mark_done`/`mark_superseded`; this plan's new transitions (`mark_in_review`, `decline_review`, `accept_milestone`) follow that exact existing pattern, not a new mechanism. |
| No speculative subtype tables (normalization critique, pre-spec) | **PASS** | A single typed `work_items` table is used — no `milestones`/`tasks` split table, per spec.md's Key Entities and the independent normalization critique performed before spec.md was written (no milestone-only or task-only attribute was found to justify one). |
| Derived facts stay derived (001's existing "Derived facts" precedent, spec.md FR-019) | **PASS** | "Qualifying mechanical evidence" and "review readiness" are both plain `SELECT`/`EXISTS` queries added to `work_ledger.py`, never stored columns — the same shape as 001's existing `is_blocked`/`is_claimed`/`list_available_work_items`. |
| No priority/scheduling state (001 FR-015, spec.md FR-019) | **PASS** | No `priority` column or dispatch-order logic is introduced anywhere in this feature. |
| Milestone review rationale routed correctly (`docs/DATA-OWNERSHIP.md`) | **PASS** | spec.md FR-014 keeps rationale out of the ledger; only the coarse status transition and an optional evidence pointer are stored, mirroring 001's existing claim-override-note pattern. |
| Backward compatibility for existing ledger data | **PASS, with an explicit migration** | See Phase 0 research.md "Decision: schema migration from version 1 to version 2" — a forward `ALTER TABLE`/table-rebuild migration is required because SQLite cannot alter a `CHECK` constraint in place; this is new work this feature must do that 001 (a fresh-schema feature) did not need. |
| Worktrees (D018) — no change to storage location | **PASS** | No change to `ledger_path()` or connection resolution; only the schema inside the same file changes. |
| Symphony boundary unchanged (001 FR-012–FR-015, D037) | **PASS** | spec.md FR-017 only filters the existing coordinator-agnostic projection by type; no Symphony adapter code, no new field naming borrowed from Symphony's own vocabulary, per spec.md's own Assumptions. |

No unjustified violations. Complexity Tracking is not filled in below because none apply.

## Project Structure

### Documentation (this feature)

```text
specs/002-milestone-task-work-items/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── coordinator-projection-v2.md
└── tasks.md             # Phase 2 output ($speckit-tasks)
```

### Source Code (repository root)

No new files. This feature extends the existing 001 implementation in place:

```text
src/bindle/
└── work_ledger.py        # EXTENDED — schema v2 (type, parent_id, compound CHECK),
                           # migration from v1, new derived-query helpers
                           # (mechanical evidence, review readiness), new guarded
                           # transitions (mark_in_review, decline_review,
                           # accept_milestone), archival preconditions for
                           # milestones with unresolved children and for
                           # attributed tasks whose parent is still
                           # open/review, projection filtered to type='task'

tests/
└── test_work_ledger.py   # EXTENDED — existing 8 test classes unchanged;
                           # new test classes for type/parent_id, milestone
                           # lifecycle, review readiness, milestone archival,
                           # task-archival parent-lifecycle preconditions,
                           # projection type-filtering, and v1→v2 migration
```

**Structure Decision**: Single-project layout, unchanged from 001. No new top-level directory, module, or dependency.

## Complexity Tracking

Not applicable — no Constitution Check violation requires justification.
