# Feature Specification: Work-State Visibility

**Feature Branch**: `spec/work-state-visibility`

**Created**: 2026-08-28

**Status**: Draft

**Input**: User description: "Bindle already owns enough durable coordination state (the SQLite work ledger, milestone review lifecycle, and published Symphony projection) to answer useful human questions about work: what exists, what is claimed/running, what is ready now, what is waiting and on what, what milestones are approaching or ready for review, and roughly what work becomes available after other work resolves. Add a small, read-only work-state visibility surface — `bindle work status` (one-shot snapshot; `--json` for a stable machine-readable read model; `--watch` as an explicit opt-in continuous-refresh mode), `bindle work forecast` (a read-only dependency-frontier/readiness explainer, never a completion-time estimator), and `bindle view` (a small local visual surface over the same semantic read model, snapshot-by-default with manual refresh and an explicit `--watch` opt-in, optionally composing Symphony's own runtime facts when Symphony happens to be running) — without becoming a new orchestration or observability subsystem."

**Baseline**: This feature builds on `specs/001-durable-work-ledger/`, `specs/002-milestone-task-work-items/`, `specs/003-symphony-task-integration/`, and `specs/004-milestone-review-surface/` (all implemented in `src/bindle/work_ledger.py`/`src/bindle/milestone_review.py`/`src/bindle/symphony_projection.py`, adopted in `docs/DECISIONS.md` D038/D039/D042) without modifying any of them. It reopens no settled decision from those four features: SQLite as the persistence format, the `task`/`milestone` split, blocking/dispatchable/review-readiness as derived-never-stored facts, the published Symphony projection's task-only shape, or either existing command group's (`bindle work`, `bindle milestone`) write surface. What none of the four provide today is a **composed, cross-cutting read** of that state — every fact this feature reports already exists as an individual `WorkLedger`/`milestone_review` method result; nothing today aggregates task and milestone state together, and nothing computes the dependency-frontier ("what becomes eligible after X resolves") fact at all. This feature adds exactly that composition and presentation layer, plus one small local visual surface over it — no new lifecycle behavior, no new persisted state, no new arbitration mechanism, and no new blocking/readiness/dispatchable predicate.

## Terminology

These words are used precisely and never interchangeably, per this repository's existing, deliberate separation between a task's execution lifecycle and a milestone's human-acceptance lifecycle (`docs/SYMPHONY.md`, `specs/002-milestone-task-work-items`):

- **Claimed**: a work item currently has a row in `work_item_claims` (`WorkLedger.is_claimed()`/`get_claim()`). A ledger fact Bindle owns and can always report, with or without Symphony.
- **Running**: a Symphony-owned runtime fact — an agent process Symphony's own runtime currently has assigned to a task (Symphony's `/api/v1/state`, `counts.running`/`running[]`). Bindle never infers "running" from "claimed"; a claimed task is only ever reported as running when Symphony's own runtime is reachable and says so (see `bindle view`, User Story 5). Absent that, a claimed task is reported as claimed, not idle and not running.
- **Dispatchable**: the exact, already-existing fact `WorkLedger.generate_external_projection()`/`generate_projection()`/`list_available_work_items()` compute for a **task**: `status = 'open'` AND unclaimed AND unblocked. This feature never recomputes this predicate independently.
- **Blocked** / **Waiting**: a work item (task or milestone) has at least one unresolved `blocked_by` edge (`WorkLedger.is_blocked()`/`list_blocking()`). "Waiting" is this specification's human-facing synonym for the identical fact — it names no third concept.
- **Review-ready**: the exact, already-existing fact `WorkLedger.is_review_ready()` computes for a **milestone** only. Never applied to a task, and never merged with "dispatchable" into one generic "ready" state — a task is dispatchable-or-not; a milestone is review-ready-or-not; nothing in this feature introduces a word that spans both.
- **Unblocked-next**: a forecast-only counterfactual fact about a work item (task or milestone) — it would have zero unresolved `blocked_by` edges if one named, currently-blocking item resolved, with every other current ledger fact (status, claim, every other blocking edge) held unchanged. This is strictly weaker than "dispatchable" or "review-ready" and applies to either a task or a milestone; on its own it says nothing about claim status, task `status`, or milestone review-readiness.
- **Dispatchable-next**: a forecast-only counterfactual fact about a **task** only — it is unblocked-next (above) AND, under that same unchanged-otherwise counterfactual, its current `status` is `open` and it is currently unclaimed, i.e., it would satisfy the exact existing dispatchable predicate (above) the moment the named blocker resolved. A task can be unblocked-next without being dispatchable-next (for example, it remains claimed, or its `status` is not `open`); this feature never reports the two as the same fact. This concept has no milestone equivalent — a milestone's forecast-relevant counterfactual is unblocked-next only, since "dispatchable" is not defined for milestones.
- **Forecast**: a structural explanation of dependency topology — what's dispatchable now (the exact existing predicate, above), what's blocked on what (the exact existing fact, above), and, for each named currently-blocking item, which other items would become unblocked-next versus dispatchable-next if it resolved (above) — computed entirely from already-recorded `blocked_by` edges and current status/claim facts. Every forecast counterfactual holds every current ledger fact other than the one named dependency's resolution unchanged — it is never a simulation of multiple simultaneous changes. Never a predicted completion time, and never a claim about actual dispatch or completion order (see Non-Goals).

