# Implementation Plan: Durable Work Ledger

**Branch**: `spec/durable-work-item-model` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-durable-work-ledger/spec.md`

**Note**: This is an architecture/ownership plan, not an implementation plan. No ledger code, no `bindle init`/CLI wiring, and no Symphony adapter are produced by this plan or by this feature. The plan exists so a future implementation session can build the smallest first slice without reopening the ownership/model question — per this repository's own explicit brief for this work.

**2026-08-26 persistence-model correction**: this plan's Summary, Technical Context, and Constitution Check below are revised to reflect a SQLite-backed persistence mechanism, superseding the original plain-per-item-TOML-file approach — an intentional, directed override, not a reopened storage-format evaluation. See `research.md`'s "Decision: storage format" for the full rationale and the preserved original decision text. Nothing else about this feature's scope changes: still specification/planning-only, still no ledger code, `bindle init` wiring, or Symphony adapter produced here.

**2026-08-26 task-generation scope correction**: this feature was originally scoped, by explicit prior direction, to stop at planning artifacts — the Project Structure section below previously read `tasks.md # NOT created — see AGENTS.md instruction for this feature: do not run /speckit.tasks`. That deferral is intentionally lifted as of this correction: the amended, SQLite-corrected 001 package (this plan plus research.md/data-model.md/quickstart.md/contracts/) is now treated as sufficiently settled to generate `tasks.md` and to run task-composition/orchestration analysis against the resulting task graph. This is a directed scope decision, not a reopened evaluation of whether task generation belongs in this feature. It still does not authorize writing ledger code, `bindle init` wiring, or a Symphony adapter, and does not itself dispatch any implementation subagent — those remain future work, per this plan's own unchanged framing above.

## Summary

Bindle needs a durable record of decomposed implementation work that survives individual agent sessions, worktrees, branches, and context loss, without becoming a scheduler, a workflow engine, or a second copy of user history. The technical approach: a **repository-scoped, machine-local, untracked coordination ledger** — a single small SQLite database holding a small set of orthogonal facts per work item (status, blocking, evidence, source pointer) across a handful of tables, with a **dedicated claims table whose primary key arbitrates concurrent claim attempts** so that of any number of concurrent attempts on the same item, exactly one succeeds via SQLite's own constraint enforcement rather than a bespoke filesystem protocol — stored at the Git common directory (shared across every linked worktree on this machine, per `docs/WORKTREES.md`'s identity model), the same architectural slot Projectmem (D022/D033) and QMD (D036) already occupy for their own repository-scoped, non-git-tracked state. Archiving a completed item thins its row in place, within one transaction, to a permanent minimal record (`id`, `status`, `superseded_by`, `archived_at`) so other items' dependency relationships to it remain resolvable forever, without retaining the rest of its content. The ledger is the durable source a future, disposable projection is generated *from* for an external coordinator (Symphony); it is never generated from the coordinator, and the coordinator never becomes its schema. SQLite, but no daemon, no scheduler, no dependency/DAG solver, no ORM, and no hosted database service.

## Technical Context

