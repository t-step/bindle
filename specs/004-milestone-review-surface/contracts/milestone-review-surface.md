# Contract: Milestone Review Surface

The human-facing counterpart to `specs/003-symphony-task-integration/contracts/task-write-surface.md`. Where that contract is the smallest write surface an external coordinator (or a human operating on its behalf) may use to act on a *task*, this one is the smallest surface a human reviewer may use to inspect and act on a *milestone*. Every mutating operation here is a thin, type-checked wrapper over `src/bindle/work_ledger.py`'s own existing, already-atomic primitives — never a new arbitration mechanism, and never raw SQL. The two read operations are new, additive queries over existing tables (`data-model.md`).

## Operations

### Review (read-only)

Library: `review_milestone(ledger, id) -> ReviewResult` (`src/bindle/milestone_review.py`)
CLI: `bindle milestone review <id>`

Reports the milestone's status, review-readiness (`is_review_ready()`, verbatim), the specific unmet condition(s) when not ready, and every child task's status, qualifying-evidence fact, full evidence-pointer list, and blocked state, plus the milestone's own claim if any (`data-model.md`'s `MilestoneReviewView`).

Rejects with a distinct result if `id` does not resolve to any work item (`not_found`), or resolves to one with `type = 'task'` (`not_a_milestone`) — never a partial or best-effort report.

### List (read-only)

Library: `list_milestones(ledger) -> list[MilestoneListEntry]`
CLI: `bindle milestone list [--status open|review|accepted|superseded] [--ready-only]`

Enumerates every milestone work item with its status and review-readiness. `--status` and `--ready-only` filter client-side over the same full result — no new query variant per filter combination.

### Enter review

Library: `enter_review(ledger, id) -> TransitionResult`
CLI: `bindle milestone enter-review <id>`

Delegates directly to `WorkLedger.mark_in_review()`, preserving its exact atomicity guarantee (`specs/002-milestone-task-work-items/data-model.md`'s "Milestone lifecycle transitions" — the review-readiness condition is embedded in the same guarded `UPDATE`, never checked-then-acted separately). Of any number of concurrent `enter-review` attempts against one milestone, at most one succeeds; every other resolves to `not_ready_or_not_open` with no ambiguity.

Same milestone/not-found guard as Review.

### Claim / Release

Library: `claim_milestone(ledger, id, owner, worktree_path=None, branch=None) -> ClaimResult` / `release_milestone(ledger, id, owner) -> ReleaseResult`
CLI: `bindle milestone claim <id> --owner <owner> [--worktree <path>] [--branch <name>]` / `bindle milestone release <id> --owner <owner>`

Delegate directly to `WorkLedger.claim()`/`release_claim()`. Preserve those methods' exact guarantees (`specs/001-durable-work-ledger/contracts/work-item-record.md`'s claim guarantees, extended to milestones by `specs/002`): exactly one concurrent claim attempt succeeds; releasing a claim not held by `owner`, or an already-unclaimed milestone, is a no-op, never an error.

Same milestone/not-found guard as Review.

### Accept / Decline

Library: `accept(ledger, id, evidence_locator=None, note=None) -> DecisionResult` / `decline(ledger, id, evidence_locator=None, note=None) -> DecisionResult`
CLI: `bindle milestone accept <id> [--evidence <locator>] [--note <text>]` / `bindle milestone decline <id> [--evidence <locator>] [--note <text>]`

Delegate directly to `WorkLedger.accept_milestone()`/`decline_review()`. Rejects the transition (`not_in_review`) when the milestone is not currently `review` — mirrors those methods' own guarded-transition semantics; never silently reapplies or double-decides.

`--evidence <locator>` and `--note <text>` mirror `add_evidence()`'s own `value`/`note` parameters exactly (`data-model.md`'s `EvidencePointer`): `--evidence` supplies the pointer's required `value` (where the rationale actually lives); `--note` supplies its optional, secondary annotation and is only meaningful alongside `--evidence` (a bare `--note` with no `--evidence` is a usage error, caught by argument parsing — `note` alone is not a locator and cannot become one). When `--evidence` is supplied and the transition succeeds, exactly one evidence pointer is recorded against the milestone (`kind='other'`, `value=<locator>`, `note=<text or None>`), via the same `add_evidence()` every other 001/002 evidence recording already uses. When `--evidence` is omitted, no evidence pointer is recorded at all — recording a rationale locator is optional (spec.md Acceptance Scenario US4.2: "optionally supplying a rationale locator"). When the transition is rejected, **no** evidence pointer is recorded, regardless of what was supplied (FR-010; `research.md`'s "Decision: rationale locator recorded via existing `add_evidence`").

Same milestone/not-found guard as Review. Neither requires the caller to currently hold the milestone's claim (spec.md FR-011).

## Guarantees

- **No new arbitration mechanism.** Every guarantee a caller relies on (transition atomicity, safe release, guarded accept/decline) is provided entirely by `work_ledger.py`'s own existing, already-verified methods — this contract adds a type check, a stable calling convention, and (for accept/decline) one strictly-sequenced-after-success evidence call.
- **Milestones are categorically required; tasks are categorically rejected.** An attempt to invoke any operation in this contract against a work item of `type = 'task'` is refused with a distinct result, never silently treated as a milestone — the exact mirror image of `task-write-surface.md`'s "Milestones are categorically rejected."
- **This surface cannot mark a task done, claim a task, or release a task's claim.** It has no operation that accepts a task id and produces any effect — `bindle work claim/release/done` remain the only write path onto a task, unchanged by this feature.
- **No raw SQL, no database handle.** Every operation's public shape is a fixed function signature (or CLI subcommand) with a fixed, small result vocabulary — nothing here accepts or returns a connection, a cursor, or a query string.
- **CLI exit codes**: `0` on success; `1` on any rejection (not found, not a milestone, not ready, not in review, already claimed) — consistent with `bindle`'s existing exit-code convention (`_cmd_work_claim` et al.), with the specific reason always printed to stderr as `bindle milestone <verb>: ...`.
- **Claiming and deciding remain orthogonal.** Accept/decline never check or require a claim (spec.md FR-011) — this surface does not invent a "must be claimed to decide" precondition the underlying 002 lifecycle does not itself have.

## What this contract does not do

- It does not create a milestone work item, attach a task to one, or modify any milestone's or task's `title`/`description`/`parent_id` — creation and attribution remain reachable only through the existing internal `WorkLedger.create_work_item()` for a caller with library access, exactly as `task-write-surface.md` already states for task creation via `speckit_loader.py`'s narrower path.
- It does not mark a task done, claim a task, or release a task's claim — `bindle work claim/release/done` (`task-write-surface.md`) remain the sole write path for those, unaffected by this feature.
- It does not store, require, or validate the *content* of a review rationale — `--note`/`--evidence` produce an ordinary pointer (`kind='other'`) to wherever the actual rationale is durably recorded (`docs/DECISIONS.md` or another owning record, per `docs/DATA-OWNERSHIP.md`); the ledger's own copy is never treated as that rationale's authoritative form (spec.md FR-014's "Rationale Locator" key entity).
- It does not add authentication, authorization, or identity verification for `owner` — exactly like `task-write-surface.md`'s existing, unchanged trust model.
- It does not modify, read, or depend on `specs/003-symphony-task-integration`'s published projection in any way — Symphony's discovery path and this feature's discovery path (`bindle milestone list`) are entirely separate artifacts over the same underlying ledger.
- It does not detect or warn about stale evidence (a since-rebased branch, a deleted PR) — pointers are read back exactly as recorded, never revalidated against Git or GitHub state (spec.md Assumptions).
