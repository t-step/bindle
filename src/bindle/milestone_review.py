"""Milestone review surface (specs/004-milestone-review-surface).

Implements the accepted design in specs/004-milestone-review-surface/
(spec.md, plan.md, research.md, data-model.md,
contracts/milestone-review-surface.md) — read those first for the "why"
behind anything here. In short: this module is a human-facing,
CLI-reachable presentation and write-wrapper layer over the milestone
review lifecycle `src/bindle/work_ledger.py` already implements and tests
(`is_review_ready`, `mark_in_review`, `decline_review`, `accept_milestone`,
`has_qualifying_evidence`) — it adds no new lifecycle behavior, no new
persisted state, and no new arbitration mechanism there.

Mirrors `symphony_projection.py`'s existing `claim_task`/`release_task`/
`complete_task` shape — a type check first, then a direct delegation to an
existing, unmodified `WorkLedger` method — but for milestones rather than
tasks, and deliberately named/framed apart from that Symphony-facing
module (`plan.md`'s "Structure Decision"): this module carries every
review-specific concern (`review_milestone()`'s composed view, the CLI
verbs), so `work_ledger.py` itself never becomes a reviewer-specific
adapter.
"""

from __future__ import annotations

import dataclasses

from .work_ledger import ClaimInfo, EvidencePointer, WorkItem, WorkLedger


def _resolve_milestone(
    ledger: WorkLedger, work_item_id: str
) -> tuple[WorkItem | None, str | None]:
    """Shared type-guard every function in this module calls first.

    Returns `(item, None)` when `work_item_id` resolves to a
    `type='milestone'` row; `(None, 'not_found')` when it does not resolve
    to any work item at all; `(None, 'not_a_milestone')` when it resolves
    to a `type='task'` row. The single, shared implementation — every
    wrapper function below calls this before doing anything else, so the
    type-guard behavior can never drift between commands (spec.md FR-009,
    User Story 5).
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

    `ok=True` iff the milestone transitioned to `review`. `ok=False`
    carries `reason`: `"not_found"`, `"not_a_milestone"`, or
    `"not_ready_or_not_open"` (the underlying `WorkLedger.mark_in_review()`'s
    own guarded-transition refusal).
    """

    ok: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class ClaimResult:
    """Result of `claim_milestone()`.

    `ok=True` iff the claim was acquired. `ok=False` carries `reason`:
    `"not_found"`, `"not_a_milestone"`, or `"already_claimed"` (the
    underlying `WorkLedger.claim()`'s own ordinary, expected "someone else
    already holds this claim" outcome).
    """

    ok: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class ReleaseResult:
    """Result of `release_milestone()`.

    `ok=True` iff the release was performed (which, per
    `WorkLedger.release_claim()`'s own "safe release" guarantee, is also
    true when the claim was already absent or held by a different
    owner — a no-op, never an error). `ok=False` carries `reason`:
    `"not_found"` or `"not_a_milestone"`.
    """

    ok: bool
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class DecisionResult:
    """Result of `accept()`/`decline()`.

    `ok` reflects the status transition's own outcome only — `True` iff
    the milestone transitioned (`accepted` or back to `open`). `reason` is
    `None` when `ok`; else `"not_found"` | `"not_a_milestone"` |
    `"not_in_review"`.

    `rationale_error` is `None` unless the transition succeeded, a
    locator was supplied, and the *separate* `add_evidence()` call then
    raised — in that case, `str(exception)`. Always `None` when `ok` is
    `False` (a rejected transition never attempts to record evidence at
    all, per spec.md FR-010). `ok=True` with `rationale_error` set means
    the decision is committed exactly as requested; the optional
    rationale-locator evidence pointer was not recorded — the transition
    is never retried or rolled back on account of this (spec.md FR-010a).
    """

    ok: bool
    reason: str | None
    rationale_error: str | None


# -- User Story 1/2: read-only review view -----------------------------


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
    """A read-only, computed-on-request report over a single milestone.

    Not a stored entity — composed fresh on every `review_milestone()`
    call from existing/new `WorkLedger` reads only. `review_ready` is
    `is_review_ready()`'s own value, read once and reported as-is — never
    recomputed independently (spec.md FR-002).
    """

    id: str
    title: str | None
    status: str
    review_ready: bool
    not_ready_reason: list[str]
    is_blocked: bool
    claim: ClaimInfo | None
    children: list[ChildTaskView]


