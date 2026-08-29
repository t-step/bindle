# Implementation Plan: Work-State Visibility

**Branch**: `spec/work-state-visibility` | **Date**: 2026-08-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/005-work-state-visibility/spec.md`

**Baseline**: `specs/001-durable-work-ledger/`, `specs/002-milestone-task-work-items/`, `specs/003-symphony-task-integration/`, and `specs/004-milestone-review-surface/` are fully implemented (`src/bindle/work_ledger.py`, `src/bindle/milestone_review.py`, `src/bindle/symphony_projection.py`, `src/bindle/cli.py`; adopted in `docs/DECISIONS.md` D038/D039/D040/D041/D042; `bindle init` unconditionally provisions both SQLite artifacts per D043/D044). This plan builds no new lifecycle behavior and reopens none of specs/001–004's own settled decisions — every semantic fact this feature reports is read, verbatim, from an existing `WorkLedger`/`milestone_review` method, and every existing method's own external behavior/return value is unchanged. `work_ledger.py` gains exactly one small addition — a pure, stateless `is_dispatchable(status, claimed, blocked) -> bool` function factoring out the non-blocking two-thirds of `list_available_work_items()`'s own existing SQL predicate. `list_available_work_items()`'s own internal implementation is refactored to route through this function per candidate row, so the identical live-state and read-only forecast-counterfactual paths share one authoritative Python expression of the rule rather than two independently-maintained ones (spec.md review correction; Research: "dispatchable-next shares one authoritative predicate"). This is the same rule, given one authoritative Python home — not a new predicate, and not a change to what any existing method reports (external behavior and return value are unchanged, verified by its own existing test suite). The only other genuinely new computation is the dependency-frontier reverse relation itself (spec.md FR-012c), a pure in-memory relate over already-fetched facts.

## Summary

One new semantic-composition module (`src/bindle/work_status.py`), one new small presentation module (`src/bindle/view.py`), one small addition to `work_ledger.py`, and CLI additions in `cli.py` (`bindle work status`, `bindle work forecast`, and a new top-level `bindle view` command group). `work_status.py` owns exactly one read-model constructor, `build_snapshot(ledger) -> WorkStatusSnapshot`, composed entirely from `WorkLedger.list_work_items()`/`list_available_work_items()`/`list_blocking()`/`get_claim()` and `milestone_review.review_milestone()` — one ledger pass per invocation, never a second independently-derived computation of any fact. `bindle work forecast`'s dependency frontier (`DependencyFrontier`, `build_forecast(snapshot)`) is a pure, in-memory relation computed *from* an already-built `WorkStatusSnapshot`'s per-item blocking/status/claim facts — it never re-queries the ledger and never mutates or simulates anything. Its `dispatchable_next` counterfactual calls one new, narrow, pure function — `work_ledger.is_dispatchable(status, claimed, blocked) -> bool` — the single authoritative Python expression of the exact three-conjunct rule `list_available_work_items()`'s own SQL already encodes; `list_available_work_items()`'s own internal implementation is refactored to route through this same function (its external behavior and return value are unchanged, verified by its own existing test suite), so live-state and counterfactual dispatchability share actual code, never two independently-maintained expressions of the same rule (Research: "dispatchable-next shares one authoritative predicate"). `bindle work status --json` serializes the identical `WorkStatusSnapshot` object the plain-text renderer reads (`contracts/work-status-json-v1.md`). `bindle view` is a loopback-only (`127.0.0.1`), stdlib-`http.server`-based, server-rendered-HTML surface — a long-lived process for its own invocation's lifetime, handling every GET request it receives (the first load, every manual browser reload, and, under `--watch`, every automatic reload) through the identical `do_GET` handler, which builds a fresh `WorkStatusSnapshot` + `DependencyFrontier` per request — no daemon, no second render code path, no JavaScript (Research: "`bindle view` process/request semantics"). Symphony runtime enrichment (FR-020) is **deferred entirely** in this initial cut: no Symphony-facing code, flag, or UI element of any kind is added, and `bindle view`'s page contains no Symphony-runtime section at all — not a permanent "unavailable" placeholder for a capability this cut never attempts (Research: "Symphony endpoint discovery has no safe zero-config default"; spec.md Assumptions, "FR-020's optional Symphony composition ... deferrable together" with FR-021/US5.5).

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from 001–004; matches `pyproject.toml`).

**Primary Dependencies**: None beyond the standard library — unchanged from 001–004 (`pyproject.toml` declares zero runtime dependencies today). `sqlite3` (via `WorkLedger`, unmodified), `argparse`, `dataclasses`, `json` (already imported by `cli.py`), and, newly, `http.server`/`socketserver` (stdlib) for `bindle view`'s loopback server, `time`/`signal` (stdlib) for `--watch` loops. No `rich`/`textual`/`curses`/`flask`/`jinja2` or any other new dependency is introduced — see Research: "`bindle view` rendering medium."

**Storage**: The existing internal `ledger.sqlite3` only (`WorkLedger`), read through existing public methods plus one new pure, I/O-free function (`is_dispatchable()` — no new query, no schema access at all). No new table, column, or `_SCHEMA_VERSION` bump (spec.md Non-Goals, SC-011) — this feature is read-only end to end.

**Testing**: `pytest`. A new `tests/test_work_status.py` (mirrors the one-module-one-test-file convention `milestone_review.py`/`test_milestone_review.py` already establishes) covering `build_snapshot()`/`build_forecast()` against constructed ledger fixtures, including a matrix test asserting `is_dispatchable(status, claimed, blocked)` agrees with `list_available_work_items()`'s own return value for every constructed task in a fixture ledger — a regression guard on `list_available_work_items()`'s internal refactor described in this plan's Baseline and Constitution Check, not the mechanism that establishes agreement (the shared function call is) (Research: "dispatchable-next shares one authoritative predicate"). Additions to `tests/test_work_ledger.py` for `is_dispatchable()` itself (a small, pure-function truth-table test); `list_available_work_items()`'s existing test class is re-run unmodified to confirm its external behavior/return value is unchanged by the internal refactor. A new `tests/test_view.py` for `view.py`'s HTML rendering function and HTTP handler — including a test that issues two independent HTTP GET requests against one running server instance (e.g. an initial load and a simulated manual reload) and asserts both succeed and both re-read current state, rather than assuming the server accepts only one request (Research: "`bindle view` process/request semantics"); left to task decomposition whether this uses a real ephemeral-port server in a background thread or a direct `BaseHTTPRequestHandler` unit test against a mock request. Additions to `tests/test_cli.py` for the new `bindle work status|forecast` and `bindle view` subcommands, mirroring `TestMilestoneCliSubcommands`/`TestWorkCliSubcommands`.

**Target Platform**: Same as 001–004 — local Python CLI/library, macOS/Linux. `bindle view`'s use of `http.server` is cross-platform within that target; no `curses` (POSIX-only, and not used by this plan regardless) dependency is introduced.

**Project Type**: Single Python package (`src/bindle/`), unchanged. Two new modules added within it.

**Performance Goals**: N/A at this scale, unchanged from 001–004 — a repository's own handful-to-dozens of work items. `build_snapshot()` is `O(work items)` ledger calls (one `get_claim`/`list_blocking` per item, one `review_milestone()` per milestone); `build_forecast()` is a pure in-memory `O(work items)` relate over the snapshot's already-fetched facts — no additional ledger I/O.

**Constraints**: Must not modify `specs/001`–`004`'s own artifacts, schema, lifecycle methods, or write surfaces (spec.md Baseline, Non-Goals). Must never introduce a second, independently-maintained computation of dispatchable/blocked/review-ready (spec.md FR-002/FR-003/FR-004/FR-012, Terminology). Must never poll or refresh without explicit `--watch` (spec.md FR-006/FR-009, Non-Goals). Must never expose the read model on a non-loopback interface by default (spec.md FR-019). Must never install, start, stop, configure, or supervise Symphony, and must introduce no `bindle symphony ...` command (spec.md FR-022, `docs/SYMPHONY.md` Non-scope). Must produce byte-identical `--json` output across two invocations against an unchanged ledger (spec.md SC-004) — this rules out embedding any wall-clock "computed at" value inside the serialized snapshot itself (Research: "No timestamp field in the JSON contract").

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
| No automatic/implicit polling; `--watch` is explicit opt-in on both `bindle work status` and `bindle view` (spec.md FR-006/FR-009/FR-018, Non-Goals) | **PASS** | Absent `--watch`, `bindle work status` performs exactly one `build_snapshot()` call and exits; `bindle view`'s HTML omits the `<meta http-equiv="refresh">` tag entirely unless `--watch` was given at that invocation's own startup — watch state is a per-process CLI flag, never persisted (FR-018). |
| No persistent background daemon (spec.md Non-Goals) | **PASS** | `bindle work status --watch`'s loop and `bindle view`'s `HTTPServer.serve_forever()` both run only for the invoking process's own lifetime and stop cleanly on `KeyboardInterrupt` — see Research: "Watch/serve shutdown behavior." |
| `bindle view` is loopback-only by default, no network exposure (spec.md FR-019) | **PASS** | The server binds `127.0.0.1` unconditionally; no `--host` flag is added in this plan (Research: "No `--host` override"). |
| No `bindle symphony ...` command; Bindle never installs/starts/stops/supervises Symphony (spec.md FR-022, `docs/SYMPHONY.md` Non-scope) | **PASS** | Symphony enrichment (FR-020) is deferred entirely in this cut — no Symphony-facing code, flag, config field, or UI element is added, and `bindle view`'s page carries no Symphony-runtime section at all (not even a placeholder) — see Research: "Symphony endpoint discovery has no safe zero-config default," and spec.md Assumptions' new clarification that FR-021/US5.5's graceful-degradation framing is part of FR-020's own deferrable bundle. |
| No new ledger table/column; SC-011 holds unchanged | **PASS** | Confirmed by inspection of every function this plan adds — all are reads or pure in-memory transforms over existing `WorkLedger` return values. |
| No raw SQL / DB handle exposed as the contract (`AGENTS.md`, mirrors 003/004's same gate) | **PASS** | `work_status.py`'s public surface is dataclasses and two builder functions; `bindle work status --json`'s contract is a documented JSON shape (`contracts/work-status-json-v1.md`), never a database file or connection. |
| Worktrees (D018) — every linked worktree sees the same ledger state | **PASS** | `work_status.py`'s functions take an already-resolved `WorkLedger` (from `RepoInfo.repo_root`, the Git common directory) exactly like `milestone_review.py`/`symphony_projection.py` already do — no new path resolution introduced. |
| No unjustified new dependency (`AGENTS.md`, "Inherit first... Invent last") | **PASS** | `bindle view`'s medium (stdlib `http.server`) and every other new piece of this feature use only the standard library, matching 001–004's own "None beyond the standard library" precedent — see Research: "`bindle view` rendering medium." |

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
│                           # Also owns the shared --watch interval
│                           # default/minimum constants, so
│                           # `bindle work status --watch` and
│                           # `bindle view --watch` cannot silently
│                           # diverge on the bound (spec.md FR-011).
├── view.py                 # NEW — bindle view's loopback HTTP server:
│                           # a stdlib http.server.HTTPServer subclass,
│                           # one do_GET handler that calls
│                           # work_status.build_snapshot()/build_forecast()
│                           # fresh per request and renders a small
│                           # server-rendered HTML page (no JS, no
│                           # external asset, no client-side framework).
│                           # The rendered page contains only Bindle's own
│                           # semantic snapshot + forecast — no
│                           # Symphony-runtime section, placeholder, or
│                           # reference of any kind exists in this feature;
│                           # Symphony enrichment (FR-020) is deferred
│                           # entirely, not stubbed (Research).
└── cli.py                  # EXTENDED — `bindle work status`
                            # [--json] [--watch] [--interval SECONDS],
                            # `bindle work forecast` (nested under the
                            # existing `work` subparser group, alongside
                            # claim/release/done/load-speckit/publish —
                            # spec.md names both as `bindle work ...`),
                            # and a new top-level `bindle view`
                            # [--watch] [--interval SECONDS] [--port PORT]
                            # subparser (parallel to repo/skills/work/
                            # milestone, mirroring 004's precedent for
                            # why milestone got its own top-level group
                            # rather than nesting under work).

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
├── test_view.py             # NEW — HTML rendering + do_GET handler,
│                            # including a multi-request test against one
│                            # running server instance.
└── test_cli.py              # EXTENDED — new TestWorkStatusCliSubcommands
                             # and TestViewCliSubcommand classes; every
                             # existing test class unchanged.
```

**Structure Decision**: Single-project layout, unchanged from 001–004. Two new modules, for two genuinely different concerns: `work_status.py` is the semantic composition/read-model layer (no I/O beyond `WorkLedger` calls, no rendering-medium-specific code — mirrors `milestone_review.py`'s own "composition module, not a CLI module" placement), and `view.py` is the one rendering-medium-specific module this feature needs (HTTP serving, HTML string templating) — deliberately not folded into `work_status.py` itself, so the semantic read model stays renderer-agnostic and reusable by the CLI's plain-text/JSON paths without pulling in `http.server` at all. `bindle work status`/`bindle work forecast` nest under the existing `work` subparser (spec.md itself names them this way, and both report task-centric facts already owned by that namespace); `bindle view` is a new top-level group because, like `bindle milestone` (004's own precedent), it is a distinct surface/audience (a human glancing at a rendered page) rather than another `bindle work` verb.

## Complexity Tracking

Not applicable — no Constitution Check violation requires justification.
