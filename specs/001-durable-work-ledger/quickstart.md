# Quickstart: Validating the Durable Work Ledger Model

No code exists yet — this is a validation guide for the *model*, to be exercised by hand-reasoning now, and re-used as the shape of real tests once the first implementation slice (see plan.md's recommended next step) exists. Each scenario below traces directly to an Acceptance Scenario in `spec.md`.

## Prerequisites

- A conceptual repository with a Git common directory and at least two linked worktrees (real or imagined) — no `bindle` code required to reason through this.
- data-model.md and the two files under `contracts/` open for reference.

## Scenario 1 — Decompose and recover (User Story 1)

1. Imagine three Work Items created from `specs/001-durable-work-ledger/spec.md` itself (dogfooding): `WI-1` ("write research.md"), `WI-2` ("write data-model.md"), `WI-3` ("write quickstart.md"), each with `source.kind = plan`, `source.locator` pointing at this feature's own plan.md.
2. Confirm: none of the three items' records need to reference each other, the creating session, or any worktree to be fully intelligible — each stands alone with `id`, `title`, `source`, `status = open`.
3. **Expected**: a fresh reader with no memory of steps 1–2 can list all three items and understand what each is for and why it exists, using only the stored fields. ✅ traces to Acceptance Scenario 1.2.
4. Confirm the negative: nothing about running `/speckit.tasks` against this feature's own `tasks.md` (if one existed) would, by itself, create any of `WI-1..3`. ✅ traces to Acceptance Scenario 1.3.

## Scenario 2 — Determine availability, including across archival (User Story 2)

1. Set `WI-2.blocked_by = [WI-1.id]` (data-model.md decomposition depends on research landing first, for illustration).
2. Compute Blocked for each item per data-model.md's "Dependency resolution": `WI-1` → not blocked (empty `blocked_by`); `WI-2` → blocked (`WI-1` resolves via the active item set to `open`, still blocking); `WI-3` → not blocked (empty `blocked_by`).
3. Compute Available to start: `WI-1` → available (open, unclaimed, unblocked); `WI-2` → **not** available; `WI-3` → available.
4. Set `WI-1.status = done`. Recompute: `WI-2` → `WI-1` now resolves to satisfied → `WI-2` is not blocked → available (if still unclaimed). ✅ traces to Acceptance Scenarios 2.1–2.3.
5. **New**: archive `WI-1` — remove its full record and create a Tombstone `{id: WI-1, status: done}`. Recompute `WI-2`'s blocked status again: resolving `WI-1` now falls through to the Tombstone (step 2 of "Dependency resolution"), still resolves to satisfied, so `WI-2` remains not blocked — archival did not change the answer. ✅ traces to SC-008.
6. **New**: imagine instead `WI-2.blocked_by` had named a typo'd id, `WI-0`, that never existed. Resolving it finds neither an active item nor a Tombstone → `dangling_blocker`, and `WI-2` is conservatively still blocked, distinguishable in the Reconciliation Report from `WI-1`'s tombstoned, satisfied case in step 5. ✅ traces to SC-009.

## Scenario 3 — Claim across worktrees, detect and recover a stale claim (User Story 3)

1. Claim `WI-1` from worktree A: create a Claim Record for `WI-1` (`owner = "agent-A"`, `worktree_path = "/repo-a"`) — its creation is the only write; `WI-1`'s own Work Item file is untouched. Claim `WI-3` from worktree B (`owner = "agent-B"`, `worktree_path = "/repo-b"`) the same way — confirm neither Claim Record references or touches the other item's Work Item file or Claim Record. ✅ traces to Acceptance Scenario 3.1.
2. Imagine `/repo-a` is deleted (worktree removed) without releasing the claim. Run reconciliation: since no worktree exists at `/repo-a`, `WI-1`'s Claim Record is reported `stale_claim` — the Claim Record itself is left untouched (read-only reconciliation, research.md), and `WI-1` remains computed as unavailable. ✅ traces to Acceptance Scenario 3.2.
3. **New — explicit recovery**: with the `stale_claim` finding from step 2 in hand, an agent performs the override: delete `WI-1`'s Claim Record on that evidence, then immediately create a new one for a different owner. `WI-1` is now claimed by the new owner; at no point was it observably unclaimed to a third party mid-override, since the override is a deliberate act, not an automatic expiry. ✅ traces to FR-019, data-model.md "Staleness."
4. Record an Evidence Pointer on `WI-3` (`kind = branch`, `value = "agent-b-wi3"`). Imagine that branch is later rebased. The Evidence Pointer is not edited or removed — it remains a historical observation. ✅ traces to Acceptance Scenario 3.3.

## Scenario 5 — Concurrent claim race on the same item (User Story 3, FR-018)

1. `WI-3` is open and unclaimed. Two agents, C and D, each attempt to create a Claim Record for `WI-3` at effectively the same instant, via the exclusive create-if-absent operation (data-model.md, "Claim atomicity contract").
2. **Expected**: exactly one of {C, D} succeeds — say C — and immediately holds a fully-formed Claim Record; D's attempt fails immediately with an unambiguous "already claimed" result, never a timeout, never an exception whose meaning is unclear, and never a state where both C and D believe they succeeded.
3. Repeating step 1 many times (varying which of C/D "wins") always produces the same shape of outcome: one winner, one clean loser, never two winners, never zero. ✅ traces to SC-004a.
4. **New — crash variant**: C's process crashes immediately after its Claim Record is created but before `owner`/`claimed_at` are written. The record exists but is empty. D, attempting to claim `WI-3` afterward, still receives "already claimed" (existence alone decides ownership) — D does **not** succeed just because the content is missing. Reconciliation reports `corrupt_claim` for `WI-3`, and the same explicit override from Scenario 3 step 3 is the sanctioned way to clear it. ✅ traces to data-model.md's "Crash/interruption."

## Scenario 6 — Generate a coordinator projection (User Story 4)

1. With `WI-2` still blocked (per Scenario 2 step 2 before `WI-1` completed) and `WI-1`/`WI-3` available, generate a projection per `contracts/coordinator-projection.md`.
2. **Expected**: the projection presents `WI-1` and `WI-3` as eligible; `WI-2` is either omitted or placed outside any `active_states` value, specifically because the target's `local` tracker adapter would not otherwise re-check `blocked_by` itself (research.md finding). ✅ traces to Acceptance Scenario 4.1.
3. Regenerate the projection again without changing any Work Item. **Expected**: identical result. ✅ traces to Acceptance Scenario 4.2.
4. Confirm: every fact used in Scenarios 1–3 above (listing, availability, claims, evidence) was determined without this scenario's projection step ever having run. ✅ traces to Acceptance Scenario 4.3.

## Out of scope for this quickstart

- Any actual file I/O, CLI invocation, or Symphony process — none exist yet.
- Performance/load testing — not a goal at this feature's scale (plan.md's Technical Context).
