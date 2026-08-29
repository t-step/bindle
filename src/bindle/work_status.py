"""Work-state visibility read model (specs/005-work-state-visibility).

Implements the accepted design in specs/005-work-state-visibility/
(spec.md, plan.md, research.md, data-model.md,
contracts/work-status-json-v1.md) — read those first for the "why" behind
anything here. This module is the single composition layer over the
already-implemented `WorkLedger`/`milestone_review` surfaces (specs/001-004):
every semantic fact it reports is read, verbatim, from an existing method —
`list_work_items`, `list_available_work_items`, `get_claim`, `list_blocking`,
and `milestone_review.review_milestone()` — never a second, independently
re-derived computation of blocking, claim, dispatchable, or review-ready
state (research.md's "one `WorkStatusSnapshot`, built once, consumed by
every renderer" decision).

This pass additionally implements User Story 4 (`bindle work forecast`):
`ForecastEntry`/`DependencyFrontier`, `build_forecast()`, and its
plain-text renderer.

This pass also implements User Story 3 (`bindle work status --watch`):
`DEFAULT_WATCH_INTERVAL_SECONDS`/`MIN_WATCH_INTERVAL_SECONDS`,
`resolve_watch_interval()`, and `watch_snapshots()` — a bounded-interval
generator that repeatedly re-runs the identical `build_snapshot()` this
module already exposes. `--watch` adds no second computation of any
kind; it is repeated delivery of the same snapshot, never a parallel
status path. `bindle view` (User Story 5) was evaluated and declined
from this feature's scope, not deferred to a later implementation unit
(docs/DECISIONS.md D045).
"""

from __future__ import annotations

import dataclasses
import math
import time
from typing import Callable, Iterator

from . import milestone_review
from . import work_ledger
from .work_ledger import ClaimInfo, WorkLedger


@dataclasses.dataclass(frozen=True)
class TaskStatusEntry:
    """One live (non-archived) `type='task'` work item's composed status."""

    id: str
    title: str | None
    status: str  # 'open' | 'done' | 'superseded' — WorkItem.status, verbatim
    claim: ClaimInfo | None  # WorkLedger.get_claim(id), verbatim
    dispatchable: bool  # True iff id appears in list_available_work_items()'s
    # own return value — never independently re-derived from
    # status/claim/blocking_ids (research.md)
    blocking_ids: list[str]  # WorkLedger.list_blocking(id), verbatim; [] when not blocked


@dataclasses.dataclass(frozen=True)
class MilestoneStatusEntry:
    """One live (non-archived) `type='milestone'` work item's composed status."""

    id: str
    title: str | None
    status: str  # 'open' | 'review' | 'accepted' | 'superseded'
    claim: ClaimInfo | None  # milestone_review.review_milestone(id).view.claim, verbatim
    review_ready: bool  # ...view.review_ready, verbatim — never a second
    # is_review_ready() call or re-derivation
    not_ready_reason: list[str]  # ...view.not_ready_reason, verbatim — empty iff review_ready
    blocking_ids: list[str]  # ...view.blocking_ids, verbatim; [] when not blocked


@dataclasses.dataclass(frozen=True)
class WorkStatusSnapshot:
    """Not a stored entity — computed fresh on every `build_snapshot()`
    call from existing `WorkLedger`/`milestone_review` reads only.

    Every list is ordered by `id`, matching `list_work_items()`'s own
    order, so two builds against an unchanged ledger produce identically
    ordered output (spec.md SC-004). Carries no wall-clock "generated at"
    field — see research.md, "No timestamp field in the JSON contract"
    (required for SC-004's byte-identical-output guarantee).
    """

    tasks: list[TaskStatusEntry]
    milestones: list[MilestoneStatusEntry]


