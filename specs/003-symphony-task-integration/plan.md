# Implementation Plan: Symphony Task Integration

**Branch**: `spec/symphony-task-integration` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-symphony-task-integration/spec.md`

**Baseline**: `specs/001-durable-work-ledger/` and `specs/002-milestone-task-work-items/` are fully implemented (`src/bindle/work_ledger.py`, `tests/test_work_ledger.py`, schema version 2, adopted in `docs/DECISIONS.md` D038). This plan extends that module with two new, generic, coordinator-agnostic primitives, and adds two new, narrowly-scoped modules on top of it for the parts that are genuinely new concerns (Markdown parsing; a second published artifact) rather than ledger schema work.

## Summary

Three additive pieces, each building on the last: (1) `src/bindle/speckit_loader.py`, a narrow parser/loader that reads one Spec Kit feature directory's `tasks.md` and idempotently creates/re-syncs `type='task'` work items via two `work_ledger.py` calls — the existing `create_work_item()` and a new `resync_declarative_fields()` — using a deterministic, source-derived work-item `id` so a reload's `INSERT` collides on the existing primary key and is caught as "already loaded," the same INSERT-collision-as-idempotency shape `claim()` already uses; (2) a new, generic `generate_external_projection()` method on `WorkLedger` (reusing the existing `_STILL_BLOCKING_CONDITION` shared SQL fragment, never duplicating it) plus `src/bindle/symphony_projection.py`, which calls that method and writes its result to a separate, versioned, disposable `.sqlite3` export file distinct from the internal `ledger.sqlite3` — never a live view into the internal file; (3) three thin, type-checked wrapper functions in the same new module (`claim_task`, `release_task`, `complete_task`) built directly on `WorkLedger.claim()`/`release_claim()`/`mark_done()`, exposed as both library functions and a new `bindle work ...` CLI command family in `src/bindle/cli.py`. No change to `work_ledger.py`'s existing schema version, to `generate_projection()`/`ProjectedWorkItem`, or to either existing coordinator-projection contract document.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from 001/002; matches `pyproject.toml`).

**Primary Dependencies**: None beyond the standard library — unchanged from 001/002. `sqlite3` (stdlib) for both the internal ledger and the new export file; `re` (stdlib) for the narrow `tasks.md` line parser; `argparse` (stdlib, already used by `cli.py`) for the new CLI subcommands.

**Storage**: Two SQLite files. The existing internal `ledger.sqlite3` at the Git-common-directory-resolved location `ledger_path()` already establishes (unchanged schema location; `work_items`/`work_item_blocked_by`/`work_item_claims`/`work_item_evidence` unchanged, no new table, no new column). A second, new, disposable file — the published projection — at a sibling path resolved the same way (see research.md, "Decision: published projection storage location and format"), regenerated on demand, never hand-edited, never itself queried by `work_ledger.py`'s own internal code.

**Testing**: `pytest`. New `tests/test_speckit_loader.py` and `tests/test_symphony_projection.py` (mirroring the one-module-one-test-file convention `work_ledger.py`/`test_work_ledger.py` already establishes), plus additions to `tests/test_work_ledger.py` for the two new `WorkLedger` methods and to `tests/test_cli.py` for the new `bindle work` subcommands.

**Target Platform**: Same as 001/002 — local Python CLI/library, macOS/Linux.

**Project Type**: Single Python package (`src/bindle/`), unchanged; two new modules added within it.

**Performance Goals**: N/A at this scale, unchanged from 001/002 — a repository's own handful-to-dozens of work items; no indexing beyond existing primary/foreign keys is needed for either the loader's per-feature scan or the projection's single-pass query.

**Constraints**: Must not require a running coordinator, daemon, or network access (unchanged from 001/002). Must not modify `generate_projection()`, `ProjectedWorkItem`, or either existing coordinator-projection contract document (spec.md FR-019). Must not create a work item as a side effect of anything other than the explicit loading operation (spec.md FR-002). Must not expose raw SQL or a direct database handle as the write-surface contract (spec.md FR-023). Must never let the published projection contain a `type='milestone'` row under any status (spec.md FR-014). An existing on-disk ledger requires no schema migration for this feature — no `_SCHEMA_VERSION` bump, since no `work_items` column or constraint changes.

**Scale/Scope**: Unchanged from 001/002 — one repository's own work, single machine, one or more linked worktrees; one feature directory loaded per invocation of the loader (spec.md FR-001).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` remains the unfilled Spec Kit template (verified this session, unchanged from 001's and 002's own finding). This repository's operative constitution remains `AGENTS.md` ("Architecture rules") and `docs/PHILOSOPHY.md`, per repo-local precedence — unchanged posture from 001/002's own plans.

Gates evaluated:

