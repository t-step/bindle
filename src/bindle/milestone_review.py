"""Milestone review surface (specs/004-milestone-review-surface).

A human-facing, CLI-reachable presentation and write-wrapper layer over the
milestone review lifecycle `work_ledger.py` already implements and tests
(`is_review_ready`, `mark_in_review`, `decline_review`, `accept_milestone`,
`has_qualifying_evidence`): no new lifecycle behavior, persisted state, or
arbitration mechanism. The 004 spec/plan/research/data-model and
contracts/milestone-review-surface.md hold the "why".

Same shape as `symphony_projection.py`'s
`claim_task`/`release_task`/`complete_task` (type check, then delegation to an
unmodified `WorkLedger` method) but for milestones, and deliberately kept apart
from that Symphony-facing module (plan.md "Structure Decision") so
`work_ledger.py` never becomes a reviewer-specific adapter.
"""

from __future__ import annotations

import dataclasses

from .work_ledger import ClaimInfo, EvidencePointer, WorkItem, WorkLedger


def _resolve_milestone(
    ledger: WorkLedger, work_item_id: str
) -> tuple[WorkItem | None, str | None]:
    """Type guard every function in this module calls first, so it cannot drift
    between commands (FR-009, US5).

    Returns `(item, None)` for a `type='milestone'` row, `(None, 'not_found')`
    when the id resolves to no work item, or `(None, 'not_a_milestone')` for a
    `type='task'` row.
    """
    item = ledger.get_work_item(work_item_id)
    if item is None:
        return None, "not_found"
    if item.type != "milestone":
        return None, "not_a_milestone"
    return item, None


@dataclasses.dataclass(frozen=True)
class TransitionResult:
    """Result of `enter_review()`.

    `ok=True` iff the milestone moved to `review`; else `reason` is
    `"not_found"`, `"not_a_milestone"`, or `"not_ready_or_not_open"`
    (`WorkLedger.mark_in_review()`'s refusal).
    """

    ok: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class ClaimResult:
    """Result of `claim_milestone()`.

    `ok=True` iff the claim was acquired; else `reason` is `"not_found"`,
    `"not_a_milestone"`, or `"already_claimed"` (`WorkLedger.claim()`'s ordinary
    "someone else holds it" outcome).
    """

    ok: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class ReleaseResult:
    """Result of `release_milestone()`.

    `ok=True` iff the release was performed, which per
    `WorkLedger.release_claim()`'s "safe release" guarantee includes a claim
    already absent or held by another owner (a no-op, never an error); else
    `reason` is `"not_found"` or `"not_a_milestone"`.
    """

    ok: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class DecisionResult:
    """Result of `accept()`/`decline()`.

    `ok` reflects the status transition only: `True` iff the milestone
    transitioned (`accepted` or back to `open`). `reason` is `None` when `ok`;
    else `"not_found"` | `"not_a_milestone"` | `"not_in_review"`.

    `rationale_error` is `None` unless the transition succeeded, a locator was
    supplied, and the separate `add_evidence()` call then raised (then
    `str(exception)`); always `None` when `ok` is `False`, since a rejected
    transition never records evidence (FR-010). `ok=True` with `rationale_error`
    set means the decision is committed as requested but the optional evidence
    pointer was not recorded; the transition is never retried or rolled back
    (FR-010a).
    """

    ok: bool
    reason: str | None
    rationale_error: str | None


@dataclasses.dataclass(frozen=True)
class ChildTaskView:
    """One child task, as reported on a `MilestoneReviewView`."""

    id: str
    title: str | None
    status: str
    has_qualifying_evidence: bool
    evidence: list[EvidencePointer]
    is_blocked: bool


@dataclasses.dataclass(frozen=True)
class MilestoneReviewView:
    """Read-only report over one milestone, composed fresh per
    `review_milestone()` from `WorkLedger` reads.

    Not a stored entity. `review_ready` is `is_review_ready()`'s value, read
    once and never recomputed (FR-002).
    """

    id: str
    title: str | None
    status: str
    review_ready: bool
    not_ready_reason: list[str]
    is_blocked: bool
    blocking_ids: list[str]
    claim: ClaimInfo | None
    children: list[ChildTaskView]


@dataclasses.dataclass(frozen=True)
class ReviewResult:
    """Result of `review_milestone()`: the `ok`/`reason` shape of the results
    above plus `view` (None unless `ok`)."""

    ok: bool
    reason: str | None
    view: MilestoneReviewView | None


def review_milestone(ledger: WorkLedger, work_item_id: str) -> ReviewResult:
    """Report a milestone's status, review-readiness, and (when not ready) what
    is outstanding.

    Composed from `WorkLedger` reads, never a new SQL predicate (research.md).
    `not_ready_reason` is a subset of `{"blocked", "no_children"}` plus one
    entry per outstanding child id, empty whenever `review_ready`.
    `blocking_ids` names the still-blocking dependencies (US1.4), and
    `is_blocked` is derived from it so the two can never disagree.
    """
    item, guard_reason = _resolve_milestone(ledger, work_item_id)
    if item is None:
        return ReviewResult(ok=False, reason=guard_reason, view=None)

    review_ready = ledger.is_review_ready(work_item_id)
    blocking_ids = ledger.list_blocking(work_item_id)
    is_blocked = bool(blocking_ids)
    children = [
        wi for wi in ledger.list_work_items() if wi.parent_id == work_item_id
    ]

    not_ready_reason: list[str] = []
    if not review_ready:
        if is_blocked:
            not_ready_reason.append("blocked")
        if not children:
            not_ready_reason.append("no_children")
        for child in children:
            qualifies = child.status == "superseded" or (
                child.status == "done"
                and ledger.has_qualifying_evidence(child.id)
            )
            if not qualifies:
                not_ready_reason.append(child.id)

    child_views = [
        ChildTaskView(
            id=child.id,
            title=child.title,
            status=child.status,
            has_qualifying_evidence=ledger.has_qualifying_evidence(child.id),
            evidence=ledger.list_evidence(child.id),
            is_blocked=ledger.is_blocked(child.id),
        )
        for child in children
    ]

    view = MilestoneReviewView(
        id=item.id,
        title=item.title,
        status=item.status,
        review_ready=review_ready,
        not_ready_reason=not_ready_reason,
        is_blocked=is_blocked,
        blocking_ids=blocking_ids,
        claim=ledger.get_claim(work_item_id),
        children=child_views,
    )
    return ReviewResult(ok=True, reason=None, view=view)


