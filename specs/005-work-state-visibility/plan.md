# Implementation Plan: Work-State Visibility

**Branch**: `spec/work-state-visibility` | **Date**: 2026-08-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/005-work-state-visibility/spec.md`

**Baseline**: `specs/001-durable-work-ledger/`, `specs/002-milestone-task-work-items/`, `specs/003-symphony-task-integration/`, and `specs/004-milestone-review-surface/` are fully implemented (`src/bindle/work_ledger.py`, `src/bindle/milestone_review.py`, `src/bindle/symphony_projection.py`, `src/bindle/cli.py`; adopted in `docs/DECISIONS.md` D038/D039/D040/D041/D042; `bindle init` unconditionally provisions both SQLite artifacts per D043/D044). This plan builds no new lifecycle behavior and reopens none of specs/001–004's own settled decisions — every semantic fact this feature reports is read, verbatim, from an existing `WorkLedger`/`milestone_review` method, and every existing method's own external behavior/return value is unchanged. `work_ledger.py` gains exactly one small addition — a pure, stateless `is_dispatchable(status, claimed, blocked) -> bool` function factoring out the non-blocking two-thirds of `list_available_work_items()`'s own existing SQL predicate. `list_available_work_items()`'s own internal implementation is refactored to route through this function per candidate row, so the identical live-state and read-only forecast-counterfactual paths share one authoritative Python expression of the rule rather than two independently-maintained ones (spec.md review correction; Research: "dispatchable-next shares one authoritative predicate"). This is the same rule, given one authoritative Python home — not a new predicate, and not a change to what any existing method reports (external behavior and return value are unchanged, verified by its own existing test suite). The only other genuinely new computation is the dependency-frontier reverse relation itself (spec.md FR-012c), a pure in-memory relate over already-fetched facts.

## Summary

One new semantic-composition module (`src/bindle/work_status.py`), one small addition to `work_ledger.py`, and CLI additions in `cli.py` (`bindle work status`, `bindle work forecast`, nested under the existing `work` subparser). `work_status.py` owns exactly one read-model constructor, `build_snapshot(ledger) -> WorkStatusSnapshot`, composed entirely from `WorkLedger.list_work_items()`/`list_available_work_items()`/`list_blocking()`/`get_claim()` and `milestone_review.review_milestone()` — one ledger pass per invocation, never a second independently-derived computation of any fact. `bindle work forecast`'s dependency frontier (`DependencyFrontier`, `build_forecast(snapshot)`) is a pure, in-memory relation computed *from* an already-built `WorkStatusSnapshot`'s per-item blocking/status/claim facts — it never re-queries the ledger and never mutates or simulates anything. Its `dispatchable_next` counterfactual calls one new, narrow, pure function — `work_ledger.is_dispatchable(status, claimed, blocked) -> bool` — the single authoritative Python expression of the exact three-conjunct rule `list_available_work_items()`'s own SQL already encodes; `list_available_work_items()`'s own internal implementation is refactored to route through this same function (its external behavior and return value are unchanged, verified by its own existing test suite), so live-state and counterfactual dispatchability share actual code, never two independently-maintained expressions of the same rule (Research: "dispatchable-next shares one authoritative predicate"). `bindle work status --json` serializes the identical `WorkStatusSnapshot` object the plain-text renderer reads (`contracts/work-status-json-v1.md`).

**Scope note (post-implementation reconciliation)**: this plan originally also scoped a fifth surface, `bindle view` — a loopback-only, stdlib-`http.server`-based, server-rendered HTML page over the identical read model, with Symphony runtime enrichment (FR-020) deferred entirely in an initial cut. That surface was evaluated for adoption after the `work_status.py`/CLI scope above already existed and working, and was declined — no repeated, observed friction demonstrated a need for a Bindle-hosted visual surface once the CLI/JSON/NDJSON interfaces existed (`docs/DECISIONS.md` D045). This plan's implementation, and this document's remaining sections, describe the `work_status.py` + `bindle work status`/`bindle work forecast` scope only; no `view.py` module, HTTP server, or Symphony-facing code exists in this feature.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from 001–004; matches `pyproject.toml`).

**Primary Dependencies**: None beyond the standard library — unchanged from 001–004 (`pyproject.toml` declares zero runtime dependencies today). `sqlite3` (via `WorkLedger`, unmodified), `argparse`, `dataclasses`, `json` (already imported by `cli.py`), and `time`/`signal` (stdlib) for the `--watch` loop. No `rich`/`textual`/`curses`/`flask`/`jinja2` or any other new dependency is introduced.

**Storage**: The existing internal `ledger.sqlite3` only (`WorkLedger`), read through existing public methods plus one new pure, I/O-free function (`is_dispatchable()` — no new query, no schema access at all). No new table, column, or `_SCHEMA_VERSION` bump (spec.md Non-Goals, SC-011) — this feature is read-only end to end.

**Testing**: `pytest`. A new `tests/test_work_status.py` (mirrors the one-module-one-test-file convention `milestone_review.py`/`test_milestone_review.py` already establishes) covering `build_snapshot()`/`build_forecast()` against constructed ledger fixtures, including a matrix test asserting `is_dispatchable(status, claimed, blocked)` agrees with `list_available_work_items()`'s own return value for every constructed task in a fixture ledger — a regression guard on `list_available_work_items()`'s internal refactor described in this plan's Baseline and Constitution Check, not the mechanism that establishes agreement (the shared function call is) (Research: "dispatchable-next shares one authoritative predicate"). Additions to `tests/test_work_ledger.py` for `is_dispatchable()` itself (a small, pure-function truth-table test); `list_available_work_items()`'s existing test class is re-run unmodified to confirm its external behavior/return value is unchanged by the internal refactor. Additions to `tests/test_cli.py` for the new `bindle work status|forecast` subcommands, mirroring `TestMilestoneCliSubcommands`/`TestWorkCliSubcommands`.

**Target Platform**: Same as 001–004 — local Python CLI/library, macOS/Linux.

**Project Type**: Single Python package (`src/bindle/`), unchanged. One new module added within it.

**Performance Goals**: N/A at this scale, unchanged from 001–004 — a repository's own handful-to-dozens of work items. `build_snapshot()` is `O(work items)` ledger calls (one `get_claim`/`list_blocking` per item, one `review_milestone()` per milestone); `build_forecast()` is a pure in-memory `O(work items)` relate over the snapshot's already-fetched facts — no additional ledger I/O.

**Constraints**: Must not modify `specs/001`–`004`'s own artifacts, schema, lifecycle methods, or write surfaces (spec.md Baseline, Non-Goals). Must never introduce a second, independently-maintained computation of dispatchable/blocked/review-ready (spec.md FR-002/FR-003/FR-004/FR-012, Terminology). Must never poll or refresh without explicit `--watch` (spec.md FR-006/FR-009, Non-Goals). Must never install, start, stop, configure, or supervise Symphony, and must introduce no `bindle symphony ...` command (`docs/SYMPHONY.md` Non-scope). Must produce byte-identical `--json` output across two invocations against an unchanged ledger (spec.md SC-004) — this rules out embedding any wall-clock "computed at" value inside the serialized snapshot itself (Research: "No timestamp field in the JSON contract").

**Scale/Scope**: Unchanged from 001–004 — one repository's own work, single machine, one or more linked worktrees.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` remains the unfilled Spec Kit template (unchanged from 001–004's own finding, verified this session). This repository's operative constitution remains `AGENTS.md` ("Architecture rules") and `docs/PHILOSOPHY.md`, per repo-local precedence — unchanged posture from prior plans.

Gates evaluated:

| Gate | Status | Basis |
|---|---|---|
| No second, independently-maintained dispatchable/blocked/review-ready predicate (spec.md FR-002/FR-003/FR-004/FR-012, Terminology) | **PASS** | `build_snapshot()` calls `list_available_work_items()` directly for the dispatchable-task id set (not a re-derived boolean), `list_blocking()` verbatim for blocking ids, and `milestone_review.review_milestone()` verbatim for readiness/reason. `build_forecast()`'s unblocked-next/dispatchable-next relation is computed only from those same already-fetched values — see Research: "Forecast is a pure relate over snapshot facts, not a new predicate." |
| Exactly one authoritative definition of task dispatchability, evaluated identically against live state and a read-only counterfactual (this review's own item 3) | **PASS** | `is_dispatchable(status, claimed, blocked) -> bool` (new, `work_ledger.py`) is the single Python expression of the rule; `list_available_work_items()`'s own internal implementation is refactored to route through it (external behavior/return value unchanged, verified by its own existing test suite), and `build_forecast()`'s `dispatchable_next` calls the identical function with `blocked` fixed to the counterfactual's own assumption — genuine shared code on both the live and counterfactual paths, not two independently-maintained expressions kept in sync by a test — see Research: "dispatchable-next shares one authoritative predicate." |
| No new persisted state, table, column, or `_SCHEMA_VERSION` bump (spec.md Non-Goals, SC-011) | **PASS** | Every new function is a read composer or a pure in-memory transform; nothing in this feature calls any `WorkLedger` mutation method. |
| No event log / activity history (spec.md Non-Goals) | **PASS** | `WorkStatusSnapshot` holds only current-state facts already available from existing reads; nothing is accumulated across invocations or renders. |
| No automatic/implicit polling; `--watch` is explicit opt-in on `bindle work status` (spec.md FR-006/FR-009, Non-Goals) | **PASS** | Absent `--watch`, `bindle work status` performs exactly one `build_snapshot()` call and exits — watch state is a per-process CLI flag, never persisted. |
| No persistent background daemon (spec.md Non-Goals) | **PASS** | `bindle work status --watch`'s loop runs only for the invoking process's own lifetime and stops cleanly on `KeyboardInterrupt` — see Research: "Watch/serve shutdown behavior." |
| No `bindle symphony ...` command; Bindle never installs/starts/stops/supervises Symphony (`docs/SYMPHONY.md` Non-scope) | **PASS** | This feature adds no Symphony-facing code, flag, config field, or UI element of any kind — a local visual surface that would have optionally composed Symphony runtime facts was evaluated and declined (`docs/DECISIONS.md` D045); Symphony grounding recorded in Research remains historical context for that declined evaluation. |
| No new ledger table/column; SC-011 holds unchanged | **PASS** | Confirmed by inspection of every function this plan adds — all are reads or pure in-memory transforms over existing `WorkLedger` return values. |
| No raw SQL / DB handle exposed as the contract (`AGENTS.md`, mirrors 003/004's same gate) | **PASS** | `work_status.py`'s public surface is dataclasses and two builder functions; `bindle work status --json`'s contract is a documented JSON shape (`contracts/work-status-json-v1.md`), never a database file or connection. |
| Worktrees (D018) — every linked worktree sees the same ledger state | **PASS** | `work_status.py`'s functions take an already-resolved `WorkLedger` (from `RepoInfo.repo_root`, the Git common directory) exactly like `milestone_review.py`/`symphony_projection.py` already do — no new path resolution introduced. |
| No unjustified new dependency (`AGENTS.md`, "Inherit first... Invent last") | **PASS** | Every new piece of this feature uses only the standard library, matching 001–004's own "None beyond the standard library" precedent. |

No unjustified violations. Complexity Tracking is not filled in below because none apply.

## Project Structure

### Documentation (this feature)

```text
specs/005-work-state-visibility/
├── plan.md                        # This file
├── research.md                    # Phase 0 output
├── data-model.md                  # Phase 1 output
├── quickstart.md                  # Phase 1 output
├── contracts/                     # Phase 1 output
│   └── work-status-json-v1.md
└── tasks.md                       # Phase 2 output ($speckit-tasks) — NOT produced by this plan
```

### Source Code (repository root)

```text
src/bindle/
├── work_ledger.py          # EXTENDED, narrowly — every read this feature
│                           # needs (list_work_items, list_available_work_items,
│                           # list_blocking, get_claim, is_review_ready)
│                           # already exists and is already tested and is
│                           # UNCHANGED in behavior. One addition: a pure,
│                           # stateless is_dispatchable(status, claimed,
│                           # blocked) -> bool function, factoring out the
│                           # non-blocking two-thirds of
│                           # list_available_work_items()'s own existing SQL
│                           # predicate so a read-only counterfactual
│                           # (forecast) can evaluate the identical rule.
│                           # list_available_work_items()'s own internal
│                           # implementation is refactored to route through
│                           # this function (its external behavior/return
│                           # value is unchanged, per its existing tests) —
│                           # see Research: "dispatchable-next shares one
│                           # authoritative predicate."
├── milestone_review.py     # UNCHANGED — review_milestone() is called
│                           # verbatim, once per milestone, by
│                           # work_status.build_snapshot().
├── symphony_projection.py  # UNCHANGED — this feature composes a
│                           # human-facing view, not a second published
│                           # projection; it does not read or write
│                           # symphony-projection.sqlite3 at all.
├── work_status.py          # NEW — the one semantic read-model module:
│                           # WorkStatusSnapshot/TaskStatusEntry/
│                           # MilestoneStatusEntry (Phase 1 data-model.md),
│                           # build_snapshot(ledger), DependencyFrontier/
│                           # ForecastEntry, build_forecast(snapshot),
│                           # plain-text renderers for both, and a
│                           # snapshot_to_json()-shaped serialization
│                           # helper consumed by cli.py's --json path.
│                           # Also owns the --watch interval
│                           # default/minimum constants (spec.md FR-011).
└── cli.py                  # EXTENDED — `bindle work status`
                            # [--json] [--watch] [--interval SECONDS] and
                            # `bindle work forecast`, nested under the
                            # existing `work` subparser group, alongside
                            # claim/release/done/load-speckit/publish —
                            # spec.md names both as `bindle work ...`.

tests/
├── test_work_ledger.py      # EXTENDED — a small truth-table test for the
│                            # new is_dispatchable(); existing
│                            # list_available_work_items() test class
│                            # unchanged (its behavior does not change).
├── test_work_status.py      # NEW — build_snapshot()/build_forecast()
│                            # against constructed ledger fixtures; JSON
│                            # determinism (SC-004); text/JSON fact parity
│                            # (SC-003); is_dispatchable() vs.
│                            # list_available_work_items() coherence.
└── test_cli.py              # EXTENDED — new TestWorkStatusCliSubcommands
                             # class; every existing test class unchanged.
```

**Structure Decision**: Single-project layout, unchanged from 001–004. One new module: `work_status.py` is the semantic composition/read-model layer (no I/O beyond `WorkLedger` calls, no rendering-medium-specific code — mirrors `milestone_review.py`'s own "composition module, not a CLI module" placement). `bindle work status`/`bindle work forecast` nest under the existing `work` subparser (spec.md itself names them this way, and both report task-centric facts already owned by that namespace). A rendering-medium-specific module (`view.py`, an HTTP-serving `bindle view` surface) was scoped in this plan's earlier draft but was evaluated and declined before implementation — no such module exists in the delivered project structure (`docs/DECISIONS.md` D045).

## Complexity Tracking

Not applicable — no Constitution Check violation requires justification.
