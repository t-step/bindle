"""Work-state visibility read model (specs/005-work-state-visibility).

Single composition layer over `WorkLedger`/`milestone_review` (specs/001-004):
every fact reported is read verbatim from `list_work_items`,
`list_available_work_items`, `get_claim`, `list_blocking`, or
`milestone_review.review_milestone()`, never re-derived (research.md: one
`WorkStatusSnapshot`, built once, consumed by every renderer). The 005
spec/plan/research/data-model and contracts/work-status-json-v1.md hold the
"why".

Also holds `bindle work forecast` (`ForecastEntry`/`DependencyFrontier`,
`build_forecast()`, its text renderer) and `bindle work status --watch`
(`resolve_watch_interval()`, `watch_snapshots()`): repeated delivery of the same
`build_snapshot()`, never a parallel status path. `bindle view` (User Story 5)
was declined, not deferred (D045).
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
    dispatchable: bool  # id in list_available_work_items(); never re-derived
    blocking_ids: list[str]  # WorkLedger.list_blocking(id), verbatim; [] when not blocked


@dataclasses.dataclass(frozen=True)
class MilestoneStatusEntry:
    """One live (non-archived) `type='milestone'` work item's composed status."""

    id: str
    title: str | None
    status: str  # 'open' | 'review' | 'accepted' | 'superseded'
    claim: ClaimInfo | None  # milestone_review.review_milestone(id).view.claim, verbatim
    review_ready: bool  # ...view.review_ready, verbatim; never re-derived
    not_ready_reason: list[str]  # ...view.not_ready_reason, verbatim — empty iff review_ready
    blocking_ids: list[str]  # ...view.blocking_ids, verbatim; [] when not blocked


@dataclasses.dataclass(frozen=True)
class WorkStatusSnapshot:
    """Not a stored entity: computed fresh per `build_snapshot()` from existing
    reads only.

    Lists are ordered by `id` (as `list_work_items()`), and there is no
    wall-clock "generated at" field, so builds against an unchanged ledger are
    byte-identical (SC-004; research.md).
    """

    tasks: list[TaskStatusEntry]
    milestones: list[MilestoneStatusEntry]


def build_snapshot(ledger: WorkLedger) -> WorkStatusSnapshot:
    """One strictly read-only ledger pass; no `WorkLedger` mutation method is
    ever called.

    Live (non-archived) items only, as
    `generate_projection()`/`generate_external_projection()`: an archived item
    is not current work state.
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


DEFAULT_WATCH_INTERVAL_SECONDS = 2.0
MIN_WATCH_INTERVAL_SECONDS = 1.0


def resolve_watch_interval(requested: float | None) -> float:
    """FR-011: no override -> the default; below the minimum -> clamped up,
    never rejected.

    Shared by every `--watch` command so none can diverge on the bound.

    A non-finite override (`nan`, `inf`, `-inf`) raises `ValueError`: `max()`
    cannot clamp it (`nan` compares false to everything and passes through;
    `inf` is already above the minimum) and `sleep()` would fail with a
    platform-specific, uninformative error.
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
    """Yield a fresh `WorkStatusSnapshot` forever: the first immediately, then
    `sleep(interval)` before each later one (FR-010's "bounded interval").

    Each iteration is one `build_snapshot()`, the same computation as `bindle
    work status`; no lock, temp file, thread, or filesystem watcher is created,
    so stopping iteration (or a `KeyboardInterrupt` out of `sleep()`) leaves the
    ledger as its last completed read saw it (SC-006). `sleep` is injected so
    tests can bound iterations without real waiting.
    """
    while True:
        yield build_snapshot(ledger)
        sleep(interval)


@dataclasses.dataclass(frozen=True)
class ForecastEntry:
    """What becomes eligible if one currently-blocking id resolved, all other
    ledger facts unchanged.

    (spec.md Terminology: "Forecast")
    """

    resolved_blocker_id: str  # may name a dangling item, reported as declared
    unblocked_next: list[str]  # ids (task or milestone) blocked only by this id
    dispatchable_next: list[str]  # dispatchable tasks in unblocked_next


@dataclasses.dataclass(frozen=True)
class DependencyFrontier:
    dispatchable_now: list[str]  # snapshot's dispatchable task ids, unchanged
    convergence_points: list[str]  # ids with len(blocking_ids) > 1, by id
    frontier: list[ForecastEntry]  # one entry per distinct blocker id


def build_forecast(snapshot: WorkStatusSnapshot) -> DependencyFrontier:
    """Pure: `snapshot` in, `DependencyFrontier` out; no `WorkLedger` parameter,
    so no ledger query (FR-015).

    `dispatchable_next` uses `work_ledger.is_dispatchable()`, the same function
    `list_available_work_items()` routes through: one dispatchability rule over
    two fact sources (live query vs. counterfactual snapshot).
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
    """Plain-text renderer only: why an unblocked-next task is not
    dispatchable-next (e.g. "D remains claimed").

    Never applied to a milestone id (no milestone equivalent).
    """
    reasons = []
    for item_id in unblocked_next:
        if item_id in dispatchable_next:
            continue
        task = tasks_by_id.get(item_id)
        if task is None:
            continue
        if task.claim is not None:
            reasons.append(f"{item_id} remains claimed")
        elif task.status != "open":
            reasons.append(f"{item_id} status={task.status}")
    return " — " + "; ".join(reasons) if reasons else ""


def render_forecast_text(snapshot: WorkStatusSnapshot, frontier: DependencyFrontier) -> str:
    """The plain-text form of `bindle work forecast` (spec.md User Story 4).

    Structural topology only: no time, date, duration, or ETA (FR-013/SC-008).
    The milestone frontier reads `snapshot.milestones` directly, not a second
    milestone-facing structure (data-model.md).
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


def format_not_ready_reason(reasons: list[str], blocking_ids: list[str]) -> str:
    """Render a milestone's `not_ready_reason` (a subset of `{"blocked",
    "no_children"}` plus one entry per outstanding child id) as one clause.

    Shared by `bindle milestone review` (`cli.py`) and this module's `bindle
    work status` renderer so the wording for the same fact cannot drift
    (research.md).
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

    An empty snapshot renders as bare `tasks:`/`milestones:` headers, never an
    error (Edge Cases, US1.5).
    """
    lines = ["tasks:"]
    lines.extend(f"  {_format_task_line(task)}" for task in snapshot.tasks)
    lines.append("milestones:")
    lines.extend(f"  {_format_milestone_line(m)}" for m in snapshot.milestones)
    return "\n".join(lines)


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
    field-for-field.

    Reads the same `WorkStatusSnapshot` as `render_status_text()` (SC-003); no
    wall-clock "generated at" field (SC-004; research.md).
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
