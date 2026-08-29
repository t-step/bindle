---

description: "Task list for Work-State Visibility"
---

# Tasks: Work-State Visibility

**Input**: Design documents from `specs/005-work-state-visibility/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/work-status-json-v1.md, quickstart.md — all present and grounded against the current implementation this session (`src/bindle/work_ledger.py`, `src/bindle/milestone_review.py`, `src/bindle/cli.py`; no drift found between the merged planning artifacts and the code they build on).

**Tests**: Included. This repository's own convention (every prior feature's `tests/test_*.py`) makes tests the norm, not opt-in. This repository's actual test runner is `python3 -m unittest discover` (`scripts/check.sh`, section 8) — every test class below is a `unittest.TestCase`, matching `tests/test_work_ledger.py`/`tests/test_milestone_review.py`/`tests/test_cli.py`'s existing style. (plan.md's Technical Context names "pytest" — inherited, unmodified boilerplate from the Spec Kit plan template also present verbatim in specs/001–004's own plan.md files, not a 005-specific claim, and not what any tracked test file or `scripts/check.sh` actually runs; this is noted here rather than "corrected" in plan.md, since it is not a contradiction this feature introduces.)

**Organization**: Grouped by user story per spec.md's priorities (P1: US1 plain-text status, US2 stable JSON — the reusable read-model contract; P2: US3 `--watch`, US4 forecast). A Foundational phase precedes every story: the shared `is_dispatchable()` predicate and `WorkStatusSnapshot`/`DependencyFrontier` dataclasses everything else composes from.

**Scope note (post-implementation reconciliation)**: this task list originally also carried a Phase 7 (User Story 5, `bindle view`, T023–T028). That user story was evaluated for adoption after Phases 1–6 (US1–US4) already existed and were usable, and was declined before any of Phase 7's tasks were started — see `docs/DECISIONS.md` D045. Phase 7 is retained below, its header and every task checkbox marked `[DECLINED]`, as a superseded record — it is not executable pending work, and no future session should pick these tasks up without a new, separately-scoped decision.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, or a disjoint region of one already-created file, with no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Every task names its exact file path

## Path Conventions

Single Python package, unchanged from 001–004: `src/bindle/`, `tests/`, both at repository root. Two new modules: `src/bindle/work_status.py`, `src/bindle/view.py`; one new test file each (`tests/test_work_status.py`, `tests/test_view.py`); `src/bindle/work_ledger.py` and `tests/test_work_ledger.py` gain a small, narrowly-scoped addition each; `src/bindle/cli.py` and `tests/test_cli.py` gain new subcommands/test classes.

---

## Phase 1: Setup

- [ ] T001 Confirm the existing dev environment runs the current suite cleanly before starting: `bash scripts/check.sh` from the repository root. (No code change; establishes a clean baseline to diff against.)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The single authoritative dispatchability predicate, and the shared dataclass/constant scaffolding every user story's `build_snapshot()`/`build_forecast()`/CLI/`view.py` call depends on. **No forecast-related task (Phase 6) may begin until `is_dispatchable()` (T004) exists** — this is the specific ordering research.md's "dispatchable-next shares one authoritative predicate" decision requires: the counterfactual path must share real code with the live-query path, never a second hand-copied expression of the same rule.

**⚠️ CRITICAL**: No user story work may begin until this phase is complete.

- [ ] T002 [P] Add a new `TestIsDispatchable` test class to `tests/test_work_ledger.py` with failing tests for a not-yet-implemented `is_dispatchable(status: str, claimed: bool, blocked: bool) -> bool`: a truth table over all 8 `(status, claimed, blocked)` combinations where `status` ranges over `{"open", "done", "superseded"}` × `claimed ∈ {True, False}` × `blocked ∈ {True, False}` — `True` iff `status == "open" and not claimed and not blocked`, per data-model.md's exact definition. Pure function, no ledger fixture needed.
- [ ] T003 [P] Create `tests/test_work_status.py` (new file) with a `TestIsDispatchableCoherence` test class: build a small fixture `WorkLedger` (mixed `open`/`done`/`superseded` × claimed/unclaimed × blocked/unblocked tasks, via `create_work_item`/`claim`/`add_blocked_by`), then assert `work_ledger.is_dispatchable(task.status, ledger.is_claimed(task.id), ledger.is_blocked(task.id)) == (task.id in ledger.list_available_work_items())` for every constructed task — the regression guard research.md names for T004's internal refactor of `list_available_work_items()` (not the mechanism that establishes the invariant; the shared function call in T004 is). Depends on: T002 (establishes the fixture-building pattern this file will keep using across later phases).
- [ ] T004 Implement `is_dispatchable(status: str, claimed: bool, blocked: bool) -> bool` in `src/bindle/work_ledger.py`, colocated with the existing `_STILL_BLOCKING_CONDITION` SQL fragment (data-model.md's exact docstring/body). Refactor `list_available_work_items()`'s own internal implementation to fetch candidate `type = 'task'` rows together with their claimed/blocked booleans (already computed today as `NOT EXISTS` subqueries — expose them as selected row-level values instead of inline `WHERE` conditions) and apply `is_dispatchable()` per row in Python to decide inclusion, rather than re-expressing the identical three-conjunct rule a second time in SQL. External behavior, return value, and row ordering are unchanged — the existing `list_available_work_items()`/`TestAvailableWorkItemsExcludesMilestones` test classes in `tests/test_work_ledger.py` must still pass, unmodified, after this change. Depends on: T002. Makes T002 and T003 pass.
- [ ] T005 [P] Add `TaskStatusEntry`, `MilestoneStatusEntry`, `WorkStatusSnapshot`, `ForecastEntry`, `DependencyFrontier` frozen dataclasses, plus `DEFAULT_WATCH_INTERVAL_SECONDS = 2.0` and `MIN_WATCH_INTERVAL_SECONDS = 1.0` module-level constants, to new `src/bindle/work_status.py` — per data-model.md's exact field lists and docstrings (no shared base class or generic `ready`/`state` field between `TaskStatusEntry`/`MilestoneStatusEntry` — Terminology's rule is enforced at the type level, per data-model.md's own explicit note). Module skeleton only; no behavior yet. Parallel with T002–T004 (different file, no dependency).

**Checkpoint**: `is_dispatchable()` exists, is truth-table-tested, and is confirmed coherent with `list_available_work_items()`'s own live return value; `work_status.py`'s shared types and watch-interval constants exist. Every user story can now build on this.

---

## Phase 3: User Story 1 - See current work state at a glance (Priority: P1) 🎯 MVP (part 1 of 2)

**Goal**: `bindle work status` (plain text): every task's claim/dispatchable/blocked facts, every milestone's status/readiness/outstanding-reason, in one command.

**Independent Test**: Per spec.md — construct a ledger with a mix of claimed, dispatchable, and blocked tasks, plus milestones in different statuses/readiness states; run `bindle work status`; confirm every task and milestone is accounted for exactly once, matching what `is_claimed()`/`get_claim()`/`list_available_work_items()`/`is_blocked()`/`list_blocking()`/`is_review_ready()`/`review_milestone()` independently report for the same ledger.

### Tests for User Story 1

- [ ] T006 [P] [US1] Add `TestBuildSnapshot` to `tests/test_work_status.py`: empty ledger → `WorkStatusSnapshot(tasks=[], milestones=[])`, not an error; a claimed task → `claim` populated (owner/claimed_at/worktree_path/branch) and simultaneously `dispatchable is False`; an open/unclaimed/unblocked task → `dispatchable is True`; a task blocked by one or more dependencies → `blocking_ids` names them (never merely a bool); milestones spanning `open`/`review`/`accepted`/`superseded` × ready/not-ready → correct `status`/`review_ready`/`not_ready_reason`, matching `review_milestone()`'s own outstanding-reason detail exactly; an archived work item (`archived_at` set) is excluded from both lists (matching `generate_projection()`'s own live-only convention). For every constructed case, assert every reported fact equals a direct call to the underlying `WorkLedger`/`milestone_review` method on the same ledger (SC-001/SC-002) — this test's own job is to catch a second, independently-derived computation, not merely confirm plausible-looking output. Depends on: T005.
- [ ] T007 [P] [US1] Add `TestWorkStatusCliSubcommand` to `tests/test_cli.py` (mirrors `TestMilestoneCliSubcommands`'s placement/style): `bindle work status` against an empty ledger (valid empty output, exit 0) and a mixed ledger (claimed/dispatchable/blocked task lines showing blocking ids; milestone lines showing readiness and, when not ready, the same outstanding-reason rendering `_format_not_ready_reason()` already produces for `bindle milestone review`). Parallel with T006 (different file).

### Implementation for User Story 1

- [ ] T008 [US1] Implement `build_snapshot(ledger: WorkLedger) -> WorkStatusSnapshot` in `src/bindle/work_status.py`: `list_work_items()` filtered to `archived_at is None`; one call to `list_available_work_items()` for the task-dispatchable id set (never recomputed from `status`/claim/blocking — research.md's "dispatchable is sourced verbatim" decision); `get_claim()`/`list_blocking()` per task; `milestone_review.review_milestone()` once per milestone, taking `review_ready`/`not_ready_reason`/`blocking_ids`/`claim` directly from its `MilestoneReviewView` (never a second, hand-assembled reason list, never `is_review_ready()` called standalone). No `WorkLedger` mutation method is ever called. Depends on: T004, T005. Makes T006 pass.
- [ ] T009 [US1] Add a plain-text status renderer to `src/bindle/work_status.py` (function name left to implementation, e.g. `render_status_text(snapshot) -> str`): task lines (claimed-by/dispatchable/blocked-on, per quickstart.md Walkthrough A's exact shape), milestone lines reusing `cli.py`'s existing `_format_not_ready_reason()` helper (moved or made importable if needed, per research.md's "plain-text `not_ready_reason` rendering reuses `_format_not_ready_reason()`" decision — never a second, hand-copied formatter that could drift in wording from `bindle milestone review`'s own output). Depends on: T008.
- [ ] T010 [US1] Add `bindle work status` to `build_parser()`/`main()` in `src/bindle/cli.py` — nested under the existing `work` subparser (spec.md itself names it `bindle work status`), plain-text-only for now (no `--json`/`--watch` yet — those are US2/US3). New `_cmd_work_status` handler: resolve repo info, construct `WorkLedger`, call `build_snapshot()` + T009's renderer, print to stdout, exit 0. Depends on: T009. Makes T007's plain-text cases pass.

**Checkpoint**: `bindle work status` (plain text) works end-to-end against a real ledger — one snapshot, no flags. US1 independently functional and testable.

---

## Phase 4: User Story 2 - Consume the same snapshot as stable, machine-readable data (Priority: P1) 🎯 MVP (part 2 of 2)

**Goal**: `bindle work status --json`, single-shot — the identical semantic facts as US1, in the documented `contracts/work-status-json-v1.md` shape; deterministic across repeated invocations (SC-004), since this is the contract every future presentation layer (including `bindle view`, Phase 7) depends on.

**Independent Test**: Per spec.md — run `bindle work status` and `bindle work status --json` against the same ledger state; confirm every fact in the plain-text form is present and identical in the JSON form; confirm running `--json` twice against an unchanged ledger produces byte-identical output.

### Tests for User Story 2

- [ ] T011 [P] [US2] Add `TestSnapshotToJson` to `tests/test_work_status.py`: the JSON-serialization helper's output matches `contracts/work-status-json-v1.md`'s documented shape field-for-field for constructed fixtures (empty `blocking_ids` as `[]`, never omitted or `null`; `claim` as the four-field object or `null`; arrays ordered by `id`); text/JSON fact parity — every fact `TestBuildSnapshot`/T006 already exercises in the plain-text renderer is present and identical in the JSON form (SC-003); two `json.dumps(..., indent=2)` calls against the same unchanged `WorkStatusSnapshot` (and, separately, two fresh `build_snapshot()` calls against an unchanged ledger, each serialized) are byte-identical (SC-004) — assert no field in the serialized structure carries a wall-clock "generated at" value (research.md's "no timestamp field in the JSON contract" decision is load-bearing for this exact guarantee). Depends on: T008.
- [ ] T012 [P] [US2] Extend `TestWorkStatusCliSubcommand` in `tests/test_cli.py`: `bindle work status --json` output parses as JSON and matches `contracts/work-status-json-v1.md`'s field set for a constructed fixture; running it twice against an unchanged ledger produces byte-identical stdout (SC-004); confirms this is a plain synchronous stdout print — no listening socket or long-lived process is started merely to serve `--json` (FR-007). Parallel with T011 (different file).

### Implementation for User Story 2

- [ ] T013 [US2] Implement `snapshot_to_json(snapshot: WorkStatusSnapshot) -> dict` in `src/bindle/work_status.py`, mirroring `contracts/work-status-json-v1.md` field-for-field (plan.md's own named identifier: "a `snapshot_to_json()`-shaped serialization helper consumed by `cli.py`'s `--json` path" — this is the identical `WorkStatusSnapshot` object the plain-text renderer reads, never a second, independently-derived computation). Depends on: T008. Makes T011 pass.
- [ ] T014 [US2] Wire `--json` onto `bindle work status` in `src/bindle/cli.py`: `print(json.dumps(snapshot_to_json(snapshot), indent=2))`, mirroring `_cmd_repo_info`'s existing `--json` convention exactly (single-shot, pretty-printed, no other formatting path). Depends on: T010, T013. Makes T012 pass.

**Checkpoint**: `bindle work status` / `bindle work status --json` fully satisfy spec.md US1–US2, FR-001–FR-008, SC-001–SC-004. **This phase plus Foundational is the smallest coherent, independently mergeable unit of this feature — see Implementation Strategy below.**

---

## Phase 5: User Story 3 - Explicitly opt into continuous observation (Priority: P2)

**Goal**: `--watch` on `bindle work status`, a separate explicit opt-in with a bounded refresh interval; `--json --watch` emits JSON Lines (NDJSON), never a growing array or partial fragment; clean exit on interruption with no stray lock or lingering process.

**Independent Test**: Per spec.md — run `bindle work status --watch`; confirm it refreshes on a bounded interval and reflects a claim made in another terminal by the next refresh; interrupt it and confirm the ledger is left in exactly its pre-invocation state with no stray lock or process.

### Tests for User Story 3

- [ ] T015 [P] [US3] Add `TestWatchIntervalResolution` to `tests/test_work_status.py`: a small, pure interval-resolution helper (or inline logic exercised directly) — no override → `DEFAULT_WATCH_INTERVAL_SECONDS`; an override at or above `MIN_WATCH_INTERVAL_SECONDS` → used as given; an override below the minimum → clamped up to `MIN_WATCH_INTERVAL_SECONDS`, never rejected outright (FR-011). Depends on: T005.
- [ ] T016 [P] [US3] Add `TestWorkStatusWatch` to `tests/test_cli.py`: `bindle work status` with no flags performs exactly one ledger read and exits — never a second read regardless of elapsed time (SC-005, US3.1); `--watch --interval <short>` run for a bounded few refreshes against a background-thread-driven ledger fixture reflects an externally-made claim by its next scheduled refresh (US3.2); interrupting a running `--watch` invocation (raise `KeyboardInterrupt` at the loop boundary, or send `SIGINT` to a subprocess) exits promptly with code 0, no traceback, and leaves the ledger's own file state exactly as the last external write left it — no stray lock/temp file (SC-006, US3.3); `--json --watch` captured output is JSON Lines — every emitted line parses independently as one complete, compact JSON document (`contracts/work-status-json-v1.md`'s "Watch-mode framing"), never a partial line even when interrupted mid-sleep, never a growing array wrapper (US3.4, FR-010). Depends on: T014.

### Implementation for User Story 3

- [ ] T017 [US3] Add `--watch [--interval SECONDS]` to `bindle work status` in `src/bindle/cli.py` (`--interval`, `type=float`, clamped through T015's resolution logic — shared with T023's `bindle view --watch`, never a second, independently-chosen bound per research.md). Absent `--watch`, behavior is unchanged from Phase 3/4 (FR-006/FR-009). With `--watch`: loop of `build_snapshot()` → render (T009's text renderer, or, under `--json`, one `json.dumps(..., separators=(",", ":"))` line followed by `\n`) → `time.sleep(interval)` → repeat; catch `KeyboardInterrupt` at the top level, exit 0 with no traceback. No new ledger call beyond the per-refresh `build_snapshot()` — no lock/temp file is ever created by this code path, so SC-006 holds by construction, not by a separate cleanup step. Depends on: T014. Makes T016 pass.

**Checkpoint**: `bindle work status` fully satisfies spec.md US1–US3, FR-001–FR-011, SC-001–SC-006.

---

## Phase 6: User Story 4 - Understand what becomes available next (Priority: P2)

**Goal**: `bindle work forecast` — dispatchable-now, convergence points (items blocked by more than one dependency), and, per currently-blocking id, which items become unblocked-next versus (task-only) dispatchable-next if it resolved; plus the milestone review frontier. Never a time, date, ETA, or completion-order claim.

**Independent Test**: Per spec.md — construct C blocked on {A, B}, D blocked on {A}; run `bindle work forecast`; confirm A and B report dispatchable, C is a convergence point blocked on both, D is blocked only on A, and resolving A makes D (not C) unblocked-next and, since D is otherwise open/unclaimed, also dispatchable-next; confirm no output names a time, date, or ETA.

### Tests for User Story 4

- [ ] T018 [P] [US4] Add `TestBuildForecast` to `tests/test_work_status.py`: spec.md's own worked example (C blocked on {A, B}; D blocked on {A}) — `dispatchable_now == sorted([A, B])`; `convergence_points == [C]`; `frontier` keyed by blocker id — `frontier[A].unblocked_next == [D]` (C excluded — still needs B), `frontier[A].dispatchable_next == [D]` iff `is_dispatchable("open", claimed=False, blocked=False)`; `frontier[B].unblocked_next == []` (C still needs A). Separately, the claimed-but-blocked case (Acceptance Scenario US4.5, quickstart.md's own `D` fixture: claimed, blocked only on A) — resolving A puts D in `unblocked_next` but explicitly **not** in `dispatchable_next`, because it remains claimed under the otherwise-unchanged counterfactual. A dangling (nonexistent) blocking id groups and reports exactly as declared, same as any other id (research.md's "dangling blocking id is a valid forecast grouping key" decision). Assert `build_forecast()` issues zero `WorkLedger` calls (pass a snapshot only — the function's own signature has no ledger parameter, so this is also a signature-level guarantee, not just a runtime one) and that its `dispatchable_next` computation calls `work_ledger.is_dispatchable()` rather than inlining an equivalent `status == "open" and claim is None` check (spy/patch `work_ledger.is_dispatchable` and assert it is actually invoked — the single most load-bearing correctness property in this feature, per research.md's "dispatchable-next shares one authoritative predicate"). Depends on: T004, T008.
- [ ] T019 [P] [US4] Add `TestWorkForecastCliSubcommand` to `tests/test_cli.py`: `bindle work forecast` output for the worked-example fixture matches quickstart.md Walkthrough B's shape (dispatchable-now line; blocked items with convergence-point annotation; one "if X resolves" block per frontier entry; milestone review frontier); assert no output line contains a time, date, duration, or ETA token (SC-008 — check for absence of any digit-colon-digit clock pattern, month/day tokens, or words like "eta"/"duration"/"estimated"); running it twice against an unchanged ledger leaves the ledger's own state byte-identical before/after (FR-015, via `list_work_items()`/`list_blocking()`-per-item snapshot comparison). Parallel with T018 (different file).

### Implementation for User Story 4

- [ ] T020 [US4] Implement `build_forecast(snapshot: WorkStatusSnapshot) -> DependencyFrontier` in `src/bindle/work_status.py`: pure in-memory relation over `snapshot.tasks`/`snapshot.milestones`'s already-fetched `blocking_ids`/`status`/`claim` fields only, **no `WorkLedger` parameter in the function signature** (so it cannot issue a query even by accident, per FR-015). `dispatchable_now` = `snapshot`'s own task-dispatchable id list, passed through unchanged. `convergence_points` = every item (task or milestone) with `len(blocking_ids) > 1`, ordered by id. `frontier` = one `ForecastEntry` per distinct id appearing in any item's `blocking_ids` (dangling ids included, exactly as declared — never filtered or specially interpreted), ordered by `resolved_blocker_id`: `unblocked_next` = items whose `blocking_ids == [that id]`; `dispatchable_next` = the task subset of `unblocked_next` for which `work_ledger.is_dispatchable(status=item.status, claimed=item.claim is not None, blocked=False)` returns `True` — **must call this imported function; must never re-derive the two-conjunct check inline** (research.md's most consequential correction — the whole point of T004's refactor is that this counterfactual path and `list_available_work_items()`'s live path share one authoritative Python expression of the rule). Depends on: T004, T008. Makes T018 pass.
- [ ] T021 [US4] Add a plain-text forecast renderer to `src/bindle/work_status.py` (e.g. `render_forecast_text(snapshot, frontier) -> str`): dispatchable-now line; blocked items with a convergence-point annotation for any item in `frontier`'s convergence set; one "if `<id>` resolves" block per `ForecastEntry` naming `unblocked_next` and `dispatchable_next` (explicitly noting when a listed item is unblocked-next but not dispatchable-next, per quickstart.md Walkthrough B's exact "(none — D remains claimed)" style — the rendering must never collapse or merge these two distinct facts); a milestone review frontier section reading `snapshot.milestones` directly (not a second milestone-facing structure — data-model.md's own note: `build_forecast()` does not duplicate the milestone frontier, it is already on the snapshot), reusing T009's not-ready-reason formatting. Contains no timestamp, duration, or completion-order language anywhere in the template. Depends on: T020, T009.
- [ ] T022 [US4] Add `bindle work forecast` to `build_parser()`/`main()` in `src/bindle/cli.py`, nested under the existing `work` subparser alongside `status`/`claim`/`release`/`done`/`load-speckit`/`publish` (spec.md names it `bindle work forecast`). New `_cmd_work_forecast` handler: resolve repo info, construct `WorkLedger`, call `build_snapshot()` + `build_forecast()` + T021's renderer, print to stdout, exit 0 — read-only, no mutation call anywhere in this handler. Depends on: T021. Makes T019 pass.

**Checkpoint**: `bindle work status` / `bindle work forecast` fully satisfy spec.md US1–US4, FR-001–FR-015, SC-001–SC-008.

---

## Phase 7 (SUPERSEDED — DECLINED, NOT IMPLEMENTED): User Story 5 - See the same picture in a small local visual surface (Priority: P3)

**Disposition**: This phase was evaluated for adoption after Phases 1–6 (User Stories 1–4) already existed and were usable, and was declined — no repeated, observed friction demonstrated a need for a Bindle-hosted visual surface once `bindle work status`/`bindle work forecast` existed. See `docs/DECISIONS.md` D045. None of T023–T028 below were started; they are retained verbatim as a historical record of what was planned and declined, not as executable pending work. No future session should pick up any task in this phase without a new, separately-scoped decision grounded in demonstrated need.

**Goal (as originally planned, not adopted)**: `bindle view` — a loopback-only (`127.0.0.1`), stdlib-`http.server`-based, server-rendered HTML page over the identical `WorkStatusSnapshot` + `DependencyFrontier` Phases 3–6 already define; one `do_GET` handler serves every request (first load, manual reload, and, under `--watch`, every automatic reload) — never a second render code path; no Symphony-runtime section, placeholder, or reference of any kind (FR-020 deferred entirely, per research.md's explicit correction — not stubbed).

**Independent Test (as originally planned, not adopted)**: Per spec.md's prior draft — launch `bindle view` with no flags against a ledger with mixed task/milestone state; confirm it renders one snapshot and performs no further reads until a manual refresh is triggered; trigger manual refresh and confirm it reflects a change made in the meantime; relaunch with `--watch` and confirm periodic automatic refresh.

**Note**: This story depended only on Phase 6 (needs both `build_snapshot()` and `build_forecast()` to render both sections) and Foundational — it did **not** depend on Phases 3–5's CLI wiring in `cli.py`.

### Tests for User Story 5 (SUPERSEDED — none started)

- [DECLINED] T023 [P] [US5] Create `tests/test_view.py` with `TestViewRendering`: an HTML-rendering function (e.g. `render_html(snapshot, frontier, watch=False, interval=None)`) produces a page containing every task/milestone id from a constructed fixture; contains **no** Symphony-related string or section of any kind (assert absence, e.g. no case-insensitive occurrence of "symphony" anywhere in the output — research.md's explicit "no placeholder" correction, US5.5/SC-010's deferred-case framing); `watch=True` includes `<meta http-equiv="refresh" content="{interval}">`; `watch=False` omits that tag entirely (FR-016/FR-018). Depends on: T020.
- [DECLINED] T024 [P] [US5] Extend `tests/test_view.py` with `TestViewServer`: start the loopback HTTP server against a constructed ledger fixture — an ephemeral-port `HTTPServer` in a background thread (chosen over a mock-request unit test, per research.md's open question, because only a real running server can demonstrate "one long-lived process, many independent requests," the specific behavior US5.2/US5.9's "process/request semantics" decision requires) — and issue two independent `GET /` requests (simulating first load, then manual reload): both succeed, and the second reflects a ledger mutation made between the two requests (proves a fresh render per request, not one cached response, and that no automatic reload occurred on its own between them absent `--watch` — SC-009). `GET /nope` returns a plain 404 and the server keeps serving afterward. The bound address is `127.0.0.1` — never `0.0.0.0` or any other host — with no way to override it from this feature's own surface (FR-019, "no `--host` override"). Depends on: T023.
- [DECLINED] T025 [P] [US5] Add `TestViewCliSubcommand` to `tests/test_cli.py`: `bindle view` prints a resolved `http://127.0.0.1:<port>/` URL to stdout before serving; run in a background thread/bounded-timeout harness, it can be interrupted (`KeyboardInterrupt` at the loop boundary) with exit code 0, no traceback, and the socket released promptly (a second `bindle view --port <same>` can immediately rebind); `--watch --interval` shares T015's clamping logic (an override below `MIN_WATCH_INTERVAL_SECONDS` clamps up, never rejected — the identical bound `bindle work status --watch` uses, never a second independently-chosen number). Parallel with T023/T024 (different file).

