# Quickstart: Validating Work-State Visibility

Like `specs/004-milestone-review-surface/quickstart.md`, this feature composes an already-implemented ledger — these scenarios are runnable once this feature's tasks land, and double as the shape of `tests/test_work_status.py`/`tests/test_view.py`/`tests/test_cli.py`'s new test cases. Each scenario traces to a User Story in `spec.md`.

## Prerequisites

- A temporary directory acting as a repository root, `WorkLedger(repo_root)` constructed against it.
- A small mixed-state ledger, built entirely from the existing, unmodified library surface (this feature creates nothing):

```python
m = ledger.create_work_item(type="milestone", title="Ship visibility")
a = ledger.create_work_item(type="task", title="A", parent_id=m)
b = ledger.create_work_item(type="task", title="B", parent_id=m)
c = ledger.create_work_item(type="task", title="C (needs A and B)", parent_id=m)
d = ledger.create_work_item(type="task", title="D (needs A only)", parent_id=m)
ledger.add_blocked_by(c, a)
ledger.add_blocked_by(c, b)
ledger.add_blocked_by(d, a)
ledger.claim(d, owner="alice")  # D: claimed AND blocked on A
```

This is the exact dependency graph spec.md's own Independent Test for User Story 4 names (C blocked on {A, B}; D blocked on {A}), plus the claimed-but-blocked case Acceptance Scenario US4.5 requires.

## Walkthrough A — one snapshot, two renderings (User Stories 1–2)

```python
from bindle.work_status import build_snapshot

snapshot = build_snapshot(ledger)
by_id = {t.id: t for t in snapshot.tasks}
assert by_id[a].dispatchable is True
assert by_id[b].dispatchable is True
assert by_id[c].dispatchable is False and by_id[c].blocking_ids == sorted([a, b])
assert by_id[d].dispatchable is False and by_id[d].blocking_ids == [a]
assert by_id[d].claim is not None and by_id[d].claim.owner == "alice"
```

**Expected**: A and B report dispatchable; C names both outstanding blockers; D is blocked *and* separately reported as claimed — the two facts coexist without being merged (Terminology). ✅ traces to Acceptance Scenarios US1.1–US1.3.

```bash
$ bindle work status
tasks:
  A  open       dispatchable
  B  open       dispatchable
  C  open       blocked on: A, B
  D  open       blocked on: A  claimed by alice at <claimed_at>
milestones:
  M  open       not ready (outstanding: A, B, C, D)

$ bindle work status --json
{
  "tasks": [
    {"id": "A", "title": "A", "status": "open", "claim": null, "dispatchable": true, "blocking_ids": []},
    {"id": "B", "title": "B", "status": "open", "claim": null, "dispatchable": true, "blocking_ids": []},
    {"id": "C", "title": "C (needs A and B)", "status": "open", "claim": null, "dispatchable": false, "blocking_ids": ["A", "B"]},
    {"id": "D", "title": "D (needs A only)", "status": "open", "claim": {"owner": "alice", "claimed_at": "...", "worktree_path": null, "branch": null}, "dispatchable": false, "blocking_ids": ["A"]}
  ],
  "milestones": [
    {"id": "M", "title": "Ship visibility", "status": "open", "claim": null, "review_ready": false, "not_ready_reason": ["A", "B", "C", "D"], "blocking_ids": []}
  ]
}

$ bindle work status --json | python3 -m json.tool > /tmp/first.json
$ bindle work status --json | python3 -m json.tool > /tmp/second.json
$ diff /tmp/first.json /tmp/second.json
$ echo $?
0
```

**Expected**: the plain-text and `--json` forms report identical semantic facts for the same state (SC-003); two `--json` invocations against the unchanged ledger are byte-identical (SC-004). ✅ traces to Acceptance Scenarios US2.1–US2.2.

## Walkthrough B — forecast: convergence, unblocked-next vs. dispatchable-next (User Story 4)

```python
from bindle.work_status import build_forecast

frontier = build_forecast(snapshot)
assert sorted(frontier.dispatchable_now) == sorted([a, b])
assert frontier.convergence_points == [c]  # only C has more than one outstanding blocker

by_blocker = {e.resolved_blocker_id: e for e in frontier.frontier}
assert by_blocker[a].unblocked_next == sorted([d])   # C still needs B — not included
assert by_blocker[a].dispatchable_next == []          # D is claimed, so NOT dispatchable-next
assert by_blocker[b].unblocked_next == []             # C still needs A — not included
```

**Expected**: resolving A alone unblocks D (loses its only blocker) but not C (still needs B) — matching spec.md's own worked example exactly; D is reported `unblocked_next` but explicitly *not* `dispatchable_next`, because it remains claimed under the otherwise-unchanged counterfactual. ✅ traces to spec.md's User Story 4 Independent Test and Acceptance Scenario US4.5.