| Gate | Status | Basis |
|---|---|---|
| `work_ledger.py` never becomes a Symphony/coordinator adapter (module's own docstring) | **PASS** | Every method added directly to `work_ledger.py` (`resync_declarative_fields`, `generate_external_projection`) stays coordinator-agnostic in name and shape — no Symphony-specific field names, no coordinator-specific behavior — mirroring `generate_projection()`'s own existing "deliberately coordinator-agnostic" posture. All Symphony-facing framing (naming, the export file, the write-surface wrappers) lives in the new `src/bindle/symphony_projection.py` module instead, never inside `work_ledger.py` itself. |
| No new arbitration mechanism (spec.md FR-020) | **PASS** | `claim_task`/`release_task`/`complete_task` call `WorkLedger.claim()`/`release_claim()`/`mark_done()` directly and add nothing beyond a type check — no new lock, no new table, no new state machine. |
| No raw SQL / DB handle exposed as the contract (spec.md FR-023, `AGENTS.md`) | **PASS** | The write surface's public shape is three narrow functions (and their CLI wrappers) with fixed inputs/outputs; nothing returns a connection or accepts arbitrary SQL. |
| Published projection stays derived/disposable (D014/D015, `docs/DATA-OWNERSHIP.md` "Durable versus derived") | **PASS** | See research.md, "Decision: published projection storage location and format" — a regenerated, disposable file is chosen precisely because it satisfies this gate; the alternative (a live `CREATE VIEW` into the internal file) was rejected partly on this basis. |
| No generalized Markdown workflow engine (spec.md's own framing, `AGENTS.md` "Discovery... intentionally unassigned") | **PASS** | `speckit_loader.py`'s parser recognizes exactly the one task-line shape `specs/001`/`specs/002` already use (spec.md Assumptions) — it is not a general Markdown/checklist parser and has no extension point for other shapes. |
| No automatic ingestion (spec.md FR-002) | **PASS** | The loader has no file-watcher, no Git hook, and no trigger other than an explicit CLI/library call naming one feature directory. |
| Milestones remain orthogonal (spec.md FR-014, FR-021, FR-024, FR-025) | **PASS** | The loader only ever creates `type='task'` rows (never reads or infers a milestone from a Spec Kit task line — Spec Kit has no milestone concept to begin with); `generate_external_projection()` filters to `type='task'` exactly like `generate_projection()` already does; `claim_task`/`release_task`/`complete_task` each check `type` first and reject a milestone id. |
| Worktrees (D018) — every linked worktree sees the same published artifact | **PASS** | The new export file's path is resolved from `RepoInfo.repo_root` (the Git common directory) exactly like `ledger_path()`, not from the invoking worktree — see research.md. |
| Idempotent reload never resets runtime state (spec.md FR-005, FR-006) | **PASS** | `resync_declarative_fields()` is a guarded `UPDATE` touching only `title`/`description`/`updated_at` — it has no path to `status`, `work_item_claims`, or `work_item_evidence`; the loader's own re-run logic never calls `create_work_item()` a second time for an id it already knows exists (see research.md, "Decision: idempotent reload mechanism"). |

No unjustified violations. Complexity Tracking is not filled in below because none apply.

## Project Structure

### Documentation (this feature)

```text
specs/003-symphony-task-integration/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── speckit-task-load.md
│   ├── symphony-projection-v1.md
│   └── task-write-surface.md
└── tasks.md             # Phase 2 output ($speckit-tasks)
```

### Source Code (repository root)

```text
src/bindle/
├── work_ledger.py          # EXTENDED — two new generic, coordinator-agnostic
│                           # methods: resync_declarative_fields() (guarded
│                           # title/description UPDATE) and
│                           # generate_external_projection() (a second,
│                           # differently-shaped projection query reusing the
│                           # existing _STILL_BLOCKING_CONDITION fragment).
│                           # No schema/version change. generate_projection()
│                           # and ProjectedWorkItem are untouched.
├── speckit_loader.py        # NEW — parses one specs/NNN-slug/tasks.md file
│                           # (the narrow, established task-line shape only),
│                           # derives stable work-item ids and source_locator
│                           # values, and idempotently loads/re-syncs work
│                           # items and their blocked_by edges via WorkLedger.
├── symphony_projection.py   # NEW — writes the published, versioned,
│                           # disposable projection export file from
│                           # generate_external_projection(), and the three
│                           # narrow claim/release/complete write-surface
│                           # wrapper functions (type-checked against
│                           # 'milestone').
└── cli.py                  # EXTENDED — new `bindle work` subcommand family
                            # (load-speckit, publish, claim, release, done),
                            # following the existing repo/skills
                            # nested-subparser convention.

tests/
├── test_work_ledger.py      # EXTENDED — new test classes for
│                           # resync_declarative_fields() and
│                           # generate_external_projection() only;
│                           # every existing test class unchanged.
├── test_speckit_loader.py   # NEW
├── test_symphony_projection.py  # NEW
└── test_cli.py              # EXTENDED — new `bindle work` subcommand tests.
```

**Structure Decision**: Single-project layout, unchanged from 001/002. Two new modules are added because they are genuinely new concerns this feature introduces — Markdown line parsing (`speckit_loader.py`) and a second published external artifact plus its write surface (`symphony_projection.py`) — neither of which belongs inside `work_ledger.py` per that module's own explicit "never a Symphony adapter" boundary (its module docstring) and per `docs/SCOPE.md`'s "not a general Markdown workflow engine" framing. The two new, generic, coordinator-agnostic primitives these modules need from the ledger itself (`resync_declarative_fields`, `generate_external_projection`) are added to `work_ledger.py` in place, per this repository's "extend before replace" precedent — they carry no Spec-Kit- or Symphony-specific naming or behavior, so they don't violate that same boundary.

## Complexity Tracking

Not applicable — no Constitution Check violation requires justification.