@dataclasses.dataclass(frozen=True)
class MilestoneListEntry:
    """One milestone, as reported by `list_milestones()`."""

    id: str
    title: str | None
    status: str
    review_ready: bool


def list_milestones(ledger: WorkLedger) -> list[MilestoneListEntry]:
    """Every milestone work item with its status and review-readiness, ordered
    by id.

    Calls `is_review_ready()` per row rather than a batch query (research.md).
    """
    return [
        MilestoneListEntry(
            id=wi.id,
            title=wi.title,
            status=wi.status,
            review_ready=ledger.is_review_ready(wi.id),
        )
        for wi in ledger.list_work_items()
        if wi.type == "milestone"
    ]


def enter_review(ledger: WorkLedger, work_item_id: str) -> TransitionResult:
    """Move a milestone from `open` to `review`.

    Delegates to `WorkLedger.mark_in_review()`, keeping its atomicity: of
    concurrent attempts on one milestone, at most one succeeds (contract, "Enter
    review"). Adds only the type guard, never a second arbitration mechanism.
    """
    item, guard_reason = _resolve_milestone(ledger, work_item_id)
    if item is None:
        return TransitionResult(ok=False, reason=guard_reason)
    if ledger.mark_in_review(work_item_id):
        return TransitionResult(ok=True)
    return TransitionResult(ok=False, reason="not_ready_or_not_open")


def claim_milestone(
    ledger: WorkLedger,
    work_item_id: str,
    owner: str,
    worktree_path: str | None = None,
    branch: str | None = None,
) -> ClaimResult:
    """Claim a milestone on behalf of a human reviewer.

    Delegates to `WorkLedger.claim()`, keeping its atomicity: of concurrent
    attempts on a never-before-claimed milestone, exactly one succeeds.
    """
    item, guard_reason = _resolve_milestone(ledger, work_item_id)
    if item is None:
        return ClaimResult(ok=False, reason=guard_reason)
    if ledger.claim(work_item_id, owner, worktree_path=worktree_path, branch=branch):
        return ClaimResult(ok=True)
    return ClaimResult(ok=False, reason="already_claimed")


def release_milestone(
    ledger: WorkLedger, work_item_id: str, owner: str
) -> ReleaseResult:
    """Release a claim held by `owner` on a milestone.

    Delegates to `WorkLedger.release_claim()`: releasing a claim not held by
    `owner`, or an unclaimed milestone, is a no-op, never an error ("safe
    release").
    """
    item, guard_reason = _resolve_milestone(ledger, work_item_id)
    if item is None:
        return ReleaseResult(ok=False, reason=guard_reason)
    ledger.release_claim(work_item_id, owner)
    return ReleaseResult(ok=True)


def _decide(
    ledger: WorkLedger,
    work_item_id: str,
    transition: str,
    evidence_locator: str | None,
    note: str | None,
) -> DecisionResult:
    # Rationale evidence is recorded only after the transition (research.md).
    item, guard_reason = _resolve_milestone(ledger, work_item_id)
    if item is None:
        return DecisionResult(ok=False, reason=guard_reason, rationale_error=None)

    transitioned = (
        ledger.accept_milestone(work_item_id)
        if transition == "accept"
        else ledger.decline_review(work_item_id)
    )
    if not transitioned:
        return DecisionResult(ok=False, reason="not_in_review", rationale_error=None)

    rationale_error = None
    if evidence_locator is not None:
        try:
            ledger.add_evidence(
                work_item_id, kind="other", value=evidence_locator, note=note
            )
        except Exception as exc:  # noqa: BLE001 - reported, never propagated (FR-010a)
            rationale_error = str(exc)

    return DecisionResult(ok=True, reason=None, rationale_error=rationale_error)


def accept(
    ledger: WorkLedger,
    work_item_id: str,
    evidence_locator: str | None = None,
    note: str | None = None,
) -> DecisionResult:
    """Accept a milestone currently in `review`.

    Delegates to `WorkLedger.accept_milestone()`; on success with
    `evidence_locator`, separately records it as a `kind='other'` evidence
    pointer (data-model.md). Neither requires the caller to hold the milestone's
    claim (FR-011).
    """
    return _decide(ledger, work_item_id, "accept", evidence_locator, note)


def decline(
    ledger: WorkLedger,
    work_item_id: str,
    evidence_locator: str | None = None,
    note: str | None = None,
) -> DecisionResult:
    """Decline a milestone currently in `review`, back to `open`.

    Delegates to `WorkLedger.decline_review()`; touches no child task's status,
    evidence, or identity, only this milestone's row and optional rationale
    evidence pointer. Same semantics as `accept()`.
    """
    return _decide(ledger, work_item_id, "decline", evidence_locator, note)
