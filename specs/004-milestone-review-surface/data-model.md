# Data Model: Milestone Review Surface

This feature adds no new column, no new table, and no schema version bump — `work_items`, `work_item_blocked_by`, `work_item_claims`, `work_item_evidence` are all unchanged from schema version 3 (`specs/003-symphony-task-integration/data-model.md`). It adds two new read-only `WorkLedger` methods and one new module (`src/bindle/milestone_review.py`) composing them, plus five thin write wrappers, into human-facing result shapes.

## New `WorkLedger` methods (`src/bindle/work_ledger.py`)

Both are generic, review-agnostic additions — no schema/version change. Both follow the module's existing "connection-per-call, no ORM" convention.

### `list_evidence(work_item_id: str) -> list[EvidencePointer]`

```sql
SELECT kind, value, recorded_at, note
FROM work_item_evidence
WHERE work_item_id = ?
ORDER BY evidence_id
```

Returns every recorded pointer for `work_item_id`, oldest first (`evidence_id`'s own insertion order, matching the table's append-only, never-reordered semantics — `specs/001-durable-work-ledger/data-model.md`, "Evidence Pointer"). Returns an empty list, never `None`, when no pointer exists. Generalizes `has_qualifying_evidence()`'s existing `EXISTS` check into a full-row read; does not replace or change that method.

### `get_claim(work_item_id: str) -> ClaimInfo | None`

```sql
SELECT owner, claimed_at, worktree_path, branch
FROM work_item_claims
WHERE work_item_id = ?
```

Returns the single claim row for `work_item_id`, or `None` if unclaimed (`work_item_claims.PRIMARY KEY (work_item_id)` guarantees at most one row). Generalizes `is_claimed()`'s existing `EXISTS` check into a full-row read; does not replace or change that method.

## New dataclasses (`src/bindle/work_ledger.py`)

Both `@dataclasses.dataclass(frozen=True)`, following the existing `WorkItem`/`ReconciliationFinding`/`ProjectedWorkItem`/`ExternalProjectionRow` precedent.

```python
@dataclasses.dataclass(frozen=True)
class EvidencePointer:
    kind: str            # 'branch' | 'commit' | 'pull_request' | 'other'
    value: str
    recorded_at: str      # ISO-8601
    note: str | None

@dataclasses.dataclass(frozen=True)
class ClaimInfo:
    owner: str
    claimed_at: str        # ISO-8601
    worktree_path: str | None
    branch: str | None
```

## Milestone Review View (`src/bindle/milestone_review.py`)

Not a stored entity — computed fresh on every call from existing/new `WorkLedger` reads only (`get_work_item`, `list_work_items`, `is_review_ready`, `is_blocked`, `list_evidence`, `get_claim`). No caching, no persistence, mirroring `is_review_ready()`'s own "derived, never stored" precedent.

```python
@dataclasses.dataclass(frozen=True)
class ChildTaskView:
    id: str
    title: str | None
    status: str                      # 'open' | 'done' | 'superseded'
    has_qualifying_evidence: bool
    evidence: list[EvidencePointer]
    is_blocked: bool

@dataclasses.dataclass(frozen=True)
class MilestoneReviewView:
    id: str
    title: str | None
    status: str                      # 'open' | 'review' | 'accepted' | 'superseded'
    review_ready: bool               # is_review_ready(), verbatim — never recomputed differently
    not_ready_reason: list[str]      # subset of {"blocked", "no_children"} plus one
                                      # entry per outstanding child id when children
                                      # exist but at least one fails the resolved-or-
                                      # evidenced bar; empty when review_ready is True
    is_blocked: bool
    claim: ClaimInfo | None
    children: list[ChildTaskView]

@dataclasses.dataclass(frozen=True)
class ReviewResult:
    ok: bool
    reason: str | None    # None when ok; else 'not_found' | 'not_a_milestone'
    view: MilestoneReviewView | None   # None when not ok

def review_milestone(ledger: WorkLedger, work_item_id: str) -> ReviewResult:
    """Same ok/reason shape as TransitionResult/ClaimResult/ReleaseResult/
    DecisionResult below, plus the populated view on success — deliberately
    consistent with every other result type in this module rather than a
    separate Result/Ok/Err convention."""
```

`not_ready_reason` is computed by `review_milestone()` itself from the same three conditions `_review_ready_sql` already ANDs together (`work_ledger.py`) — not a new SQL predicate (research.md, "Decision: readiness diagnostic is composed from existing reads"). When `review_ready` is `True`, `not_ready_reason` is always empty; the two are never independently wrong relative to each other because `review_ready` is `is_review_ready()`'s own value, read once and reported as-is.

## Milestone List View

```python
@dataclasses.dataclass(frozen=True)
class MilestoneListEntry:
    id: str
    title: str | None
    status: str
    review_ready: bool

def list_milestones(ledger: WorkLedger) -> list[MilestoneListEntry]:
    """list_work_items() filtered to type == 'milestone', with is_review_ready()
    called once per row. Ordered by id, matching list_work_items()'s own order."""
```

## Write wrappers (`src/bindle/milestone_review.py`)

Each mirrors `symphony_projection.py`'s existing `claim_task`/`release_task`/`complete_task` shape: a type check first (reject `not_found` / `not_a_milestone` before touching the underlying method), then a direct delegation to the existing, unmodified `WorkLedger` lifecycle method.

| Function | Delegates to | Result vocabulary |
|---|---|---|
| `enter_review(ledger, id) -> TransitionResult` | `mark_in_review()` | `ok` \| `not_found` \| `not_a_milestone` \| `not_ready_or_not_open` |
| `claim_milestone(ledger, id, owner, worktree_path=None, branch=None) -> ClaimResult` | `claim()` | `ok` \| `not_found` \| `not_a_milestone` \| `already_claimed` |
| `release_milestone(ledger, id, owner) -> ReleaseResult` | `release_claim()` | `ok` \| `not_found` \| `not_a_milestone` (release itself remains a no-op-safe delete, per 001) |
| `accept(ledger, id, evidence_locator=None, note=None) -> DecisionResult` | `accept_milestone()`, then `add_evidence(kind='other', ...)` iff the transition returned `True` and `evidence_locator` was given | `ok` \| `not_found` \| `not_a_milestone` \| `not_in_review` |
| `decline(ledger, id, evidence_locator=None, note=None) -> DecisionResult` | `decline_review()`, then `add_evidence(kind='other', ...)` iff the transition returned `True` and `evidence_locator` was given | `ok` \| `not_found` \| `not_a_milestone` \| `not_in_review` |

`DecisionResult`/`TransitionResult`/`ClaimResult`/`ReleaseResult` are small frozen dataclasses with an `ok: bool` and a `reason: str | None`, mirroring `symphony_projection.py`'s existing `ClaimResult`/`ReleaseResult`/`CompleteResult` shape exactly (`contracts/task-write-surface.md`'s own result vocabulary convention, applied here rather than reinvented).

## What is explicitly not a new entity

- No new `work_items` status value — `review`/`accepted`/`open`/`superseded` are 002's existing milestone vocabulary, unchanged.
- No "review decision" row or table — an accept/decline is a status transition (already-existing column) plus, optionally, an ordinary evidence pointer (already-existing table, already-existing `kind='other'` value) — see `research.md`, "Decision: rationale locator recorded via existing `add_evidence`".
- No "readiness" column anywhere — `MilestoneReviewView.review_ready` and `MilestoneListEntry.review_ready` are both computed fields on an in-memory, never-persisted response object, not database columns.