```bash
$ bindle work forecast
dispatchable now: A, B
blocked:
  C  blocked on: A, B  (convergence point)
  D  blocked on: A
if A resolves:
  unblocked-next: D
  dispatchable-next: (none — D remains claimed)
if B resolves:
  unblocked-next: (none)
milestone review frontier:
  M  not ready (outstanding: A, B, C, D)
```

**Expected**: no line in this output names a time, date, or ETA (SC-008); running it twice against the unchanged ledger changes nothing in the ledger itself (FR-015). ✅ traces to Acceptance Scenarios US4.1–US4.9.

## Walkthrough C — `--watch` refreshes, then leaves the ledger untouched on interrupt (User Story 3)

```bash
$ bindle work status --watch --interval 1 &
$ WATCH_PID=$!
$ sleep 0.5
$ ledger.claim(a, owner="bob")   # from a second process/terminal
$ sleep 1.5
# the next refresh's output now shows A as claimed, not dispatchable
$ kill -INT $WATCH_PID
$ echo $?
0
```

**Expected**: `bindle work status` with no flags never refreshes a second time on its own; `--watch` reflects an external claim by its next scheduled refresh; interrupting it exits promptly with no stray lock or lingering process, and the ledger's own state is exactly what the external claim left it as (this command never writes). ✅ traces to Acceptance Scenarios US3.1–US3.3, SC-005, SC-006.

```bash
$ bindle work status --json --watch --interval 1 > /tmp/watch.ndjson &
$ WATCH_PID=$!
$ sleep 2.5
$ kill -INT $WATCH_PID
$ wc -l /tmp/watch.ndjson
2   # (or 3 — depends on exact timing; at least one full refresh happened)
$ python3 -c "
import json
with open('/tmp/watch.ndjson') as f:
    for line in f:
        json.loads(line)   # every line parses independently — JSON Lines
print('all lines independently valid JSON')
"
all lines independently valid JSON
```

**Expected**: `--json --watch` emits [JSON Lines](https://jsonlines.org/) (NDJSON) — one complete, compact JSON document per refresh, newline-delimited — never a growing array, never a partial object, never a document split across lines (`contracts/work-status-json-v1.md`, "Watch-mode framing"). Interrupting mid-stream leaves only complete lines in the file; no trailing partial JSON fragment. ✅ traces to Acceptance Scenario US3.4, FR-010.

## Walkthrough D — `bindle view`: one long-lived server, many requests, manual reload, `--watch` opt-in, no Symphony section (User Story 5)

```bash
$ bindle view &
http://127.0.0.1:54231/
# process stays attached to this shell (backgrounded here with & only so
# the walkthrough can keep issuing commands); it does not daemonize or
# detach itself, and it does not open a browser automatically — only the
# URL above is printed. Open it in a browser, or curl it directly below.
```

**Expected**: the page renders exactly one snapshot of the same facts Walkthrough A/B show (tasks, milestones, dependency frontier) and does not refresh on its own; the rendered page contains **no Symphony-runtime section at all** — no row, no "unavailable" placeholder, nothing — because this feature defers Symphony enrichment (FR-020) entirely rather than stubbing it (`research.md`). ✅ traces to Acceptance Scenarios US5.1, US5.2.

```bash
$ curl -s http://127.0.0.1:54231/ | grep -c 'task-'
4   # the first request's render: A, B, C, D all present

$ ledger.claim(a, owner="carol")   # a mutation from a second process/terminal

$ curl -s http://127.0.0.1:54231/ | grep 'task-a'
task-a ... claimed by carol ...   # a SECOND, independent request against the
                                    # SAME still-running server — freshly
                                    # re-reads current state; the process was
                                    # never restarted between these two requests
```

**Expected**: this demonstrates the actual process/request contract directly — `bindle view` does not accept exactly one HTTP request and stop; its one `do_GET` handler runs once per request, for as long as the process lives, and each run is an independent one-shot render (`research.md`, "`bindle view` process/request semantics"). A manual browser reload is nothing more than another ordinary `GET /` against this same running server — this curl sequence is that same behavior made scriptable. ✅ traces to Acceptance Scenario US5.2 ("re-renders current state without the process restarting").

```bash
$ bindle view --watch --interval 2 &
http://127.0.0.1:54987/
# the served page includes <meta http-equiv="refresh" content="2">;
# leaving a browser tab open on it reloads automatically every ~2s — each
# automatic reload is, again, just another GET / against the same handler
```

**Expected**: automatic refresh only happens because `--watch` was given at *this* launch; a separate, later `bindle view` launched without `--watch` never inherits that behavior (FR-018 — no persisted watch state). ✅ traces to Acceptance Scenarios US5.3, US5.4.

```bash
$ curl -s http://127.0.0.1:54231/nope
# 404, plain text — an ordinary unmatched request; the server keeps running
$ kill -INT %1
$ echo $?
0
```

**Expected**: interrupting `bindle view` (with or without `--watch` running) exits promptly, closes the loopback socket, and leaves no lingering process — the same shutdown discipline as `bindle work status --watch` (`research.md`, "watch/serve shutdown behavior"). ✅ traces to Non-Goals' "no persistent background daemon."