## User Scenarios & Testing *(mandatory)*

<!--
  This feature's users are the repository maintainer (or a script acting on
  their behalf) who wants a cross-cutting picture of current coordination
  state — the same audience specs/001-004 already write for, not an
  external product audience.
-->

### User Story 1 - See current work state at a glance (Priority: P1)

A maintainer runs one command and sees, without opening a SQLite client or cross-referencing three separate `bindle` subcommands by hand: which tasks are currently claimed (and by whom), which tasks are dispatchable right now, which tasks are waiting and on exactly which unresolved dependency, and a summary of every milestone's status and review-readiness.

**Why this priority**: Every other story in this feature composes or presents this same underlying snapshot; without it, none of the others have anything to build on.

**Independent Test**: Construct a ledger with a mix of claimed, dispatchable, and blocked tasks, plus milestones in different statuses and readiness states; run `bindle work status`; confirm every task and milestone is accounted for exactly once, with the correct claim/dispatchable/blocked/review-ready facts, matching what the existing `WorkLedger`/`milestone_review` methods independently report for the same ledger.

**Acceptance Scenarios**:

1. **Given** a task with a current claim, **When** a maintainer runs `bindle work status`, **Then** that task is reported as claimed, together with the claim's owner and claimed-at time (`get_claim()`), and is not simultaneously reported as dispatchable.
2. **Given** a task that is `open`, unclaimed, and unblocked, **When** a maintainer runs `bindle work status`, **Then** that task is reported as dispatchable.
3. **Given** a task blocked by one or more unresolved dependencies, **When** a maintainer runs `bindle work status`, **Then** that task is reported as blocked/waiting, naming the specific still-blocking dependency id(s) (`list_blocking()`) — never merely a boolean.
4. **Given** milestones in a mix of `open`, `review`, `accepted`, and `superseded` status, some review-ready and some not, **When** a maintainer runs `bindle work status`, **Then** every milestone is listed with its status and review-readiness, and every not-ready milestone names why (reusing `review_milestone()`'s existing outstanding-reason detail).
5. **Given** an empty ledger, **When** a maintainer runs `bindle work status`, **Then** the command reports an empty-but-valid snapshot, not an error.
6. **Given** any ledger state, **When** a maintainer runs `bindle work status` without `--watch`, **Then** the command prints exactly one snapshot and exits — it never polls or refreshes on its own.

---

### User Story 2 - Consume the same snapshot as stable, machine-readable data (Priority: P1)

A script (or a future renderer such as `bindle view`) needs the identical semantic facts from User Story 1 in a form it can parse reliably, without scraping formatted text.

**Why this priority**: Equal priority to User Story 1 because it is the reusable contract everything else in this feature (and any future presentation layer) depends on — `bindle view`'s own read model is this JSON shape, not a second, independently-derived computation.

**Independent Test**: Run `bindle work status` and `bindle work status --json` against the same ledger state; confirm every fact in the plain-text form (claims, dispatchable set, blocking ids, milestone readiness) is present and identical in the JSON form; confirm running `--json` twice against an unchanged ledger produces byte-identical output.

**Acceptance Scenarios**:

1. **Given** any ledger state already covered by User Story 1's scenarios, **When** a maintainer runs `bindle work status --json`, **Then** the emitted JSON contains the identical semantic facts as the plain-text form for that same state.
2. **Given** an unchanged ledger, **When** `bindle work status --json` is run twice, **Then** both outputs are identical.
3. **Given** `bindle work status --json`, **When** it is invoked, **Then** it prints JSON to stdout and exits — no HTTP server, socket, or other network-accessible interface is started merely to serve this data.

---

### User Story 3 - Explicitly opt into continuous observation (Priority: P2)

A maintainer watching work progress in real time (e.g., while Symphony is dispatching tasks) wants the snapshot to refresh automatically, but only when they ask for that — a plain status check must never turn into background polling they didn't request.

**Why this priority**: Depends on Stories 1–2 already existing (there must be a snapshot to refresh); ranked below them because the one-shot form is the more common and more foundational use.

**Independent Test**: Run `bindle work status --watch`; confirm it refreshes on a bounded interval and reflects a claim made in another terminal by the next refresh; interrupt it (e.g., Ctrl+C) and confirm the ledger is left in exactly its pre-invocation state with no stray lock or process.

**Acceptance Scenarios**:

1. **Given** `bindle work status` is run with no flags, **When** any amount of time passes, **Then** it does not refresh, poll, or re-read the ledger a second time — it already exited after User Story 1's single snapshot.
2. **Given** `bindle work status --watch` is running, **When** a claim, release, or status change is made elsewhere against the same ledger, **Then** the next scheduled refresh reflects the change.
3. **Given** `bindle work status --watch` is running, **When** the maintainer interrupts it, **Then** it exits promptly, leaves no open lock or lingering process, and the ledger's own state is unaffected (this command never writes).
4. **Given** `--watch` combined with `--json`, **When** it runs, **Then** each refresh emits one complete, independently valid JSON snapshot — never a partial or streamed fragment a reader must reassemble.

---

### User Story 4 - Understand what becomes available next, without a fake execution plan (Priority: P2)

Beyond "what's blocked and by what" (already in User Story 1), a maintainer wants to understand the shape of remaining work: what's dispatchable right now, what single dependency is the thing multiple other items are all waiting on, and — if a specific item resolved — which other items would merely become unblocked-next versus which would further become dispatchable-next (Terminology) — without the tool pretending to know a wall-clock schedule or a guaranteed completion order it cannot actually know under concurrent execution.

**Why this priority**: A genuinely useful but structurally distinct question from Story 1's per-item snapshot — it is a graph-shaped view across items, not a per-item fact, and depends on Story 1's underlying facts already being composable.

**Independent Test**: Construct a small dependency graph (e.g., task C blocked on both A and B; task D blocked only on A) and run `bindle work forecast`; confirm it reports A and B as currently dispatchable, C as blocked on both A and B (a convergence point), D as blocked only on A, and that resolving A would newly make D — but not C — unblocked-next, and, since D is otherwise `open` and unclaimed, also dispatchable-next; confirm no output names a time, date, or ETA.

**Acceptance Scenarios**:

1. **Given** a ledger with some tasks dispatchable now, **When** a maintainer runs `bindle work forecast`, **Then** every currently-dispatchable task is listed as such.
2. **Given** a task or milestone blocked on one or more unresolved dependencies, **When** `bindle work forecast` runs, **Then** it names the specific blocking id(s) — the identical fact User Story 1 reports, not a second, independently computed blocking check.
3. **Given** an item blocked on more than one unresolved dependency, **When** `bindle work forecast` runs, **Then** that item is identified as a convergence point naming every one of its outstanding blockers.
4. **Given** a specific currently-blocking id, **When** `bindle work forecast` runs, **Then** it reports which other item(s) would become unblocked-next (i.e., have no other unresolved blocker remaining) if that id resolved, and, for each such item that is a task, whether it would also be dispatchable-next (already `status = 'open'` and already unclaimed under the same counterfactual) or would remain merely unblocked-next.
5. **Given** a task that is currently claimed and is blocked by exactly one unresolved dependency, **When** `bindle work forecast` runs and that dependency is the one named as hypothetically resolved, **Then** the task is reported as becoming unblocked-next but explicitly not dispatchable-next, because it remains claimed under the otherwise-unchanged counterfactual — losing a blocker is reported as distinct from becoming dispatchable.
6. **Given** milestones in a mix of readiness states, **When** `bindle work forecast` runs, **Then** it includes a milestone review frontier: which milestones are review-ready now, and for each that is not, what's outstanding (the same fact User Story 1 already reports for milestones).
7. **Given** multiple tasks simultaneously dispatchable, **When** `bindle work forecast` runs, **Then** it never asserts or implies which of them will actually be claimed or completed first — only that all are currently dispatchable; actual completion order is explicitly acknowledged as unknowable under concurrent execution.
8. **Given** any output of `bindle work forecast`, **When** it is reviewed, **Then** it contains no estimated duration, timestamp-based ETA, or wall-clock prediction of any kind.
9. **Given** `bindle work forecast` is run any number of times against an unchanged ledger, **When** its output is compared, **Then** the ledger itself is unchanged (read-only; no work item, claim, or blocking edge is created, mutated, or simulated to produce the result).

---

### User Story 5 - See the same picture in a small local visual surface (Priority: P3)

A maintainer who would rather glance at a small local visual display than read CLI text wants the same semantic snapshot rendered locally, with no surprise background activity — and, if Symphony happens to be running, wants to optionally also see what Symphony's own runtime is doing, without Bindle taking on any responsibility for Symphony itself.

**Why this priority**: Lowest priority because it is a presentation convenience over facts Stories 1–4 already fully define and expose; a maintainer with CLI access already has everything this story shows, just less conveniently.

**Independent Test**: Launch `bindle view` with no flags against a ledger with mixed task/milestone state; confirm it renders one snapshot and performs no further reads until a manual refresh is triggered; trigger manual refresh and confirm it reflects a change made in the meantime; relaunch with `--watch` and confirm periodic automatic refresh; separately, run it once with no Symphony instance reachable (confirm graceful full rendering of Bindle's own state) and once with a Symphony instance running and its observability endpoint reachable (confirm the optional runtime section appears, sourced from that endpoint).

**Acceptance Scenarios**:

1. **Given** `bindle view` is launched with no flags, **When** it starts, **Then** it renders exactly one snapshot of the semantic read model (Stories 1/4) and does not automatically refresh.
2. **Given** `bindle view` is running in its default (non-watch) mode, **When** the maintainer triggers the manual refresh action, **Then** the display updates to reflect current ledger state on demand.
3. **Given** `bindle view --watch` is launched, **When** any amount of time passes, **Then** the display refreshes automatically on a bounded interval, independent of and not requiring the manual refresh action.
4. **Given** two separate launches of `bindle view`, one with `--watch` and one without, **When** each is observed, **Then** each launch's refresh behavior is determined solely by its own invocation's flag — watch state from a prior launch never carries into a new one.
5. **Given** no Symphony instance is reachable, **When** `bindle view` is launched, **Then** it renders Bindle's full semantic snapshot with no error; if this implementation attempts FR-020's optional Symphony composition, it clearly marks the Symphony-runtime section as unavailable rather than omitting it silently or failing the whole render, and if FR-020 is deferred entirely (Assumptions), the render contains no Symphony-runtime section at all, which satisfies this scenario identically.
6. **Given** a Symphony instance is running and its existing observability endpoint is reachable, **When** `bindle view` is launched or refreshed, **Then** it may additionally display Symphony's own runtime facts (running/retrying/blocked-on-input agents, workspace/worker information, last agent event or message), sourced fresh from that endpoint and visibly distinguished from Bindle's own semantic snapshot — never merged into it as if Bindle itself asserted those facts.
7. **Given** `bindle view` is displaying composed Symphony runtime facts, **When** the underlying Symphony endpoint becomes unreachable mid-session (e.g., Symphony is stopped), **Then** the next refresh degrades that section to unavailable without crashing the rest of the display.
8. **Given** `bindle view` at any point, **When** its behavior is examined, **Then** it never starts, stops, configures, or otherwise manages a Symphony process, and no `bindle symphony ...`-style command is introduced by this feature.

### Edge Cases

- What happens when the ledger has zero work items? `bindle work status`, `bindle work forecast`, and `bindle view` each render an empty-but-valid snapshot — not an error, not a crash.
- What happens when a claim's recorded `worktree_path`/`branch` no longer resolves (an existing `reconcile()` "stale_claim" finding)? Status reports the claim exactly as recorded — this feature does not silently hide, "fix", or reinterpret a stale claim; reconciliation (`WorkLedger.reconcile()`) remains a separate, existing, unmodified operation this feature does not duplicate or invoke automatically.
- What happens when a task is blocked by a dangling (nonexistent) dependency id? It is reported exactly as `list_blocking()` already reports it — conservatively still-blocking — with no special interpretation invented for this feature.
- What happens when two maintainers request status/forecast/view concurrently while a third claims, releases, or completes a task? Each snapshot is an independent read with no cross-query locking, exactly like every other derived read in this ledger (specs/004's own precedent) — a snapshot may be stale by the time it is displayed; this is expected staleness, not a defect this feature must eliminate.
- What happens when `bindle work forecast` is run and nothing is currently blocked? It reports that every open task is currently dispatchable, cleanly — not an empty or confusing result.
- What happens when `bindle view --watch` is running and a task's claim changes underneath it between refreshes? The next scheduled refresh reflects the new state; a display that was accurate at render time and is now stale is not treated as an error.
- What happens when Symphony's observability endpoint is reachable but returns unexpected or malformed data? `bindle view` degrades that section to unavailable rather than failing the entire render (same posture as an unreachable endpoint).
- What happens when `--watch`'s refresh interval is set very low? A sensible default and minimum bound apply so this feature cannot be used to hammer the ledger file with unbounded-frequency reads; the exact bound is left to planning.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `bindle work status` MUST report, for every currently claimed work item, its claim owner, claimed-at time, and (if recorded) worktree/branch — sourced from the existing, unmodified `WorkLedger.get_claim()`, never a new claim representation.
- **FR-002**: `bindle work status` MUST report the set of tasks currently dispatchable, using the identical existing predicate `generate_external_projection()`/`generate_projection()`/`list_available_work_items()` already compute (open, unclaimed, unblocked) — this feature MUST NOT introduce a second, independently-maintained dispatchable computation.
- **FR-003**: `bindle work status` MUST report every currently blocked/waiting work item together with the specific unresolved dependency id(s) blocking it, sourced from the existing `WorkLedger.list_blocking()` — never merely a boolean.
- **FR-004**: `bindle work status` MUST report every milestone's current status and review-readiness (`is_review_ready()`, unchanged), and for each not-ready milestone, the same outstanding-reason detail `milestone_review.review_milestone()` already computes (blocked / no children / which specific child(ren)) — never a new readiness predicate.
- **FR-005**: `bindle work status` MUST include, for every reported item, its id and title (when present), so results are understandable without a maintainer separately cross-referencing raw ids.
- **FR-006**: `bindle work status`, invoked without `--watch`, MUST perform exactly one snapshot read and exit — it MUST NOT poll, refresh, or hold any connection open beyond that single read, regardless of whether `--json` is also given.
- **FR-007**: `bindle work status --json` MUST emit the identical semantic facts as FR-001–FR-005 in a single, stable, machine-parseable structure printed to stdout — never a scrape of the plain-text form, and never served over a network socket or HTTP endpoint introduced merely to provide JSON.
- **FR-008**: The structure emitted by FR-007 MUST be documented as this feature's own read-model contract (mirroring the documentation convention of `contracts/symphony-projection-v1.md`/`contracts/milestone-review-surface.md`), so a future presentation layer (including `bindle view`, User Story 5) can depend on it without re-deriving its own semantics.
- **FR-009**: `--watch` MUST be a separate, explicit opt-in flag on `bindle work status`; its absence MUST leave the command's behavior exactly as FR-006 describes.
- **FR-010**: When `--watch` is given, the system MUST re-run the identical snapshot computation (FR-001–FR-008) on a bounded interval, MUST NOT hold a long-lived write lock or otherwise block concurrent ledger operations between refreshes (each refresh is its own short-lived read, consistent with `WorkLedger`'s existing per-call connection lifecycle), and MUST exit cleanly on interruption without leaving any lock, temp file, or partial output behind.
- **FR-011**: `--watch` MAY accept an optional refresh-interval override; a sensible default and a minimum bound MUST apply when no override (or too small an override) is given, so this flag cannot be used to issue unbounded-frequency reads against the ledger file.
- **FR-012**: `bindle work forecast` MUST report, read-only: (a) every task currently dispatchable now (FR-002's identical fact); (b) every currently blocked/waiting item and its specific blocking id(s) (FR-003's identical fact); (c) for each currently-blocking id, which other item(s) would become unblocked-next (lose that blocker and have no other unresolved blocker remaining) if it resolved, under a counterfactual that holds every current ledger fact other than that one named dependency's resolution unchanged (Terminology) — and, for each such item that is a task, whether it would also be dispatchable-next (unblocked-next AND, under that same counterfactual, already `status = 'open'` and already unclaimed, i.e., would satisfy the existing dispatchable predicate) versus merely unblocked-next — a frontier computed by relating existing per-item blocking, status, and claim facts to each other, introducing no new blocking or dispatchable predicate; (d) every item blocked by more than one unresolved dependency, named explicitly as a convergence point; (e) a milestone review frontier: which milestones are review-ready now, and for each that is not, the same outstanding detail FR-004 already computes.
- **FR-013**: `bindle work forecast` MUST NOT report, estimate, or imply any wall-clock completion time, duration, or ETA for any item.
- **FR-014**: `bindle work forecast` MUST NOT assert or imply a guaranteed execution or completion order among multiple currently-dispatchable items, or among items that would become unblocked-next or dispatchable-next — it reports dependency structure only, and MUST NOT model, encode, or depend on Symphony's own scheduler candidate-ordering behavior (a Symphony-owned implementation detail outside this feature's scope).
- **FR-015**: `bindle work forecast` MUST be computed entirely from the existing, unmodified ledger read methods — it MUST NOT create, mutate, or simulate any work item, claim, or blocking edge (including a hypothetical "what if X were resolved" write) to produce its result.
- **FR-016**: `bindle view`, launched with no flags, MUST render exactly one snapshot of the semantic read model (FR-001–FR-005 and FR-012) with no automatic refresh.
- **FR-017**: `bindle view` MUST provide a manual refresh action that re-renders the current snapshot on demand without restarting the process.
- **FR-018**: `bindle view` MUST accept an explicit `--watch` flag, independent of any other flag, that enables periodic automatic refresh for that invocation only; watch state MUST NOT persist across invocations — each new launch defaults to snapshot-only unless `--watch` is supplied again for that launch.
- **FR-019**: `bindle view` MUST be local-machine/loopback-oriented — it MUST NOT expose the semantic read model, or any composed Symphony fact, to a non-local network interface by default.
- **FR-020**: `bindle view` MAY, when Symphony's existing local observability endpoint is reachable, additionally display Symphony's own runtime facts (running/retrying/blocked-on-input agents, workspace/worker information, last agent event or message) exactly as that endpoint reports them — sourced fresh on each render or refresh, never cached or persisted by Bindle, and visibly distinguished from Bindle's own semantic snapshot rather than merged into it.
- **FR-021**: `bindle view` MUST render Bindle's own semantic snapshot correctly, with no error and no degraded semantic content, when Symphony is not running or its observability endpoint is unreachable or returns unexpected data. If this implementation attempts FR-020's optional Symphony composition, the Symphony-sourced section is marked unavailable in that case, never a hard failure of the whole command; if FR-020 is deferred entirely (Assumptions), there is no Symphony-sourced section to mark, and correctly rendering Bindle's own snapshot is the whole of this requirement.
- **FR-022**: `bindle view` MUST NOT install, start, stop, configure, or otherwise supervise Symphony, and this feature MUST NOT introduce any `bindle symphony ...` command or equivalent lifecycle surface — any Symphony-facing behavior is limited to an optional, read-only request against an already-running instance's existing observability endpoint.
- **FR-023**: Every Bindle-owned fact reported by `bindle work status`, `bindle work forecast`, and `bindle view` (claims, blocking, dispatchable tasks, milestone readiness) MUST be fully available with Symphony absent, uninstalled, or never having run — none of the three commands' Bindle-owned rendering may require Symphony to be installed, configured, or running.

### Key Entities *(include if feature involves data)*

- **Work Status Snapshot**: A read-only, computed-on-request composition (FR-001–FR-005) over existing ledger state — claimed items, dispatchable tasks, blocked/waiting items with their blocking ids, and per-milestone status/readiness. Not a new stored entity: nothing is persisted, cached, or added to the schema; recomputed fresh on every request, exactly mirroring 001–004's "derived, never stored" precedent.
- **Dependency Frontier**: A read-only, computed-on-request graph-shaped view (FR-012) relating existing per-item blocking, status, and claim facts to each other — dispatchable-now items, blocked items and their blockers, convergence points, and, for each currently-blocking id, the reverse relationship distinguishing which item(s) would become unblocked-next from which (task-only) would further become dispatchable-next if that id resolved (Terminology). Not stored; not a new blocking or dispatchable predicate; derived entirely from `is_blocked()`/`list_blocking()` results already defined by specs/001–002, related to the existing `status`/claim facts already defined by specs/001–002.
- **Local View Render**: An ephemeral, on-demand or periodically refreshed presentation of a Work Status Snapshot and/or Dependency Frontier, optionally alongside Symphony Runtime Facts (below). Nothing about a render is persisted by Bindle between invocations.
- **Symphony Runtime Facts**: External, ephemeral facts sourced fresh from Symphony's own existing observability endpoint when reachable (running/retrying/blocked-on-input agents, workspace/worker info, last event/message). Bindle does not own, version, cache, or guarantee the availability of this contract — it is Symphony's, read only when `bindle view` chooses to compose it (FR-020), and always visibly attributed as Symphony's own data.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In constructed ledger scenarios covering every combination of task claim/dispatchable/blocked state, `bindle work status`'s reported facts match the existing `is_claimed()`/`get_claim()`/the dispatchable predicate/`is_blocked()`/`list_blocking()` computations in 100% of cases.
- **SC-002**: In the same scenarios, `bindle work status`'s milestone facts match `is_review_ready()` and `review_milestone()`'s existing outstanding-reason computation in 100% of cases.
- **SC-003**: `bindle work status --json`, parsed and compared against the plain-text form for the same ledger state, reports identical semantic facts in 100% of constructed cases.
- **SC-004**: Regenerating `bindle work status`'s snapshot (either form) twice against an unchanged ledger produces an identical result in 100% of cases.
- **SC-005**: `bindle work status` and `bindle work status --json`, invoked without `--watch`, perform exactly one snapshot read and exit in 100% of constructed test invocations.
- **SC-006**: With `--watch`, interrupting the command at any point leaves the ledger in exactly its pre-invocation state (no stray lock, no partial write, no mutation of any kind) in 100% of constructed scenarios.
- **SC-007**: In constructed dependency graphs (including convergence points — an item blocked by two or more dependencies — and at least one scenario with a claimed-but-blocked task, to exercise the unblocked-next/dispatchable-next distinction), `bindle work forecast`'s reported dispatchable set, blocking ids, convergence points, and unblocked-next/dispatchable-next relationships match a hand-computed graph derived from the same `blocked_by`, `status`, and claim facts in 100% of cases.
- **SC-008**: In 100% of constructed reviews of `bindle work forecast`'s output, it contains no time estimate, ETA, duration, or claim of guaranteed execution/completion order.
- **SC-009**: `bindle view`, launched with no flags, renders exactly one snapshot and performs no further ledger (or Symphony) reads until the maintainer triggers manual refresh or relaunches with `--watch`, in 100% of constructed test launches.
- **SC-010**: `bindle view` launched with no Symphony instance reachable renders Bindle's full semantic snapshot with zero errors, in 100% of constructed scenarios; when this implementation attempts FR-020's optional Symphony composition, that render additionally includes a clearly labeled unavailable Symphony section, and when FR-020 is deferred entirely (Assumptions), no Symphony section exists to label.
- **SC-011**: No requirement in this specification requires or introduces a new ledger table, column, or persisted derived fact — confirmed by review of the actual schema before and after implementation (mirrors specs/004 SC-008's exact framing).

## Assumptions

- **This feature is a composition and presentation layer, not a data-model feature.** Grounding against the actual repository found every individual fact this feature reports already computable from an existing, unmodified `WorkLedger`/`milestone_review` method (`is_claimed`, `get_claim`, the dispatchable predicate, `is_blocked`, `list_blocking`, `is_review_ready`, `review_milestone`, `list_milestones`). The genuine gap is narrower than a new subsystem: (1) nothing today composes task and milestone state into one cross-cutting view, (2) nothing computes the reverse dependency-frontier ("what becomes eligible if X resolves") relationship at all, and (3) no local visual surface exists. This specification is scoped to exactly that gap.
- **Existing-tools grounding**: `bindle milestone list`/`review`, the published `symphony-projection.sqlite3`, ad-hoc read-only SQLite queries against `.bindle-work/ledger.sqlite3`, and — when Symphony is running — its own Phoenix/LiveView dashboard and JSON observability API (`/api/v1/state`, `/api/v1/:issue_identifier`) already answer many individual questions in this space today. None of them compose task+milestone state together or compute a dependency frontier; this feature adds exactly that composition, not a reimplementation of any of the above.
- **Symphony grounding**: confirmed directly against the referenced fork's `development` branch that a Phoenix/LiveView dashboard (`elixir/lib/symphony_elixir_web/router.ex`) and a JSON observability API (`ObservabilityApiController`) already exist and report exactly the running/retrying/blocked/workspace/last-event facts `bindle view`'s optional composition (FR-020) draws on. **Note**: the checked-out fork (`f0029ef`) is 6 commits ahead of `docs/SYMPHONY.md`'s currently-pinned reference (`a9d5775`) as of this grounding pass — a documentation-currency gap noted here for visibility, not fixed by this specification. This feature does not attempt to reproduce Symphony's own LiveView dashboard or terminal status renderer (`status_dashboard.ex`) beyond the narrow facts FR-020 names.
- **Symphony's own scheduler candidate-ordering rule** (how it currently picks among several eligible tasks) is a Symphony-owned implementation detail this feature deliberately does not surface, encode, or keep in sync with (FR-014) — forecasting dependency structure is this feature's job; predicting or explaining Symphony's own dispatch choice is not.
- **No historical/event-log gap blocks any requirement here.** Every fact this feature requires (current status, current claim, current blocking edges, current review-readiness) is a current-state fact the ledger already retains. A related but explicitly out-of-scope capability — e.g., "what completed in the last day" or an activity/change feed — would require a persisted transition history the ledger does not keep today (only current state plus a single `updated_at` per row). This is recorded as a known follow-up gap, not absorbed into this feature.
- **The exact mechanism for locating a running Symphony instance's observability endpoint** (a conventional default, an environment variable, an explicit operator-supplied flag) is left to the planning stage; this specification requires only that the attempt is read-only, bounded (never hangs indefinitely), and degrades gracefully per FR-021 when absent or unreachable.
- **FR-020's optional Symphony composition and FR-021/User Story 5's own graceful-degradation framing describe one bundle of behavior, deferrable together.** FR-021 ("the Symphony-sourced section is marked unavailable, never a hard failure") and Acceptance Scenario US5.5 both presuppose an implementation that attempts FR-020's optional endpoint composition and found it absent or unreachable at that moment. An initial implementation that defers FR-020 entirely — attempting no Symphony discovery or composition of any kind — satisfies FR-021/US5.5 by rendering `bindle view` with no Symphony-runtime section at all, rather than a section that implies a reachability check occurred when none was attempted. FR-016–FR-019, FR-022, and FR-023 (rendering the semantic snapshot correctly, manual refresh, `--watch` opt-in, loopback-only exposure, no Symphony lifecycle ownership) are unaffected by this and remain required regardless of whether a given implementation attempts FR-020 at all.
- **`bindle view`'s implementation medium** (a local terminal UI, a local browser-rendered page, or another local-only presentation) is deliberately left to the planning stage, to be resolved against this repository's "no persistent web service unless the spec can demonstrate it is genuinely required" constraint (`AGENTS.md`) — this specification constrains only the surface's observable behavior (FR-016–FR-023), not its rendering technology.
- **Terminology is load-bearing.** "Dispatchable"/"claimed"/"running"/"blocked"/"waiting"/"review-ready"/"unblocked-next"/"dispatchable-next" are used exactly as defined in the Terminology section above; this feature introduces no new generic "ready" state spanning both a task's dispatchable fact and a milestone's review-ready fact. In particular, "unblocked-next" and "dispatchable-next" are never used interchangeably: losing a blocker (unblocked-next) is necessary but not sufficient for a task to be dispatchable-next — it must also still be `status = 'open'` and unclaimed under the same counterfactual — and "dispatchable-next" has no milestone equivalent at all, since "dispatchable" itself is task-only.

## Non-Goals

- No new ledger table, column, or persisted derived fact of any kind (mirrors SC-011).
- No completion-time estimation, ETA, or duration reporting anywhere in this feature.
- No guaranteed execution, dispatch, or completion order — `bindle work forecast` is a structural frontier, never a plan.
- No representation of, or dependency on, Symphony's own scheduler candidate-ordering behavior.
- No `bindle symphony ...` command or any Symphony lifecycle management (install, build, configure, start, stop, or supervise).
- No recreation of Symphony's own LiveView dashboard or terminal status renderer.
- No new arbitration, scheduler, or dependency-resolution mechanism inside Bindle — every blocking/readiness/dispatchable fact is read from, not recomputed independently of, `is_blocked()`/`list_blocking()`/`is_review_ready()`/the existing dispatchable predicate.
- No event log, activity feed, or history of past transitions (see Assumptions' follow-up-gap note).
- No network-exposed HTTP API introduced merely to serve `--json` — it remains stdout output from a CLI invocation.
- No automatic or implicit polling anywhere — every repeated observation requires the caller's explicit `--watch`.
- No persistent background daemon of any kind — `--watch` on either `bindle work status` or `bindle view` runs only for the lifetime of the invoking process and stops on interruption.
- No change to `specs/001`–`004`'s schema, milestone status vocabulary, lifecycle transitions, or existing write surfaces (`bindle work claim/release/done`, `bindle milestone ...`).
