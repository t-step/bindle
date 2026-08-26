# Implementation Plan: Durable Work Ledger

**Branch**: `spec/durable-work-item-model` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-durable-work-ledger/spec.md`

**Note**: This is an architecture/ownership plan, not an implementation plan. No ledger code, no `bindle init`/CLI wiring, and no Symphony adapter are produced by this plan or by this feature. The plan exists so a future implementation session can build the smallest first slice without reopening the ownership/model question — per this repository's own explicit brief for this work.

## Summary

Bindle needs a durable record of decomposed implementation work that survives individual agent sessions, worktrees, branches, and context loss, without becoming a scheduler, a workflow engine, or a second copy of user history. The technical approach: a **repository-scoped, machine-local, untracked coordination ledger** — one plain-text record per work item, holding a small set of orthogonal facts (status, blocking, evidence, source pointer), plus a **separate, atomically-created claim record per claimed item** so concurrent claim attempts on the same item are unambiguously arbitrated by a filesystem primitive rather than a read-modify-write race — stored at the Git common directory (shared across every linked worktree on this machine, per `docs/WORKTREES.md`'s identity model), the same architectural slot Projectmem (D022/D033) and QMD (D036) already occupy for their own repository-scoped, non-git-tracked state. Archiving a completed item leaves behind a permanent, minimal tombstone so other items' dependency relationships to it remain resolvable forever, without retaining the rest of its content. The ledger is the durable source a future, disposable projection is generated *from* for an external coordinator (Symphony); it is never generated from the coordinator, and the coordinator never becomes its schema. No SQLite, no daemon, no scheduler, no dependency/DAG solver.

## Technical Context

**Language/Version**: Python 3.11+ (matches `pyproject.toml`'s `requires-python`; this plan does not introduce a new language or runtime).

**Primary Dependencies**: None beyond the Python standard library — matching this project's existing zero-dependency posture (`bindle.toml` itself is read via stdlib `tomllib`; no TOML-writing dependency exists or is proposed). No sqlite3 driver dependency is needed either (`sqlite3` is stdlib), which means the recommendation below is not driven by dependency weight — see research.md.

**Storage**: One plain-text file per work item, TOML-formatted (see research.md, "Decision: storage format"), under a repository-scoped, untracked directory resolved from the Git common directory (see research.md, "Decision: storage location"). Claims are separate, atomically-created sibling files keyed by item id (research.md, "Decision: claim atomicity"); archived items leave a small permanent tombstone file (research.md, "Decision: retention" / "Decision: dependency resolution across archival"). All three remain the same plain-file format — no database engine.

**Testing**: `pytest` (matches this repository's existing `tests/` convention; no new test framework).

**Target Platform**: Same as the rest of `bindle` — a Python CLI/library invoked locally (macOS/Linux dev machines), no server component.

**Project Type**: Single Python package (`src/bindle/`), consistent with the existing flat provider-module layout (`repo.py`, `guardrails.py`, `projectmem.py`, `qmd.py`).

**Performance Goals**: N/A at this scale — a repository is expected to carry a handful to a few dozen concurrently-relevant work items, not thousands; no indexing or query-performance goal is set by this plan (see research.md, "Decision: storage format" for the scale reasoning).

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
| Durability (D015) — Bindle-owned state limited to configuration/cache/export | **CONDITIONAL PASS, with an explicit scope note** — see research.md's "Decision: ownership." The ledger is a new kind of Bindle-owned state (bounded coordination state, not narrative history) that does not cleanly fit the existing "configuration / disposable cache / explicit export" three-way split. This plan does not silently stretch that language; it names the gap and defers closing it to a future `docs/DECISIONS.md` entry made only once a first slice is actually observed working (mirroring D037's own reference-before-adoption posture). Not a violation, but not yet a fully closed gate either — see "genuinely unresolved" in the final report. |
| Preservation (D016) — capture requires a reason | **PASS** | Every field in the model (data-model.md) exists to answer a scenario from spec.md; no transcript, event log, or narrative history is captured. |
| Worktrees (D018) — repository identity is the Git common directory | **PASS** | Storage location (research.md) is explicitly resolved from the Git common directory, matching `RepoInfo.repo_root`'s own resolution in `src/bindle/repo.py`, not the invoking worktree. |
| No scheduler / no dependency-DAG solver (exploration plan's explicit rejections) | **PASS** | data-model.md's `blocked_by` is a flat reference list with a boolean eligibility fold, not a graph library, topological sort, or priority queue. No ranking or ordering logic is introduced. |
| No generic Component/Provider framework (D033/D035 closing precedent) | **PASS** | This plan proposes one purpose-built module for one purpose-built shape, exactly like `projectmem.py`/`qmd.py`, not a generic abstraction. |
| Concurrent claim correctness (FR-018, SC-004a) without reopening storage format | **PASS** | research.md's "Decision: claim atomicity" resolves the read-modify-write race with a directory-entry-level exclusive-create primitive on a separate per-item file — still plain files, no database; see research.md for why this reconfirms rather than undermines the storage-format decision. |
| Dependency truth survives archival (FR-020/FR-021) without a permanent history store | **PASS** | research.md's "Decision: dependency resolution across archival" resolves this with a fixed three-field Tombstone per archived item, not a growing log — see the Durability gate note above; this is the same shape of state as the ledger itself, not a new kind of permanent-history exception. |

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
└── tasks.md             # NOT created — see AGENTS.md instruction for this feature: do not run /speckit.tasks
```

### Source Code (repository root)

No source code is created or modified by this plan. The layout below documents where a **future** implementation session would add the ledger, following this repository's existing flat per-provider module convention (`src/bindle/repo.py`, `guardrails.py`, `projectmem.py`, `qmd.py`) — nothing under this tree exists yet:

```text
src/bindle/
├── repo.py              # existing — RepoInfo, used by the future ledger for storage-location resolution
├── projectmem.py        # existing — sibling provider-lifecycle precedent (D033)
├── qmd.py               # existing — sibling provider-lifecycle precedent (D036)
└── work_ledger.py        # FUTURE, not created by this plan — read/list/create/claim/reconcile/project functions

tests/
└── test_work_ledger.py   # FUTURE, not created by this plan
```

**Structure Decision**: Single-project layout (Option 1), matching the existing `src/bindle/` package. No new top-level project, service, or directory tree. `work_ledger.py` is a name choice for illustration only — the first implementation slice may choose a different module name; this plan does not fix it.

## Complexity Tracking

Not applicable — no Constitution Check violation requires justification.