**Language/Version**: Python 3.11+ (matches `pyproject.toml`'s `requires-python`; this plan does not introduce a new language or runtime).

**Primary Dependencies**: None beyond the Python standard library — matching this project's existing zero-dependency posture. `sqlite3` (stdlib) is used directly, with no ORM or third-party driver, exactly as `bindle.toml` is already read via stdlib `tomllib` — this decision is not driven by dependency weight, since a dependency was never the concern; see research.md's "Decision: storage format" for what actually changed.

**Storage**: A single SQLite database file at a repository-scoped, untracked location resolved from the Git common directory (see research.md, "Decision: storage location"), holding `work_items`, `work_item_blocked_by`, `work_item_claims`, and `work_item_evidence` tables (research.md, "Decision: storage format"; data-model.md for the full schema). Claims are rows in a dedicated table arbitrated by a primary-key constraint (research.md, "Decision: claim atomicity"); archived items are thinned in place within the same table, not moved to a separate artifact (research.md, "Decision: retention" / "Decision: dependency resolution across archival").

**Testing**: `pytest` (matches this repository's existing `tests/` convention; no new test framework).

**Target Platform**: Same as the rest of `bindle` — a Python CLI/library invoked locally (macOS/Linux dev machines), no server component.

**Project Type**: Single Python package (`src/bindle/`), consistent with the existing flat provider-module layout (`repo.py`, `guardrails.py`, `projectmem.py`, `qmd.py`).

**Performance Goals**: N/A at this scale — a repository is expected to carry a handful to a few dozen concurrently-relevant work items, not thousands; no indexing beyond the schema's own primary/foreign keys, and no query-performance goal, is set by this plan (see research.md, "Decision: connection lifecycle and concurrency" for the scale reasoning).

**Constraints**: Must not require a running coordinator, daemon, or network access to create, read, claim, or reconcile a work item (`AGENTS.md`, "On when in use" posture; `docs/SCOPE.md`, "Bindle does not own... generic project management"). Must remain correct if a worktree referenced by a claim is deleted mid-work.

**Scale/Scope**: One repository's own decomposed implementation work, single machine, one or more linked worktrees, one or more concurrently active agents/sessions. Cross-machine sharing of in-flight coordination state is explicitly out of scope for this slice (see research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` in this repository is still the unfilled Spec Kit template — no project-specific principles have been ratified into it (verified this session by reading the file directly). This repository's own governing architecture rules instead live in `AGENTS.md` ("Architecture rules") and `docs/PHILOSOPHY.md` (the replaceability/durability/preservation rules and the nine-criteria feature admission test), which this plan treats as the operative constitution, per this repository's own stated precedence (repo-local instructions take precedence over generic tooling defaults).

Gates evaluated against those rules:

| Gate | Status | Basis |
|---|---|---|
| Ownership answered before design (`AGENTS.md`, "Architecture rules") | **PASS** | research.md's "Decision: ownership" resolves who owns the ledger before any schema/storage choice is made, per the required order. |
| Replaceability (D014) — no parsing of another tool's private store | **PASS** | The ledger never parses Symphony's, Git's, or GitHub's internal formats; it produces a disposable projection *for* a coordinator and holds pointers (branch, commit, PR) to provider-owned state rather than copies. |
| Durability (D015) — Bindle-owned state limited to configuration/cache/export | **CONDITIONAL PASS, with an explicit scope note — unaffected by the persistence-format correction** — see research.md's "Decision: ownership." The ledger is a new kind of Bindle-owned state (bounded coordination state, not narrative history) that does not cleanly fit the existing "configuration / disposable cache / explicit export" three-way split. This gate's reasoning is about *ownership*, not physical format — choosing SQLite over plain files changes nothing about whether the ledger's category needs its own `docs/DECISIONS.md` acknowledgment, so this correction does not narrow or widen the gap. This plan does not silently stretch that language; it names the gap and defers closing it to a future `docs/DECISIONS.md` entry made only once a first slice is actually observed working (mirroring D037's own reference-before-adoption posture). Not a violation, but not yet a fully closed gate either — see "genuinely unresolved" in the final report. |
| Preservation (D016) — capture requires a reason | **PASS** | Every column in the model (data-model.md) exists to answer a scenario from spec.md; no transcript, event log, or narrative history is captured. Archival's column-thinning (data-model.md, "Archival") is the same preservation discipline applied to the new schema, not a relaxation of it. |
| Worktrees (D018) — repository identity is the Git common directory | **PASS** | Storage location (research.md) is explicitly resolved from the Git common directory, matching `RepoInfo.repo_root`'s own resolution in `src/bindle/repo.py`, not the invoking worktree — every linked worktree opens the same physical SQLite file. |
| No scheduler / no dependency-DAG solver (exploration plan's explicit rejections) | **PASS** | data-model.md's `blocked_by` is a flat edge table with a boolean eligibility fold and a recursive-CTE reachability query for cycle detection — a graph-reachability *query*, not a graph library, topological sort, priority queue, or solver. No ranking or ordering logic is introduced. |
| No generic Component/Provider framework (D033/D035 closing precedent) | **PASS** | This plan proposes one purpose-built module using `sqlite3` (stdlib) directly, exactly like `projectmem.py`/`qmd.py` use their own respective tools directly, not a generic abstraction and not an ORM. |
| Concurrent claim correctness (FR-018, SC-004a) | **PASS** | research.md's "Decision: claim atomicity" resolves the read-modify-write race with a primary-key constraint on a dedicated `work_item_claims` table, arbitrated by SQLite's own constraint enforcement and single-writer transaction serialization — replacing, not merely relocating, the original file-based exclusive-create primitive. |
| Dependency truth survives archival (FR-020/FR-021) without a permanent history store | **PASS** | research.md's "Decision: dependency resolution across archival" resolves this by thinning a terminal item's row in place to `id`/`status`/`superseded_by`/`archived_at` rather than deleting it — a genuine simplification over the original two-artifact (item file + tombstone file) design, collapsing dependency resolution to a single-table lookup. Still not a growing log — see the Durability gate note above; the same bounded shape of state as before, now expressed as a thinned row instead of a separate tombstone file. |

No unjustified violations. Complexity Tracking is not filled in below because none apply.

## Project Structure

### Documentation (this feature)

```text
specs/001-durable-work-ledger/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── work-item-record.md
│   └── coordinator-projection.md
└── tasks.md             # Phase 2 output — generated 2026-08-26; see this file's "task-generation scope correction" note above (originally deferred, deferral lifted this session)
```

### Source Code (repository root)

No source code is created or modified by this plan. The layout below documents where a **future** implementation session would add the ledger, following this repository's existing flat per-provider module convention (`src/bindle/repo.py`, `guardrails.py`, `projectmem.py`, `qmd.py`) — nothing under this tree exists yet:

```text
src/bindle/
├── repo.py              # existing — RepoInfo, used by the future ledger for storage-location resolution
├── projectmem.py        # existing — sibling provider-lifecycle precedent (D033)
├── qmd.py               # existing — sibling provider-lifecycle precedent (D036)
└── work_ledger.py        # FUTURE, not created by this plan — schema init, read/list/create/claim/reconcile/project functions over sqlite3 (stdlib)

tests/
└── test_work_ledger.py   # FUTURE, not created by this plan
```

**Structure Decision**: Single-project layout (Option 1), matching the existing `src/bindle/` package. No new top-level project, service, or directory tree. `work_ledger.py` is a name choice for illustration only — the first implementation slice may choose a different module name; this plan does not fix it.

## Complexity Tracking

Not applicable — no Constitution Check violation requires justification.
