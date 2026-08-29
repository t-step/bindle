# Data Model: Work-State Visibility

This feature adds no new table, no new column, and no schema version bump — `work_items`, `work_item_blocked_by`, `work_item_claims`, `work_item_evidence` are all unchanged from schema version 3 (`specs/003-symphony-task-integration/data-model.md`). Every read this feature needs — `list_work_items`, `list_available_work_items`, `list_blocking`, `get_claim`, and, via `milestone_review.review_milestone()`, `is_review_ready`/`has_qualifying_evidence`/`is_blocked` — already exists, already tested, and is unchanged in *external* behavior (return value, ordering). It adds one new module, `src/bindle/work_status.py`, composing them into a shared, never-persisted read model plus one small in-memory derived structure, and one small addition to `work_ledger.py` — a pure, stateless predicate function, not a query — that `list_available_work_items()`'s own internal implementation is refactored to route through, so the live and counterfactual dispatchability paths share one authoritative rule rather than two independently-maintained expressions of it (`research.md`, "dispatchable-next shares one authoritative predicate").

## New `WorkLedger` function (`src/bindle/work_ledger.py`)

```python
def is_dispatchable(status: str, claimed: bool, blocked: bool) -> bool:
    """The exact task-dispatchability rule list_available_work_items()'s own
    SQL encodes (status == 'open' AND NOT claimed AND NOT blocked), factored
    out as a pure, I/O-free function so it is evaluated identically against
    live ledger state and against a read-only forecast counterfactual. Takes
    no `type` argument — every caller already scopes to type == 'task'
    before calling this, the same structural precondition
    list_available_work_items()'s own query already applies."""
    return status == "open" and not claimed and not blocked
```

`list_available_work_items()`'s own internal implementation is refactored to fetch candidate `type = 'task'` rows with their claimed/blocked booleans and apply `is_dispatchable()` per row in Python, rather than inlining the same three conjuncts a second time in its SQL `WHERE` clause — its external behavior, return value, and ordering are unchanged, verified by its own existing, unmodified test suite. `tests/test_work_status.py` additionally includes a matrix test asserting `is_dispatchable()` agrees with `list_available_work_items()`'s own return value for every constructed task, as a regression guard on the refactor (`research.md`, "dispatchable-next shares one authoritative predicate").

## Work Status Snapshot (`src/bindle/work_status.py`)

Not a stored entity — computed fresh on every `build_snapshot()` call from existing `WorkLedger`/`milestone_review` reads only, mirroring `MilestoneReviewView`'s (specs/004) own "derived, never stored" precedent. Every list is ordered by `id`, matching `list_work_items()`'s own order, so two builds against an unchanged ledger produce identically-ordered output (spec.md SC-004).

```python
@dataclasses.dataclass(frozen=True)
class TaskStatusEntry:
    """One live (non-archived) type='task' work item's composed status."""
    id: str
    title: str | None
    status: str                  # 'open' | 'done' | 'superseded' — WorkItem.status, verbatim
    claim: ClaimInfo | None      # WorkLedger.get_claim(id), verbatim
    dispatchable: bool           # True iff id appears in list_available_work_items()'s
                                  # own return value — never independently re-derived
                                  # from status/claim/blocking_ids (research.md)
    blocking_ids: list[str]      # WorkLedger.list_blocking(id), verbatim; [] when not blocked

@dataclasses.dataclass(frozen=True)
class MilestoneStatusEntry:
    """One live (non-archived) type='milestone' work item's composed status."""
    id: str
    title: str | None
    status: str                  # 'open' | 'review' | 'accepted' | 'superseded'
    claim: ClaimInfo | None      # milestone_review.review_milestone(id).view.claim, verbatim
    review_ready: bool           # ...view.review_ready, verbatim — never a second
                                  # is_review_ready() call or re-derivation
    not_ready_reason: list[str]  # ...view.not_ready_reason, verbatim — empty iff review_ready
    blocking_ids: list[str]      # ...view.blocking_ids, verbatim; [] when not blocked

@dataclasses.dataclass(frozen=True)
class WorkStatusSnapshot:
    tasks: list[TaskStatusEntry]           # every live type='task' item, ordered by id
    milestones: list[MilestoneStatusEntry] # every live type='milestone' item, ordered by id


def build_snapshot(ledger: WorkLedger) -> WorkStatusSnapshot:
    """One ledger pass: list_work_items() (filtered to archived_at is None —
    matching generate_projection()/generate_external_projection()'s own
    live-only convention, since an archived item is not part of 'current work
    state'), list_available_work_items() once for the task-dispatchable id
    set, then get_claim()/list_blocking() per task and
    milestone_review.review_milestone() per milestone. No WorkLedger mutation
    method is ever called. Carries no wall-clock 'generated at' field —
    see research.md, 'No timestamp field in the JSON contract' (required for
    SC-004's byte-identical-output guarantee)."""
```

