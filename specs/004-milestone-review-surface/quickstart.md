# Quickstart: Validating the Milestone Review Surface

Like `specs/003-symphony-task-integration/quickstart.md`, this feature extends an already-implemented ledger — these scenarios are runnable against the real API once this feature's tasks land, and double as the shape of `tests/test_milestone_review.py`/`tests/test_work_ledger.py`/`tests/test_cli.py`'s new test cases. Each scenario traces to a User Story in `spec.md`.

## Prerequisites

- A temporary directory acting as a repository root, `WorkLedger(repo_root)` constructed against it.
- A milestone and a couple of tasks created via the existing, unmodified library surface (creating a milestone or attaching a task to one is out of this feature's scope — spec.md's Assumptions):

```python
m = ledger.create_work_item(type="milestone", title="Ship the review surface")
t1 = ledger.create_work_item(type="task", title="Add list_evidence/get_claim", parent_id=m)
t2 = ledger.create_work_item(type="task", title="Wire the CLI", parent_id=m)
```

## Walkthrough A — readiness, evidence, enter-review, claim, accept (User Stories 1–4)

```python
from bindle.milestone_review import review_milestone, list_milestones, enter_review, claim_milestone, accept

view = review_milestone(ledger, m).view
assert view.review_ready is False
assert "no_children" not in view.not_ready_reason  # it has children
assert t1 in [c.id for c in view.children if not c.has_qualifying_evidence]
```

**Expected**: `not ready`, both children `open` with no evidence — traces to Acceptance Scenario US1.1.

```bash
$ bindle milestone review <m>
milestone <m>: open, not ready (outstanding: <t1>, <t2>)
  <t1>  open       evidence: none        blocked: no
  <t2>  open       evidence: none        blocked: no
```

Complete the remaining work:

```python
ledger.add_evidence(t1, kind="commit", value="abc1234")
ledger.mark_done(t1)
ledger.add_evidence(t2, kind="pull_request", value="https://github.com/t-step/bindle/pull/99")
ledger.mark_done(t2)

view = review_milestone(ledger, m).view
assert view.review_ready is True
```

**Expected**: `ready` once both children are `done` and evidenced — traces to Acceptance Scenario US1.2 and User Story 2's evidence-listing scenarios.

```bash
$ bindle milestone review <m>
milestone <m>: open, ready
  <t1>  done  evidence: [commit abc1234]                                     blocked: no
  <t2>  done  evidence: [pull_request https://github.com/t-step/bindle/pull/99]  blocked: no

$ bindle milestone list --ready-only
<m>  open  ready

$ bindle milestone enter-review <m>
$ bindle milestone claim <m> --owner alice
$ bindle milestone review <m>
milestone <m>: review, ready, claimed by alice
  ...
$ bindle milestone accept <m> --evidence "https://github.com/t-step/bindle/pull/101#pullrequestreview-1" --note "matches the agreed scope"
$ bindle milestone review <m>
milestone <m>: accepted, ready
```

**Expected**: `enter-review` transitions `open → review`; `claim` records `alice` as the milestone's claim; `accept` transitions `review → accepted` and records one `kind='other'` evidence pointer on the milestone pointing at wherever the rationale was actually written (here, a PR review comment — a `docs/DECISIONS.md` anchor is an equally valid locator once that entry exists, but must never be invented ahead of the entry it would point to, per `AGENTS.md`'s decision-reference consistency check). No child's status/evidence changes at any point in this sequence. ✅ traces to Acceptance Scenarios US3.1, US3.3, US4.1, SC-001, SC-002.

## Walkthrough B — decline with a rationale locator, then corrective work (User Story 4)

Starting from a second, separately review-ready milestone `m2` with children `t3`, `t4` (both `done`, evidenced, exactly as above):

```bash
$ bindle milestone enter-review <m2>
$ bindle milestone decline <m2> --evidence "https://github.com/t-step/bindle/pull/101#pullrequestreview-2" --note "missing an edge case"
$ bindle milestone review <m2>
milestone <m2>: open, ready
  <t3>  done  evidence: [...]  blocked: no
  <t4>  done  evidence: [...]  blocked: no
```

**Expected**: `decline` transitions `review → open`; `t3`/`t4` are completely untouched (same ids, same status, same evidence — byte-identical before/after per SC-003); one evidence pointer is recorded on `m2` itself, not on either child.

```python
t5 = ledger.create_work_item(type="task", title="Fix the missed edge case", parent_id=m2)
view = review_milestone(ledger, m2).view
assert view.review_ready is False  # t5 is open, unevidenced
```

**Expected**: adding a corrective task under a declined milestone is immediately reflected by the next `review_milestone()` call — no action from this feature is required to "notice" the new child. ✅ traces to Acceptance Scenario US4.2, US4.5, SC-003.

## Walkthrough C — the two surfaces cannot perform each other's mutation (User Story 5)

```bash
$ bindle milestone accept <t1>
bindle milestone accept: <t1> is not a milestone
$ echo $?
1

$ bindle work done <m>
bindle work done: <m> is not a task
$ echo $?
1
```

**Expected**: both rejections are pre-existing or newly-added type guards, not silent no-ops or partial effects — the first line is this feature's own new guard (FR-009); the second is `specs/003`'s existing, unmodified guard (`task-write-surface.md`), demonstrated here only to confirm this feature did not weaken it. ✅ traces to Acceptance Scenarios US5.1, US5.2, SC-006, SC-007.