def build_snapshot(ledger: WorkLedger) -> WorkStatusSnapshot:
    """One ledger pass: `list_work_items()` (filtered to `archived_at is
    None` — matching `generate_projection()`/`generate_external_projection()`'s
    own live-only convention, since an archived item is not part of
    "current work state"), `list_available_work_items()` once for the
    task-dispatchable id set, then `get_claim()`/`list_blocking()` per task
    and `milestone_review.review_milestone()` per milestone. No
    `WorkLedger` mutation method is ever called — this function is
    strictly read-only.
    """
    dispatchable_ids = set(ledger.list_available_work_items())
    tasks: list[TaskStatusEntry] = []
    milestones: list[MilestoneStatusEntry] = []

    for item in ledger.list_work_items():
        if item.archived_at is not None:
            continue
        if item.type == "task":
            tasks.append(
                TaskStatusEntry(
                    id=item.id,
                    title=item.title,
                    status=item.status,
                    claim=ledger.get_claim(item.id),
                    dispatchable=item.id in dispatchable_ids,
                    blocking_ids=ledger.list_blocking(item.id),
                )
            )
        elif item.type == "milestone":
            view = milestone_review.review_milestone(ledger, item.id).view
            milestones.append(
                MilestoneStatusEntry(
                    id=view.id,
                    title=view.title,
                    status=view.status,
                    claim=view.claim,
                    review_ready=view.review_ready,
                    not_ready_reason=view.not_ready_reason,
                    blocking_ids=view.blocking_ids,
                )
            )

    return WorkStatusSnapshot(tasks=tasks, milestones=milestones)


# -- Watch mode (User Story 3: `bindle work status --watch`) -------------

DEFAULT_WATCH_INTERVAL_SECONDS = 2.0
MIN_WATCH_INTERVAL_SECONDS = 1.0


def resolve_watch_interval(requested: float | None) -> float:
    """FR-011: no override -> `DEFAULT_WATCH_INTERVAL_SECONDS`; an
    override at or above `MIN_WATCH_INTERVAL_SECONDS` -> used as given;
    an override below the minimum -> clamped up to the minimum, never
    rejected outright. Shared by every `--watch`-bearing command this
    feature adds, so none can silently diverge on the bound.

    A non-finite override (`nan`, `inf`, `-inf`) is rejected outright:
    `max()` cannot clamp it to the minimum (`nan` compares false to
    everything and passes through unchanged; `inf` already compares
    above the minimum), and passing it on to `sleep()` fails with a
    platform-specific, uninformative error instead of a clear one.
    """
    if requested is None:
        return DEFAULT_WATCH_INTERVAL_SECONDS
    if not math.isfinite(requested):
        raise ValueError(f"--interval must be a finite number, got {requested!r}")
    return max(requested, MIN_WATCH_INTERVAL_SECONDS)