**Why no shared base class or generic "ready"/"state" field**: `TaskStatusEntry.dispatchable` and `MilestoneStatusEntry.review_ready` are deliberately distinct fields on structurally independent dataclasses, not a common field on a shared parent — Terminology's own rule ("this feature introduces no new generic 'ready' state spanning both a task's dispatchable fact and a milestone's review-ready fact") is enforced by the type system, not by convention a future caller could bypass.

## Dependency Frontier (`src/bindle/work_status.py`)

Also not stored — a pure, in-memory relation computed from an already-built `WorkStatusSnapshot`'s `blocking_ids`/`status`/`claim` fields. `build_forecast()` issues zero ledger queries (research.md, "forecast is a pure relate over snapshot facts").

```python
@dataclasses.dataclass(frozen=True)
class ForecastEntry:
    """What becomes eligible if one specific currently-blocking id resolved,
    holding every other current ledger fact unchanged (Terminology:
    'Forecast')."""
    resolved_blocker_id: str      # the hypothetically-resolved id — may name
                                  # a dangling/nonexistent work item, reported
                                  # exactly as declared (research.md)
    unblocked_next: list[str]     # item ids (task or milestone) whose
                                  # blocking_ids becomes empty once this one
                                  # id is removed — ordered by id
    dispatchable_next: list[str]  # subset of unblocked_next that are tasks
                                  # for which work_ledger.is_dispatchable(
                                  # status, claimed, blocked=False) is True —
                                  # status/claimed read unchanged from the
                                  # snapshot, blocked=False supplied by the
                                  # counterfactual itself (research.md,
                                  # "dispatchable-next shares one
                                  # authoritative predicate"); never computed
                                  # for a milestone (Terminology: "no
                                  # milestone equivalent")

@dataclasses.dataclass(frozen=True)
class DependencyFrontier:
    dispatchable_now: list[str]              # == snapshot's own task-dispatchable
                                              # id list, passed through unchanged
    convergence_points: list[str]            # item ids (task or milestone) with
                                              # len(blocking_ids) > 1, ordered by id
    frontier: list[ForecastEntry]            # one entry per distinct id appearing
                                              # in any item's blocking_ids, ordered
                                              # by resolved_blocker_id


def build_forecast(snapshot: WorkStatusSnapshot) -> DependencyFrontier:
    """Pure function: snapshot in, DependencyFrontier out. No WorkLedger
    parameter — cannot issue a ledger query even by accident. Calls
    work_ledger.is_dispatchable() (imported, not re-derived) once per
    unblocked_next candidate to decide dispatchable_next — the same
    function list_available_work_items() itself is planned to route
    through, so there is exactly one authoritative Python expression of
    task dispatchability, evaluated against two different fact sources
    (live query vs. counterfactual snapshot), never two different rules.
    The milestone review frontier (FR-012e) is not a separate structure
    here: it is snapshot.milestones itself (review_ready + not_ready_reason
    are already present on every MilestoneStatusEntry) — bindle work
    forecast's renderer reads snapshot.milestones directly, alongside this
    DependencyFrontier, rather than this module inventing a second
    milestone-facing shape."""
```

## What `bindle work status --json` serializes (`contracts/work-status-json-v1.md`)

`WorkStatusSnapshot` (tasks + milestones) only — `DependencyFrontier` is `bindle work forecast`'s own plain-text-only output in this feature (research.md, `--watch` interval decision's sibling note: no FR/SC requires a `--json` form of forecast, so none is added). `bindle view` renders both `WorkStatusSnapshot` and a `DependencyFrontier` derived from it, but as HTML, not as a second JSON contract — `bindle view` is a rendering surface over the identical semantic facts, not a second published data interface (unlike `symphony_projection.py`'s own separately-versioned external contract, which this feature does not touch).

## What is explicitly not a new entity

- No new `work_items` status value, column, or table — every status/claim/blocking/readiness fact already exists in schema version 3.
- No cached, persisted, or stored "snapshot" row anywhere — `WorkStatusSnapshot`/`DependencyFrontier` are in-memory objects that exist only for the duration of one CLI invocation or one `bindle view` HTTP request, exactly mirroring `is_review_ready()`/`MilestoneReviewView`'s own "derived, never stored" precedent (specs/002/004).
- No event log, activity journal, or history of past transitions — `WorkStatusSnapshot` holds only current-state facts (spec.md Non-Goals; Assumptions' own "no historical/event-log gap" note).
- No second, Bindle-owned copy of Symphony's runtime state — this feature adds no Symphony-facing dataclass, field, or read at all (research.md, "Symphony endpoint discovery has no safe zero-config default").