### Implementation for User Story 5 (SUPERSEDED — none started)

- [DECLINED] T026 [US5] Create `src/bindle/view.py`: an HTML-rendering function building a server-rendered page from a `WorkStatusSnapshot` + `DependencyFrontier` — plain Python string formatting only, no template engine dependency, no JavaScript, no external asset. No Symphony-facing field, flag, config value, or placeholder UI element of any kind exists anywhere in this module (research.md's explicit correction: deferred means deferred, not scaffolded-but-inert). Depends on: T020. Makes T023 pass.
- [DECLINED] T027 [US5] Add a loopback `http.server.HTTPServer` + `BaseHTTPRequestHandler` subclass to `src/bindle/view.py`: one `do_GET` handler for `GET /` that constructs a `WorkLedger`, calls `build_snapshot()` + `build_forecast()` fresh on every invocation, and returns T026's render; any other path returns a plain 404; binds `127.0.0.1` unconditionally; binds port `0` (OS-assigned) by default. Depends on: T026. Makes T024 pass.
- [DECLINED] T028 [US5] Add `bindle view [--watch] [--interval SECONDS] [--port PORT]` as a new top-level subparser in `src/bindle/cli.py` (parallel to `repo`/`skills`/`work`/`milestone`, not nested under `work` — mirrors `milestone`'s own precedent for why a distinct human-facing surface gets its own top-level group rather than nesting under an existing verb namespace). `_cmd_view` handler: resolve repo info, start T027's server, print the resolved URL, then `serve_forever()` in the foreground; catch `KeyboardInterrupt` at the top level, call `server.server_close()` in a `finally` block, exit 0 with no traceback. `--interval` reuses T015/T017's shared clamping logic (never a second, independently-chosen bound). Depends on: T027. Makes T025 pass.

**Checkpoint (superseded)**: This phase's own checkpoint ("all five user stories pass independently") never applied, since Phase 7 was declined before any of its tasks started. The feature's actual adopted-scope checkpoint is Phase 6's, above: US1–US4, FR-001–FR-015, SC-001–SC-008.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [x] T029 [P] Run `bash scripts/check.sh` (this repository's canonical verification gate, per AGENTS.md) and resolve any lint/type/test findings across every file this feature touched.
- [x] T030 [P] Manually execute quickstart.md's walkthroughs for the adopted scope (A: one snapshot, two renderings; B: forecast convergence/unblocked-next/dispatchable-next; C: `--watch` refresh-then-clean-interrupt) against a scratch repository, confirming actual CLI output matches what quickstart.md documents; correct either the code or the doc if they've drifted. (Walkthrough D, `bindle view`, is no longer part of the adopted quickstart — see quickstart.md's own reconciliation note and `docs/DECISIONS.md` D045.)
- [x] T031 [P] Confirm SC-011 directly: diff the `work_items`/`work_item_blocked_by`/`work_item_claims`/`work_item_evidence` table definitions and `_SCHEMA_VERSION` before and after this feature's implementation — no new table, column, or version bump anywhere (mirrors specs/004 SC-008's own framing, per spec.md).
- [x] T032 Add a new decision entry to `docs/DECISIONS.md` recording this feature's adopted boundary, mirroring D038–D044's style: what was adopted (`work_status.py`'s composed read model and dependency frontier, `is_dispatchable()`'s narrowly-scoped refactor of `list_available_work_items()`, two new CLI surfaces — `bindle work status`, `bindle work forecast`); what was deliberately not touched (specs/001–004's own methods/schema/write surfaces, unchanged); and that User Story 5 (`bindle view`, a local visual surface with optional Symphony runtime enrichment) was evaluated after US1–US4 existed and declined, not deferred-and-pending. Landed as `docs/DECISIONS.md` D045. Depends on: T001–T031 complete and merged.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. **Blocks every user story** — `is_dispatchable()` (T004) and `work_status.py`'s shared dataclasses/constants (T005) are used, directly or transitively, by every adopted story. In particular, T004 must land before any Phase 6 (forecast) task — the ordering constraint spec.md's own review correction (research.md) exists specifically to enforce.
- **User Stories (Phases 3–6, adopted)**: All depend on Foundational.
  - Phases 3+4 (US1, US2) form this feature's real spine — both build directly on `build_snapshot()` (T008) and are, by spec.md's own priority marking, equal-priority (US2 is "the reusable contract everything else... depends on"). Treated here as one combined MVP unit (see Implementation Strategy).
  - Phase 5 (US3) extends Phase 4's CLI wiring with a loop; no new semantic computation.
  - Phase 6 (US4) depends on Foundational's `is_dispatchable()` (T004) and Phase 3's `build_snapshot()` (T008) — not on Phases 4/5's `--json`/`--watch` wiring at all.
  - Phase 7 (US5) is superseded/declined (see Phase 7's own header) — not part of this dependency graph's adopted scope.
- **Polish (Phase 8)**: Depends on all adopted user stories (Phases 3–6) being complete. T032 additionally depends on the feature actually being merged.

### User Story Dependencies

- **US1 (P1)**: Depends only on Foundational.
- **US2 (P1)**: Depends only on Foundational + US1's `build_snapshot()` (T008) — shares that same object, never a second computation. Equal priority to US1 per spec.md.
- **US3 (P2)**: Depends on US1+US2's CLI wiring (T010, T014) — `--watch` is additive behavior on the same command, not a new computation.
- **US4 (P2)**: Depends on Foundational (T004) + US1's `build_snapshot()` (T008). Independently testable without US2/US3 having landed — `bindle work forecast` never touches `--json`/`--watch`.
- **US5 (P3, superseded/declined)**: Not part of the adopted dependency graph — see Phase 7's own header and `docs/DECISIONS.md` D045.

### Within Each User Story

- Tests before implementation (tests fail first, then the implementation task makes them pass — noted per-task above).
- `work_status.py`'s builder functions (`build_snapshot`, `build_forecast`) before their renderer functions, before their `cli.py` wiring (a CLI handler cannot be written against a function that doesn't exist yet).
- `cli.py` subparser/handler tasks (T010, T014, T017, T022) are sequential with each other — one shared file, one shared `build_parser()`/`main()` pair — never marked `[P]` against one another, per plan.md's own file-ownership note (mirrors 004's precedent). (Phase 7's T028 is superseded/declined, never landed.)
- `work_status.py` implementation tasks (T008, T009, T013, T020, T021) are likewise sequential with each other — one shared file — even though they belong to different user stories.

### Parallel Opportunities

- T002 (`tests/test_work_ledger.py`) and T003/T005 (`tests/test_work_status.py`) are genuinely parallel — different files.
- Within Phase 3: T006 (`tests/test_work_status.py`) and T007 (`tests/test_cli.py`) are parallel — different files.
- Within Phase 4: T011 and T012 — same pattern, parallel.
- Within Phase 5: T015 and T016 — same pattern, parallel (T015 is itself parallel with Phase 3/4's own test tasks, since it only needs T005).
- Within Phase 6: T018 and T019 — same pattern, parallel.
- **Cross-story**: Once Foundational (Phase 2) and Phase 3's `build_snapshot()` (T008) exist, Phase 6's *test-and-builder* work (T018/T020, needing only T004+T008) can proceed in parallel with Phase 4/5's `cli.py` wiring (T013/T014/T017, needing T010) — different files, no shared edit region.
- Real serialization remains at the test-authoring and cross-module level, not within `work_status.py`'s or `cli.py`'s own implementation tasks, given this feature's small size and the two files' central role.

---

## Parallel Example: Foundational + User Story 1

```bash
# After Phase 1 (Setup):
Task: "Add TestIsDispatchable to tests/test_work_ledger.py (T002)"
Task: "Create tests/test_work_status.py with TestIsDispatchableCoherence (T003)"   # depends on T002's pattern, sequenced after it
Task: "Add dataclasses/constants to src/bindle/work_status.py (T005)"             # parallel with T002/T003 -- different file

# After T004 (is_dispatchable + refactor) and T005 land:
Task: "Add TestBuildSnapshot to tests/test_work_status.py (T006)"
Task: "Add TestWorkStatusCliSubcommand to tests/test_cli.py (T007)"               # parallel with T006 -- different file
```

---

## Implementation Strategy

### MVP First (Foundational + User Story 1 + User Story 2)

1. Complete Phase 1 (trivial) and Phase 2 (Foundational: `is_dispatchable()`, the shared dataclasses/constants).
2. Complete Phase 3 (US1: `bindle work status` plain text) and Phase 4 (US2: `bindle work status --json`).
3. **STOP and VALIDATE**: run quickstart.md Walkthrough A by hand against a scratch repository.
4. **This is the smallest coherent first implementation unit**, derived from the actual dependency graph above, not assumed: every other adopted story (US3's `--watch`, US4's forecast) depends on `build_snapshot()` (T008) either directly or transitively, and nothing in Phases 3–4 depends on anything past Foundational. spec.md itself marks US1 and US2 as equal, first priority — "the reusable contract everything else in this feature depends on" — and the merged `contracts/work-status-json-v1.md` already documents exactly this JSON shape as the stable interface future work builds on. Shipping Foundational + US1 + US2 alone gives a maintainer a real, complete, independently useful answer to "what is claimed/dispatchable/blocked, and what's each milestone's readiness" — in both a human-readable and a script-consumable form — before any watch/forecast work begins.

### Incremental Delivery

1. Foundational → US1+US2 (snapshot visible, both forms) → US3 (opt into live refresh) → US4 (dependency frontier) → Polish. (US5, `bindle view`, was evaluated after this sequence completed and declined — Phase 7, `docs/DECISIONS.md` D045 — not a remaining increment.)
2. Each checkpoint above is independently mergeable and independently valuable. US4 does not require US3 to have landed first (its own dependency chain bypasses it entirely, per "User Story Dependencies" above) — a team under time pressure could ship Foundational+US1+US2, then jump straight to US4 (forecast) without `--watch` existing yet, and add US3 later with no rework, since `--watch` is purely additive to already-shipped commands.
