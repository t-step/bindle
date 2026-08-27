# Quickstart: Validating Symphony Task Integration

Like `specs/002-milestone-task-work-items/quickstart.md`, this feature extends an already-implemented ledger — these scenarios are runnable against the real API once this feature's tasks land, and double as the shape of `tests/test_speckit_loader.py`/`tests/test_symphony_projection.py`/`tests/test_work_ledger.py`'s new test cases. Each scenario traces to a User Story in `spec.md`.

## Prerequisites

- A temporary directory acting as a repository root, containing a real `specs/003-symphony-task-integration/tasks.md` fixture (or any small feature directory with a few task lines and a `Depends on:` clause).
- `WorkLedger(repo_root)` constructed against it.

## Scenario 1 — Load a feature directory, then reload it idempotently (User Story 1)

```python
from bindle.speckit_loader import load_feature

result = load_feature(ledger, feature_dir="specs/999-example-feature")
# result.loaded == ["speckit:999-example-feature:T001", "speckit:999-example-feature:T002", ...]
# result.skipped == []  (every line in the fixture parses)

snapshot = {id_: ledger.get_work_item(id_) for id_ in result.loaded}

ledger.mark_done(result.loaded[0])
ledger.claim(result.loaded[1], owner="agent-A")

result2 = load_feature(ledger, feature_dir="specs/999-example-feature")
# result2.loaded == [] (nothing NEW was created)
assert ledger.get_work_item(result.loaded[0]).status == "done"          # untouched by reload
assert ledger.is_claimed(result.loaded[1])                              # untouched by reload
for id_ in result.loaded[2:]:
    assert ledger.get_work_item(id_) == snapshot[id_]                   # completely unchanged
```

**Expected**: the first load creates one work item per task line; the second load creates nothing new and leaves every previously-loaded item's status/claim/evidence completely unchanged. ✅ traces to Acceptance Scenarios 1.1, 1.3, 1.4 and SC-002/SC-003.

```python
load_feature(ledger, feature_dir="specs/001-durable-work-ledger")  # a feature that also has a "T001"
# No collision: distinct id from specs/999-example-feature's own T001.
```

✅ traces to Acceptance Scenario 1.2 and SC-004.

## Scenario 2 — Cross-line dependency resolves regardless of order (User Story 1)

```python
# fixture tasks.md declares T002 "Depends on: T001." with T001's own line appearing AFTER T002's in the file
result = load_feature(ledger, feature_dir="specs/999-out-of-order-deps")
t1_id, t2_id = result.loaded  # ids for T001, T002 respectively, however the file ordered the lines
assert ledger.is_blocked(t2_id) is True
ledger.mark_done(t1_id)
assert ledger.is_blocked(t2_id) is False
```

**Expected**: the dependency resolves correctly independent of line order within the file. ✅ traces to Acceptance Scenario 1.5 and FR-009.

## Scenario 3 — Publish the projection and confirm task-only, correct dispatchability (User Story 2)

```python
from bindle.symphony_projection import publish
import sqlite3

ledger.create_work_item("M-1", "A milestone", "adhoc", "note", type="milestone")
open_task = "speckit:999-example-feature:T003"   # open, unclaimed, unblocked
export_path = publish(ledger)

conn = sqlite3.connect(f"file:{export_path}?mode=ro", uri=True)
rows = conn.execute("SELECT id, identifier, status, dispatchable FROM task_projection").fetchall()
assert all(r[0] != "M-1" for r in rows)                       # no milestone row, ever
assert (open_task, "speckit-999-example-feature-T003", "open", 1) in rows
assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
```

**Expected**: `task_projection` contains only task rows; the milestone never appears; `dispatchable` matches the ledger's own "available to start" computation without the reader evaluating blocking/claims itself; the version is discoverable from the file alone. ✅ traces to Acceptance Scenarios 2.1–2.4, 2.6 and SC-005/SC-007.

```python
export_path_2 = publish(ledger)  # no ledger changes in between
# Reading task_projection from export_path and export_path_2 produces an equal result.
```

✅ traces to Acceptance Scenario 2.5 and SC-006.

## Scenario 4 — Claim, release, and complete through the write surface (User Story 3)

```python
from bindle.symphony_projection import claim_task, release_task, complete_task

r1 = claim_task(ledger, open_task, owner="symphony-worker-1")
assert r1.ok
r2 = claim_task(ledger, open_task, owner="symphony-worker-2")
assert not r2.ok and r2.reason == "already_claimed"          # immediate, unambiguous

release_task(ledger, open_task, owner="symphony-worker-1")
claim_task(ledger, open_task, owner="symphony-worker-1")
r3 = complete_task(ledger, open_task)
assert r3.ok and ledger.get_work_item(open_task).status == "done"

r4 = claim_task(ledger, "M-1", owner="symphony-worker-1")
assert not r4.ok and r4.reason == "not_a_task"                # milestone rejected, not silently claimed
```

**Expected**: claim arbitration matches the ledger's own atomic guarantee; release is owner-scoped and safe; completion is guarded; a milestone id is categorically rejected by all three operations. ✅ traces to Acceptance Scenarios 3.1–3.5 and SC-008/SC-009.

## Scenario 5 — CLI equivalents

```sh
bindle work load-speckit specs/999-example-feature
bindle work publish
bindle work claim speckit:999-example-feature:T003 --owner symphony-worker-1
bindle work done speckit:999-example-feature:T003
bindle work release speckit:999-example-feature:T003 --owner symphony-worker-1
```

**Expected**: each command's exit code and stderr message follow `bindle`'s existing convention (0 on success, 1 with a `bindle work <verb>: ...` stderr message on any rejection) — confirms the CLI is a faithful, thin wrapper over the library functions exercised in Scenarios 1–4.

## Full run

`bash scripts/check.sh` passes with this feature's tests included, alongside every existing 001/002 test, unmodified.