def watch_snapshots(
    ledger: WorkLedger,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[WorkStatusSnapshot]:
    """Yield a freshly built `WorkStatusSnapshot` forever: the first
    snapshot is produced immediately (no wait before the first read),
    then `sleep(interval)` runs before every subsequent one — the
    "bounded interval" FR-010 requires. Each iteration is exactly one
    `build_snapshot()` call, the identical one-shot computation `bindle
    work status` already uses; nothing here re-derives or caches a
    fact, and no lock, temp file, thread, or filesystem watcher is ever
    created, so a caller that stops iterating (or that lets
    `KeyboardInterrupt` propagate out of `sleep()`) leaves the ledger in
    exactly the state its last completed read observed (SC-006). `sleep`
    is the injected seam this feature needs to test a bounded number of
    iterations without waiting on wall-clock time or a real infinite
    loop — no generalized watcher abstraction, no background thread.
    """
    while True:
        yield build_snapshot(ledger)
        sleep(interval)


# -- Dependency frontier (User Story 4: `bindle work forecast`) ----------


@dataclasses.dataclass(frozen=True)
class ForecastEntry:
    """What becomes eligible if one specific currently-blocking id
    resolved, holding every other current ledger fact unchanged
    (spec.md Terminology: "Forecast").
    """

    resolved_blocker_id: str  # may name a dangling/nonexistent work item,
    # reported exactly as declared (research.md)
    unblocked_next: list[str]  # item ids (task or milestone) whose
    # blocking_ids becomes empty once this one id is removed — ordered by id
    dispatchable_next: list[str]  # subset of unblocked_next that are tasks
    # for which work_ledger.is_dispatchable(status, claimed, blocked=False)
    # is True; never computed for a milestone (Terminology: "no milestone
    # equivalent")


@dataclasses.dataclass(frozen=True)
class DependencyFrontier:
    dispatchable_now: list[str]  # == snapshot's own task-dispatchable id
    # list, passed through unchanged
    convergence_points: list[str]  # item ids (task or milestone) with
    # len(blocking_ids) > 1, ordered by id
    frontier: list[ForecastEntry]  # one entry per distinct id appearing in
    # any item's blocking_ids, ordered by resolved_blocker_id


def build_forecast(snapshot: WorkStatusSnapshot) -> DependencyFrontier:
    """Pure function: `snapshot` in, `DependencyFrontier` out. No
    `WorkLedger` parameter — cannot issue a ledger query even by accident
    (FR-015). Calls `work_ledger.is_dispatchable()` once per
    unblocked-next task candidate to decide `dispatchable_next` — the same
    function `list_available_work_items()` itself routes through, so
    there is exactly one authoritative expression of task dispatchability,
    evaluated against two different fact sources (live query vs.
    counterfactual snapshot), never two different rules.
    """
    items: list[tuple[str, list[str]]] = [(t.id, t.blocking_ids) for t in snapshot.tasks]
    items.extend((m.id, m.blocking_ids) for m in snapshot.milestones)

    dispatchable_now = sorted(t.id for t in snapshot.tasks if t.dispatchable)
    convergence_points = sorted(
        item_id for item_id, blocking_ids in items if len(blocking_ids) > 1
    )

    blocker_ids: set[str] = set()
    for _, blocking_ids in items:
        blocker_ids.update(blocking_ids)

    tasks_by_id = {t.id: t for t in snapshot.tasks}

    frontier: list[ForecastEntry] = []
    for blocker_id in sorted(blocker_ids):
        unblocked_next = sorted(
            item_id for item_id, blocking_ids in items if blocking_ids == [blocker_id]
        )
        dispatchable_next = sorted(
            item_id
            for item_id in unblocked_next
            if item_id in tasks_by_id
            and work_ledger.is_dispatchable(
                tasks_by_id[item_id].status,
                tasks_by_id[item_id].claim is not None,
                False,
            )
        )
        frontier.append(
            ForecastEntry(
                resolved_blocker_id=blocker_id,
                unblocked_next=unblocked_next,
                dispatchable_next=dispatchable_next,
            )
        )

    return DependencyFrontier(
        dispatchable_now=dispatchable_now,
        convergence_points=convergence_points,
        frontier=frontier,
    )


def _dispatchable_next_gap_reason(
    unblocked_next: list[str],
    dispatchable_next: list[str],
    tasks_by_id: dict[str, TaskStatusEntry],
) -> str:
    """Explain, for the plain-text renderer only, why an unblocked-next
    task did not also become dispatchable-next — e.g. "D remains claimed".
    Never applied to a milestone id (no milestone equivalent exists).
    """
    reasons = []
    for item_id in unblocked_next:
        if item_id in dispatchable_next:
            continue
        task = tasks_by_id.get(item_id)
        if task is None:
            continue  # a milestone id — no dispatchable-next concept applies
        if task.claim is not None:
            reasons.append(f"{item_id} remains claimed")
        elif task.status != "open":
            reasons.append(f"{item_id} status={task.status}")
    return " — " + "; ".join(reasons) if reasons else ""


def render_forecast_text(snapshot: WorkStatusSnapshot, frontier: DependencyFrontier) -> str:
    """The plain-text form of `bindle work forecast` (spec.md User Story 4).

    Structural dependency topology only — no time, date, duration, or
    ETA of any kind (FR-013/SC-008); the milestone review frontier reads
    `snapshot.milestones` directly rather than a second milestone-facing
    structure (data-model.md).
    """
    tasks_by_id = {t.id: t for t in snapshot.tasks}
    items = list(snapshot.tasks) + list(snapshot.milestones)
    convergence = set(frontier.convergence_points)

    lines = [
        "dispatchable now: "
        + (", ".join(frontier.dispatchable_now) if frontier.dispatchable_now else "(none)")
    ]

    lines.append("blocked:")
    for item in sorted(items, key=lambda i: i.id):
        if not item.blocking_ids:
            continue
        suffix = "  (convergence point)" if item.id in convergence else ""
        lines.append(f"  {item.id}  blocked on: {', '.join(item.blocking_ids)}{suffix}")

    for entry in frontier.frontier:
        lines.append(f"if {entry.resolved_blocker_id} resolves:")
        if entry.unblocked_next:
            lines.append("  unblocked-next: " + ", ".join(entry.unblocked_next))
            if entry.dispatchable_next:
                lines.append("  dispatchable-next: " + ", ".join(entry.dispatchable_next))
            else:
                reason = _dispatchable_next_gap_reason(
                    entry.unblocked_next, entry.dispatchable_next, tasks_by_id
                )
                lines.append(f"  dispatchable-next: (none{reason})")
        else:
            lines.append("  unblocked-next: (none)")

    lines.append("milestone review frontier:")
    for m in snapshot.milestones:
        readiness = (
            "ready"
            if m.review_ready
            else f"not ready ({format_not_ready_reason(m.not_ready_reason, m.blocking_ids)})"
        )
        lines.append(f"  {m.id}  {readiness}")

    return "\n".join(lines)


# -- Plain-text rendering -------------------------------------------------


def format_not_ready_reason(reasons: list[str], blocking_ids: list[str]) -> str:
    """Render a milestone's `not_ready_reason` (a flat subset of
    `{"blocked", "no_children"}` plus one entry per outstanding child id)
    as one human-readable clause.

    Shared verbatim between `bindle milestone review` (`cli.py`) and this
    module's own `bindle work status` renderer (research.md's "plain-text
    `not_ready_reason` rendering reuses `_format_not_ready_reason()`"
    decision) — never a second, hand-copied formatter that could drift in
    wording from the other's output for the identical underlying fact.
    """
    parts = []
    if "blocked" in reasons:
        parts.append(
            "blocked by: " + ", ".join(blocking_ids) if blocking_ids else "blocked"
        )
    if "no_children" in reasons:
        parts.append("no_children")
    outstanding = [r for r in reasons if r not in ("blocked", "no_children")]
    if outstanding:
        parts.append("outstanding: " + ", ".join(outstanding))
    return ", ".join(parts)


def _format_claim_suffix(claim: ClaimInfo | None) -> str:
    if claim is None:
        return ""
    return f"  claimed by {claim.owner} at {claim.claimed_at}"


def _format_task_line(task: TaskStatusEntry) -> str:
    parts = [task.id, task.status]
    if task.dispatchable:
        parts.append("dispatchable")
    elif task.blocking_ids:
        parts.append("blocked on: " + ", ".join(task.blocking_ids))
    return "  ".join(parts) + _format_claim_suffix(task.claim)


def _format_milestone_line(milestone: MilestoneStatusEntry) -> str:
    readiness = (
        "ready"
        if milestone.review_ready
        else f"not ready ({format_not_ready_reason(milestone.not_ready_reason, milestone.blocking_ids)})"
    )
    parts = [milestone.id, milestone.status, readiness]
    return "  ".join(parts) + _format_claim_suffix(milestone.claim)


def render_status_text(snapshot: WorkStatusSnapshot) -> str:
    """The plain-text form of `bindle work status` (spec.md User Story 1).

    Renders an empty-but-valid snapshot cleanly — `tasks:`/`milestones:`
    headers with nothing under them — never an error (spec.md Edge Cases,
    Acceptance Scenario US1.5).
    """
    lines = ["tasks:"]
    lines.extend(f"  {_format_task_line(task)}" for task in snapshot.tasks)
    lines.append("milestones:")
    lines.extend(f"  {_format_milestone_line(m)}" for m in snapshot.milestones)
    return "\n".join(lines)


# -- JSON serialization (contracts/work-status-json-v1.md) ----------------


def _claim_to_json(claim: ClaimInfo | None) -> dict | None:
    if claim is None:
        return None
    return {
        "owner": claim.owner,
        "claimed_at": claim.claimed_at,
        "worktree_path": claim.worktree_path,
        "branch": claim.branch,
    }


def snapshot_to_json(snapshot: WorkStatusSnapshot) -> dict:
    """Serialize `snapshot` per `contracts/work-status-json-v1.md`,
    field-for-field — the identical `WorkStatusSnapshot` object
    `render_status_text()` reads, never a second, independently-derived
    computation (spec.md SC-003). Carries no wall-clock "generated at"
    field anywhere (spec.md SC-004; research.md's "no timestamp field in
    the JSON contract" decision).
    """
    return {
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "claim": _claim_to_json(task.claim),
                "dispatchable": task.dispatchable,
                "blocking_ids": list(task.blocking_ids),
            }
            for task in snapshot.tasks
        ],
        "milestones": [
            {
                "id": m.id,
                "title": m.title,
                "status": m.status,
                "claim": _claim_to_json(m.claim),
                "review_ready": m.review_ready,
                "not_ready_reason": list(m.not_ready_reason),
                "blocking_ids": list(m.blocking_ids),
            }
            for m in snapshot.milestones
        ],
    }
