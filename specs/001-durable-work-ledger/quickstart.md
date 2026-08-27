# Quickstart: Validating the Durable Work Ledger Model

No code exists yet — this is a validation guide for the *model*, to be exercised by hand-reasoning now, and re-used as the shape of real tests once the first implementation slice (see plan.md's recommended next step) exists. Each scenario below traces directly to an Acceptance Scenario in `spec.md`.

**2026-08-26 persistence-model correction**: scenarios below are restated against the SQLite relational model in `data-model.md` (superseding the original per-item-TOML-file model — see `research.md`'s "Decision: storage format"). Statement shapes shown (`INSERT`/`DELETE`/`SELECT`) are illustrative, not a fixed API.

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
5. **New**: archive `WI-1` — within one transaction, its row is thinned to `{id: WI-1, status: done, superseded_by: NULL, archived_at: <now>}` and its evidence/edges/claim rows (if any) are removed; the row itself is never deleted (`data-model.md`, "Archival"). Recompute `WI-2`'s blocked status again: resolving `WI-1` is the same single-table lookup as before (`SELECT status, superseded_by FROM work_items WHERE id = 'WI-1'`), which still returns `status = done` from the thinned row, so `WI-2` remains not blocked — archival did not change the answer, and no second table was consulted. ✅ traces to SC-008.
6. **New**: imagine instead `WI-2.blocked_by` had named a typo'd id, `WI-0`, that never existed. In the normal write path this edge is rejected outright at declaration time by the `work_item_blocked_by` foreign key constraint; imagine instead a connection that ran without `PRAGMA foreign_keys = ON` (a misconfiguration) allowed it to be written. Resolving `WI-0` finds no row in `work_items` at all → `dangling_blocker`, and `WI-2` is conservatively still blocked, distinguishable in the Reconciliation Report from `WI-1`'s thinned-but-present, satisfied case in step 5. ✅ traces to SC-009.

## Scenario 3 — Claim across worktrees, detect and recover a stale claim (User Story 3)

1. Claim `WI-1` from worktree A: `INSERT INTO work_item_claims (work_item_id, owner, claimed_at, worktree_path) VALUES ('WI-1', 'agent-A', <now>, '/repo-a')` — this insert is the only write; `WI-1`'s own `work_items` row is untouched. Claim `WI-3` from worktree B the same way (`owner = 'agent-B'`, `worktree_path = '/repo-b'`) — confirm neither claim row references or touches the other item's `work_items` row or claim row (they are independent rows in the same table, in the same database file, which both worktrees open identically). ✅ traces to Acceptance Scenario 3.1.
2. Imagine `/repo-a` is deleted (worktree removed) without releasing the claim. Run reconciliation: `SELECT * FROM work_item_claims` returns `WI-1`'s row; since no worktree exists at `/repo-a`, it is reported `stale_claim` — the row itself is left untouched (reconciliation issues no write, research.md), and `WI-1` remains computed as unavailable. ✅ traces to Acceptance Scenario 3.2.
3. **New — explicit recovery**: with the `stale_claim` finding from step 2 in hand, an agent runs `DELETE FROM work_item_claims WHERE work_item_id = 'WI-1'` on that evidence — this is the override *release*. `WI-1` is now unclaimed and claimable by anyone; the releasing agent does not thereby own it. The agent then attempts to acquire a new claim for `WI-1` through the ordinary `INSERT` (data-model.md, "Claim atomicity contract"), exactly like any other acquisition. If nothing else races it, this succeeds and `WI-1` is claimed by the new owner. If another actor's acquire attempt wins the race in the gap between the `DELETE` and the new `INSERT` — a real, observable possibility this model does not exclude — the releasing agent's own `INSERT` instead fails with the ordinary primary-key-violation "already claimed" result, and it must not assume it owns `WI-1`; the other actor does. Release and reacquisition remain two independent statements, each individually (not jointly) arbitrated by the same constraint that governs any other claim — no atomic delete-and-replace primitive is introduced. ✅ traces to FR-019, data-model.md "Staleness," and the spec.md Edge Case on override release.
4. Record an Evidence Pointer on `WI-3` (`INSERT INTO work_item_evidence (work_item_id, kind, value, recorded_at) VALUES ('WI-3', 'branch', 'agent-b-wi3', <now>)`). Imagine that branch is later rebased. The row is not edited or removed — it remains a historical observation. ✅ traces to Acceptance Scenario 3.3.

## Scenario 4 — Concurrent claim race on the same item (User Story 3, FR-018)

1. `WI-3` is open and unclaimed. Two agents, C and D, each attempt `INSERT INTO work_item_claims (work_item_id, owner, claimed_at) VALUES ('WI-3', ..., ...)` at effectively the same instant.
2. **Expected**: exactly one of {C, D} succeeds — say C — and immediately holds a fully-formed claim row (SQLite's single-writer serialization plus the primary key on `work_item_id` guarantee this); D's `INSERT` fails immediately with a primary-key constraint violation, never a timeout, never an exception whose meaning is unclear, and never a state where both C and D believe they succeeded.
3. Repeating step 1 many times (varying which of C/D "wins") always produces the same shape of outcome: one winner, one clean loser, never two winners, never zero. ✅ traces to SC-004a.
4. **New — crash variant, revised for SQLite's transactional atomicity**: C's process crashes mid-transaction, before `COMMIT`, while inserting its claim row. Because the `INSERT` is a single statement inside a transaction that never committed, SQLite rolls it back entirely on next open — `WI-3`'s claim row **does not exist at all**, exactly as if C had never attempted it. D, attempting to claim `WI-3` afterward, succeeds normally; there is no intermediate "row exists but is empty" state reachable this way, unlike the original file-based model's crash window. `corrupt_claim` is reserved for a narrower case not exercised by an ordinary crash: e.g. the database file itself is corrupted at the storage layer (detectable via `PRAGMA integrity_check`), or a connection ran with constraints bypassed and left an inconsistent row. When that narrower case does occur, the same explicit override from Scenario 3 step 3 is the sanctioned way to clear it. ✅ traces to data-model.md's "Crash/interruption" and the revised SC-010 (see spec.md).

## Scenario 5 — Generate a coordinator projection (User Story 4)

1. With `WI-2` still blocked (per Scenario 2 step 2 before `WI-1` completed) and `WI-1`/`WI-3` available, generate a projection per `contracts/coordinator-projection.md`.
2. **Expected**: the projection presents `WI-1` and `WI-3` as eligible; `WI-2` is either omitted or placed outside any `active_states` value, specifically because the target's `local` tracker adapter would not otherwise re-check `blocked_by` itself (research.md finding). ✅ traces to Acceptance Scenario 4.1.
3. Regenerate the projection again without changing any Work Item. **Expected**: identical result. ✅ traces to Acceptance Scenario 4.2.
4. Confirm: every fact used in Scenarios 1–4 above (listing, availability, claims, evidence) was determined without this scenario's projection step ever having run. ✅ traces to Acceptance Scenario 4.3.

## Out of scope for this quickstart

- Any actual database I/O, CLI invocation, or Symphony process — none exist yet.
- Performance/load testing — not a goal at this feature's scale (plan.md's Technical Context).
