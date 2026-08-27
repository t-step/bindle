# Quickstart: Validating Milestone and Task Work Items

Unlike `specs/001-durable-work-ledger/quickstart.md` (written before any code existed), this feature extends an already-implemented ledger — these scenarios are runnable against the real `WorkLedger` API in `src/bindle/work_ledger.py` once this feature's tasks land, and double as the shape of `tests/test_work_ledger.py`'s new test cases. Each scenario traces to a User Story in `spec.md`.

## Prerequisites

- A temporary directory acting as a repository root (as 001's own tests already set up via a `tmp_path`/git-init fixture).
- `WorkLedger(repo_root)` constructed against it.

## Scenario 1 — Group tasks under a milestone (User Story 1)

```python
ledger = WorkLedger(repo_root)
ledger.create_work_item("M-1", "Ship the milestone/task model", "plan", "plans/active/...", type="milestone")
ledger.create_work_item("T-1", "Write data-model.md", "plan", "plans/active/...", type="task", parent_id="M-1")
ledger.create_work_item("T-2", "Implement schema v2", "plan", "plans/active/...", type="task", parent_id="M-1")
```

**Expected**: both `T-1` and `T-2` read back with `parent_id == "M-1"`; `ledger.get_work_item("M-1").parent_id is None`. A fresh `WorkLedger(repo_root)` handle (simulating a new session) reads back identical results. ✅ traces to Acceptance Scenarios 1.1–1.2.

```python
ledger.create_work_item("T-3", "Bad parent", "plan", "...", type="task", parent_id="T-1")  # T-1 is a task, not a milestone
# Expected: raises / returns failure, no row written for T-3.
```

✅ traces to Acceptance Scenario 1.3.

## Scenario 2 — A task reaches "done" without any review fact (User Story 2)

```python
ledger.mark_done("T-1")
ledger.has_qualifying_evidence("T-1")  # -> False, no evidence recorded
ledger.add_evidence("T-1", "commit", "abc123")
ledger.has_qualifying_evidence("T-1")  # -> True
```

**Expected**: `mark_done("T-1")` behaves exactly as it does for any 001 task (no evidence required to call it); `has_qualifying_evidence` is a pure read with no side effect on `status`, claims, or anything milestone-shaped. ✅ traces to Acceptance Scenarios 2.1–2.3.

## Scenario 3 — Review readiness and claiming the milestone (User Story 3)

```python
ledger.is_review_ready("M-1")  # -> False: T-2 is still open
ledger.mark_done("T-2")
ledger.add_evidence("T-2", "pull_request", "https://example/pr/1")
ledger.is_review_ready("M-1")  # -> True: both children done with qualifying evidence, M-1 unblocked
ledger.mark_in_review("M-1")   # open -> review; fails if is_review_ready() were False
ledger.claim("M-1", owner="reviewer-1")
```

**Expected**: `claim("M-1", ...)` behaves exactly like claiming a task (same table, same arbitration) — a second concurrent `claim("M-1", owner="reviewer-2")` fails with the same primary-key-violation semantics 001 already guarantees. ✅ traces to Acceptance Scenarios 3.1–3.4.

## Scenario 4 — Decline review, add corrective work, history untouched (User Story 4)

```python
snapshot_t1 = ledger.get_work_item("T-1")
snapshot_t2 = ledger.get_work_item("T-2")
ledger.release_claim("M-1", owner="reviewer-1")
ledger.decline_review("M-1")   # review -> open
ledger.create_work_item("T-4", "Fix the thing reviewer flagged", "plan", "...", type="task", parent_id="M-1")
assert ledger.get_work_item("T-1") == snapshot_t1
assert ledger.get_work_item("T-2") == snapshot_t2
ledger.is_review_ready("M-1")  # -> False again: T-4 is open
```

**Expected**: `T-1`/`T-2`'s records are byte-for-byte unchanged; the decline decision's *rationale* is recorded in `docs/DECISIONS.md` by whoever made the call, not in the ledger — the ledger only shows the coarse `review -> open` transition. ✅ traces to Acceptance Scenarios 4.1–4.3.

## Scenario 5 — Symphony never sees the milestone (User Story 5)

```python
ledger.mark_done("T-4")
ledger.add_evidence("T-4", "commit", "def456")
projection = ledger.generate_projection()
ids = {p.id for p in projection}
assert "M-1" not in ids
assert {"T-1", "T-2", "T-4"} <= ids
```

**Expected**: no projected row ever has `id == "M-1"`, in this state or any other constructed state (open/review/accepted/superseded, claimed/unclaimed) — verified by parametrizing this assertion over every milestone status in the actual test suite. A second call to `generate_projection()` with no intervening write produces an equal result. ✅ traces to Acceptance Scenarios 5.1–5.3.

## Out of scope for this quickstart

- Any Symphony process, adapter, or CLI invocation — none exist (unchanged from 001).
- The v1→v2 schema migration path itself — covered separately by its own test class exercising a real pre-existing version-1 database file, not by these scenarios (which assume a fresh v2 database).
