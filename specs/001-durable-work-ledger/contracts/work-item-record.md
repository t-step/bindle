# Contract: Work Item Record (agent/human-facing)

This is the contract an agent or maintainer reads/writes against — not a code interface (no ledger code exists yet). It documents the guarantees a future implementation must uphold, derived from data-model.md and spec.md's functional requirements.

## Read guarantees

- Listing all work items MUST be possible from any linked worktree of the repository, with identical results, at a given point in time (FR-011; resolved storage location: the Git common directory, research.md).
- Reading a single item by `id` MUST return the same record structure regardless of which worktree or session performs the read.
- Computing "available to start" (data-model.md's derived fact) for the full set of items MUST NOT require any live process, network access, or coordinator (FR-012).
- A stale or corrupt claim (data-model.md's "Claim Record" section) MUST be discoverable by inspecting only: the Claim Record's own recorded `worktree_path`/`branch` and readability, and currently observable repository/filesystem state — no external service call.
- Resolving whether a work item's declared blocking relationship is currently satisfied MUST be possible by checking only the active item set and, when a referenced item has been archived, its permanent Tombstone (data-model.md) — never requiring the full historical record of an archived item to still exist.

## Write guarantees

- Creating a Work Item is only ever performed by an explicit act naming a Source Reference (FR-002/FR-003) — there is no operation that creates a Work Item without one.
- Two different Work Items MUST be independently writable without one write affecting the other's stored record (SC-004) — the storage form (research.md: one file per item) exists specifically to make this true by construction, not by a locking layer.
- Marking an item `done` or `superseded` MUST NOT delete its record outright; a `superseded` item retains `superseded_by` (FR-016), and archiving it MUST leave behind a permanent Tombstone before or in the same step as removing the full record (FR-020, data-model.md).
- No write operation defined by this contract computes or persists a dispatch order, priority rank, or concurrency assignment among items (FR-015) — those remain absent from the record entirely.

## Claim guarantees (FR-018, FR-019 — the precise concurrency contract)

- **Acquiring a claim MUST be a single atomic, exclusive create-if-absent operation against a claim record dedicated to that item's id — never a read-then-write against the Work Item's own file or any shared file.** Of any number of concurrent acquire attempts for the same item, exactly one MUST succeed; every other MUST receive an immediate, deterministic "already claimed" failure — not a timeout, not an ambiguous result, and never a window in which more than one attempt could believe it succeeded. This is precise enough to test deterministically: spawn N concurrent acquire attempts against one never-before-claimed item id and assert exactly one success and N−1 identical, immediate failures, repeated across many trials (SC-004a).
- **The claim record's existence, not its content, is what decides ownership.** If the acquiring process crashes after the record exists but before its content (owner, timestamp, worktree pointer) is fully written, the record MUST still be treated as claimed (never as available), and MUST be surfaced as a distinct `corrupt_claim` finding rather than trusted as a normal, attributable claim.
- **Releasing a claim is deleting its record.** Releasing an already-released (nonexistent) claim MUST be a no-op, not an error. Release by the recorded owner MUST always be permitted. Release by anyone else (an override) MUST only be performed on the basis of an observed `stale_claim` or `corrupt_claim` reconciliation finding for that specific item — never automatically, never on a timer.
- **Reconciliation finding a claim stale or corrupt MUST NOT itself release it or change the item's computed availability** — the item remains unavailable until the explicit override above is performed (FR-010).

## Non-goals of this contract

- No transactional multi-item write ("claim these three items atomically, or none") is guaranteed or required — only single-item claim acquisition is covered by the atomicity guarantee above.
- No automatic lease, heartbeat, or timeout-based claim expiry is defined or implied — staleness is determined solely by checking observable repository/filesystem state at the moment reconciliation runs, on demand, never by elapsed time.
- No network-facing API is defined — this is a local file contract, consistent with `docs/SCOPE.md`'s "Bindle does not own... generic project management" as a hosted concept.
