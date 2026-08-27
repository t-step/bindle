# Contract: Coordinator Projection, revised for milestone/task types

This revises `specs/001-durable-work-ledger/contracts/coordinator-projection.md` for the presence of milestone work items. It does not change any field mapping already established there — it adds exactly one new rule.

## What changes

**Milestones are never inputs to the projection at all.** 001's existing field-mapping table (identifier, title, state, eligibility, optional dashboard fields) continues to apply verbatim, but only to rows where `type = 'task'`. A milestone work item — regardless of its `status` (`open`, `review`, `accepted`, `superseded`), regardless of whether it is claimed, and regardless of whether any of its child tasks are individually eligible — MUST NOT appear in a generated projection under any field name, mapped or unmapped.

## Why this is a projection-time filter, not a Symphony-adapter concern

Symphony's shipped `local` tracker adapter (per `docs/SYMPHONY.md` and 001's own contract doc) has no concept of "this row is a grouping, not dispatchable work" — it would happily treat any row handed to it as a candidate. The filtering responsibility therefore belongs entirely to Bindle's own projection step, exactly as 001's contract doc already established that *blocking* eligibility must be withheld by Bindle rather than relied upon from Symphony's adapter ("Symphony's shipped `local` tracker adapter hardcodes `dispatchable: true` and does not evaluate `blocked_by` itself"). This feature extends that same withholding principle to type: Bindle withholds non-task rows from the projection entirely, the same way it withholds blocked rows from `eligible: true`.

## What does not change

- The projection remains a generated, disposable, regenerable view (001 FR-014) — this revision adds a filter predicate to that same generation step, not a second projection artifact.
- No Symphony-specific field name (`dispatchable`, `identifier`, `state`, etc.) is adopted by `ProjectedWorkItem` itself in this feature — that translation remains a future adapter's responsibility, per 001's contract doc and this feature's own spec.md Assumptions.
- A task that is itself blocked by a milestone (e.g., "do not start until this milestone is accepted") is still projected — as an ordinary, currently-ineligible task — exactly as a task blocked by another task already is under 001's existing rules. Only the blocking *milestone* is withheld from appearing as a row; the blocked *task* still appears, marked ineligible.
