# Contract: External Task Write Surface

The smallest supported write surface by which an external caller (a coordinator, or a human operating on its behalf) may act on a task it discovered through `contracts/symphony-projection-v1.md`. Every operation here is a thin, type-checked wrapper over `src/bindle/work_ledger.py`'s own existing, already-atomic primitives — never a new arbitration mechanism, and never raw SQL.

## Operations

### Claim

Library: `claim_task(ledger, id, owner, worktree_path=None, branch=None) -> ClaimResult`
CLI: `bindle work claim <id> --owner <owner> [--worktree <path>] [--branch <name>]`

Delegates directly to `WorkLedger.claim()`. Preserves that method's exact atomicity guarantee (`specs/001-durable-work-ledger/contracts/work-item-record.md`'s claim guarantees): of any number of concurrent claim attempts against one never-before-claimed task, exactly one succeeds and every other receives an immediate, unambiguous "already claimed" result — never a timeout, never an ambiguous outcome (SC-008).

Additional check before delegating: if `id` does not resolve to any work item, or resolves to one with `type = 'milestone'`, the operation is rejected with a distinct result (`not_found` / `not_a_task`) rather than being passed through to `claim()`.

### Release

Library: `release_task(ledger, id, owner) -> ReleaseResult`
CLI: `bindle work release <id> --owner <owner>`

Delegates directly to `WorkLedger.release_claim()`. Releasing a claim not held by `owner`, or releasing an already-unclaimed task, is a no-op — never an error — exactly matching the underlying method's own "safe release" guarantee.

Same milestone/not-found guard as Claim.

### Complete

Library: `complete_task(ledger, id) -> CompleteResult`
CLI: `bindle work done <id>`

Delegates directly to `WorkLedger.mark_done()`. Rejects the transition (returns `False`/a failure result) when the task is not currently `open` — mirrors the guarded-transition semantics `mark_done` already provides; never silently reapplies or double-completes.

Same milestone/not-found guard as Claim and Release.

## Guarantees

- **No new arbitration mechanism.** Every guarantee an external caller relies on (claim atomicity, safe release, guarded completion) is provided entirely by `work_ledger.py`'s own existing, already-verified methods — this contract adds a type check and a stable calling convention, nothing more (FR-020–FR-023).
- **Milestones are categorically rejected.** An attempt to claim, release, or complete a work item of `type = 'milestone'` is refused with a distinct result, never silently treated as a task (FR-024, spec.md Acceptance Scenario US3.5).
- **No raw SQL, no database handle.** Every operation's public shape is a fixed function signature (or CLI subcommand) with a fixed, small result vocabulary — nothing here accepts or returns a connection, a cursor, or a query string.
- **CLI exit codes**: `0` on success; `1` on any rejection (already claimed, not found, not a task, not currently open) — consistent with `bindle`'s existing exit-code convention (`_cmd_repo_info`, `_cmd_skills_*`), with the specific reason always printed to stderr as `bindle work <verb>: ...`.

## What this contract does not do

- It does not add evidence recording, milestone review transitions, or any lifecycle transition beyond claim/release/complete — those remain reachable only through the existing internal `WorkLedger` API for a caller with library access, not through this external surface.
- It does not add authentication, authorization, or identity verification for `owner` — exactly like the underlying `claim()`/`release_claim()` methods, `owner` is a caller-supplied string with no verification, consistent with this ledger's existing, unchanged trust model (a single-machine, single-repository coordination tool, not a multi-tenant service).
- It does not provide a way to discover *which* tasks exist — that is `contracts/symphony-projection-v1.md`'s role; this contract only acts on an `id` the caller already has.