@dataclasses.dataclass(frozen=True)
class ReviewResult:
    """Result of `review_milestone()`.

    Same `ok`/`reason` shape as `TransitionResult`/`ClaimResult`/
    `ReleaseResult`/`DecisionResult` above, plus the populated `view` on
    success (`None` when not `ok`).
    """

    ok: bool
    reason: str | None
    view: MilestoneReviewView | None


def review_milestone(ledger: WorkLedger, work_item_id: str) -> ReviewResult:
    """Report a milestone's status, review-readiness, and (when not
    ready) exactly what is outstanding — composed entirely from existing/
    new `WorkLedger` reads (`research.md`'s "Decision: readiness
    diagnostic is composed from existing reads"), never a new SQL
    predicate. `not_ready_reason` is a subset of `{"blocked",
    "no_children"}` plus one entry per outstanding child id — empty
    whenever `review_ready` is `True` (data-model.md's
    `MilestoneReviewView`).
    """
    item, guard_reason = _resolve_milestone(ledger, work_item_id)
    if item is None:
        return ReviewResult(ok=False, reason=guard_reason, view=None)

    review_ready = ledger.is_review_ready(work_item_id)
    is_blocked = ledger.is_blocked(work_item_id)
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
    """Enumerate every milestone work item with its status and
    review-readiness (`research.md`'s "Decision: `bindle milestone list`
    reuses `review_milestone()`'s readiness computation per row" — an
    individual `is_review_ready()` call per row, not a batch query).
    Ordered by id, matching `list_work_items()`'s own order.
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


# -- User Story 3: enter review, claim, release -------------------------


def enter_review(ledger: WorkLedger, work_item_id: str) -> TransitionResult:
    """Move a milestone from `open` to `review`.

    Delegates directly to `WorkLedger.mark_in_review()`, preserving its
    exact atomicity guarantee — of any number of concurrent attempts
    against one milestone, at most one succeeds (contracts/milestone-
    review-surface.md's "Enter review"). Adds only the type guard above
    it, never a second arbitration mechanism.
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
    """Claim a milestone, on behalf of a human reviewer.

    Delegates directly to `WorkLedger.claim()`, preserving its exact
    atomicity guarantee: of any number of concurrent claim attempts
    against one never-before-claimed milestone, exactly one succeeds.
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

    Delegates directly to `WorkLedger.release_claim()` — releasing a
    claim not held by `owner`, or releasing an already-unclaimed
    milestone, is a no-op, never an error, matching the underlying
    method's own "safe release" guarantee.
    """
    item, guard_reason = _resolve_milestone(ledger, work_item_id)
    if item is None:
        return ReleaseResult(ok=False, reason=guard_reason)
    ledger.release_claim(work_item_id, owner)
    return ReleaseResult(ok=True)


# -- User Story 4: accept / decline --------------------------------------


def _decide(
    ledger: WorkLedger,
    work_item_id: str,
    transition: str,
    evidence_locator: str | None,
    note: str | None,
) -> DecisionResult:
    # Shared by accept()/decline() below — the only difference between
    # the two is which underlying WorkLedger transition method is called
    # (research.md's "Decision: rationale locator recorded via existing
    # add_evidence(kind='other', ...), sequenced after the transition").
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

    Delegates directly to `WorkLedger.accept_milestone()`; if it succeeds
    and `evidence_locator` is given, separately records it as a
    `kind='other'` evidence pointer (`data-model.md`'s rationale locator
    mechanism). Neither requires the caller to currently hold the
    milestone's claim (spec.md FR-011).
    """
    return _decide(ledger, work_item_id, "accept", evidence_locator, note)


def decline(
    ledger: WorkLedger,
    work_item_id: str,
    evidence_locator: str | None = None,
    note: str | None = None,
) -> DecisionResult:
    """Decline a milestone currently in `review`, back to `open`.

    Delegates directly to `WorkLedger.decline_review()`; touches no
    child task's status, evidence, or identity — only this milestone's
    own row and, optionally, its own rationale-locator evidence pointer.
    Same success/rationale semantics as `accept()`.
    """
    return _decide(ledger, work_item_id, "decline", evidence_locator, note)
