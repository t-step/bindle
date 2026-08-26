# Phase 1 Data Model: Durable Work Ledger

This is a conceptual data model (field names, types, and invariants), not an implementation. Serialization details (exact TOML table names, file naming) are left to the first implementation slice; the *shape* below is what this plan fixes — including, as of this revision, the concurrency and dependency-lifetime rules a naive read-modify-write model would get wrong (see `research.md`'s "Decision: claim atomicity" and "Decision: dependency resolution across archival" for the full rationale; this file states the resulting contract).

## Work Item

One decomposed, independently claimable unit of implementation work. One file per item.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Stable identifier, assigned at creation, never reused or reassigned. Independent of session/worktree/branch (FR-001). |
| `title` | string | yes | Short human-readable summary. |
| `source` | Source Reference (embedded, see below) | yes | Pointer to the upstream intent artifact (FR-002). |
| `status` | enum: `open` \| `done` \| `superseded` | yes | Coarse status only (FR-005). Default `open` at creation. |
| `blocked_by` | list of item `id` | no (default empty) | Flat, **stable, declared** references to other items (FR-006). Never auto-pruned when a referenced item resolves — see "Dependency resolution" below. Not a priority/order — see Blocking Reference below. |
| `evidence` | list of Evidence Pointer | no (default empty) | Appended over time as work progresses (FR-008). |
| `superseded_by` | item `id`, optional | only when `status = superseded` | Mirrors `docs/DECISIONS.md`'s "superseded in place" convention (FR-016). |
| `created_at` | timestamp | yes | Set once at creation. |
| `updated_at` | timestamp | yes | Set on every mutation to this item's own record (not a mutation to a different item that merely references it, and not a mutation to this item's own Claim Record — see below, which is a separate file with its own lifecycle). |

**Change from the original data model**: `claim` is **no longer a field embedded in the Work Item record.** It is a separate Claim Record (its own small file, keyed by the same `id`) — see "Claim Record" below for why, and for the atomicity contract this split exists to provide. A Work Item's own file is never touched in order to claim or release it.

**Invariants**:
- `status = superseded` requires `superseded_by` to be set; every other status requires it to be absent.
- An item's own `id` must never appear in its own `blocked_by` (a direct self-cycle is rejected at write time; longer cycles remain a *detectability* requirement on the reader — see Edge Cases in spec.md — since a cycle can be formed by two items written independently).
- `blocked_by` is a **declared, historical set of dependency edges**, not a live "currently-blocking" list. It answers "what did this item's owner say it depends on," not "what is still open right now" — that second question is always computed fresh (see "Dependency resolution" below), never by mutating this list. Nothing in this model prunes, rewrites, or replaces entries in `blocked_by` when a referenced item resolves.

## Dependency resolution (resolving one `blocked_by` entry)

Resolving a single `id` in `blocked_by` to an outcome checks, in order:

1. **An active Work Item with that `id` exists** → its `status` governs directly: `open` → **still blocking**; `done` or `superseded` → **satisfied** (superseded counts as resolved-for-blocking-purposes, unchanged from the original rule: the named piece of work will not be produced under that identity, and if the dependency still matters, re-pointing to whatever superseded it is an explicit act, not something this model infers).
2. **No active Work Item, but a Tombstone with that `id` exists** (see "Tombstone" below) → the Tombstone's recorded terminal `status` governs, with the same `done`/`superseded` → satisfied rule as above. This is what makes archival safe: a completed item's dependency-relevant fact survives its own archival forever, in a form far smaller than the full record.
3. **Neither an active Work Item nor a Tombstone exists for that `id`** → **Dangling** — genuinely unresolvable. This is the one and only case that means "unknown/corrupt," and it can never be produced by an item that actually completed and was archived (step 2 always resolves those). A Dangling reference is treated **conservatively as still blocking** (never silently treated as satisfied) and is surfaced by reconciliation as `dangling_blocker` for explicit human/agent resolution — fix the reference, or explicitly acknowledge and accept it.

**Derived facts** (computed on demand, never stored):
- **Blocked**: an item is blocked iff any `id` in its `blocked_by` resolves (above) to "still blocking" or "Dangling."
- **Claimed**: an item is claimed iff a Claim Record exists for its `id` (see "Claim Record" below) — never a field read off the Work Item itself.
- **Available to start**: `status = open` AND not Claimed AND not Blocked (User Story 2). Staleness of an existing claim does **not** change this computation — see "Claim Record" → "Staleness does not change availability automatically" below; a stale claim still counts as Claimed until explicitly released.

## Claim Record

**A separate small record per claimed item, not a field embedded in the Work Item** — this split is the direct fix for the read-modify-write race a single shared file would otherwise create (`research.md`, "Decision: claim atomicity"). Existence of a Claim Record for a given `id` *is* the claim; there is no additional "claimed" flag anywhere else to fall out of sync with it.

| Field | Type | Required | Notes |
|---|---|---|---|
| `owner` | string | yes | Identifies who claimed it — an agent/session label or a person's name; format not prescribed by this plan. |
| `claimed_at` | timestamp | yes | |
| `worktree_path` | string, optional | no | Absolute path to the worktree the claim is being worked in, when applicable. Per `docs/WORKTREES.md`, this is machine-local and not a portable identifier — it exists for reconciliation, not cross-machine addressing. |
| `branch` | string, optional | no | Descriptive only (`docs/WORKTREES.md`: "Branch names are descriptive context, never primary identity") — never used as the sole way to find the work. |

### Claim atomicity contract (FR-018)

- **Acquire**: creating a Claim Record for an `id` MUST use a filesystem primitive that is atomic and exclusive at the directory-entry level — i.e., a create operation that either (a) succeeds and is the *only* such operation to succeed among any number of concurrent attempts against the same `id`, or (b) fails immediately and unambiguously because the record already exists. (The canonical example of such a primitive is POSIX exclusive file creation — "create this path, but fail instead of overwriting if it already exists" — but this contract does not mandate a specific syscall; any mechanism with the same all-or-nothing, no-overwrite guarantee satisfies it.) No read-then-write, no "check if claimed, then write" two-step sequence satisfies this contract, regardless of how small the gap between the two steps is.
- **Exactly one successful claimant**: guaranteed directly by the primitive above — of any number of concurrent acquire attempts for the same `id`, exactly one succeeds.
- **Unambiguous failure for a losing claimant**: every other concurrent attempt receives an immediate, deterministic "already claimed" result — never a timeout, never an exception the caller must interpret, never a state where both callers believe they hold the claim.
- **Content is not the arbitration mechanism**: the *existence* of the Claim Record decides ownership; its *content* (owner, timestamp, worktree pointer) is written immediately after the record is created and is purely descriptive. This matters for the crash case below.
- **Crash/interruption**: if the acquiring process crashes after the record is created but before its content is fully written, the Claim Record exists but is empty or unparsable. This is **not** treated as available (the record still exists — no double-claim is possible), and it is **not** treated as a normal valid claim either. It is a distinct, surfaced reconciliation finding — `corrupt_claim` — resolved via the same explicit override described under "Staleness" below. No claim is ever silently lost or silently duplicated by a crash; at worst, its descriptive content is incomplete and requires the same explicit human/agent attention a stale claim does.
- **Safe release**: releasing a Claim Record is deleting it. Deleting a record that does not exist is a no-op (idempotent release, not an error). An ordinary release (by the recorded owner) is unconditional; a release by anyone else is an **override** and MUST only be performed after observing reconciliation evidence justifying it (`stale_claim` or `corrupt_claim` — see "Staleness" below) — this is a documented process expectation on the caller, not something the plain-file mechanism itself can cryptographically enforce, consistent with this repository's existing single-operator trust model.
- **Multi-worktree correctness**: guaranteed because Claim Records live in the same Git-common-directory-scoped ledger location as Work Items (unchanged storage-location decision) — every linked worktree on the machine creates/reads the exact same file, not a per-worktree copy, so the OS-level exclusivity guarantee is shared across every worktree by construction.
- **Explicitly not guaranteed**: atomic claiming of *multiple different* items as one transaction (spec.md's Assumptions) — each `id`'s Claim Record is acquired independently; there is no "claim these three items or none" operation.

### Staleness — does not change availability automatically

- **Staleness determination**: a Claim Record is **stale** when its recorded `worktree_path` no longer exists as a worktree on this machine (or, when `branch` is also recorded, that branch itself is gone). This is determined *only* by checking currently observable repository/filesystem state at the moment reconciliation runs — never by elapsed time, a heartbeat, or a lease expiry. No background process is required or assumed.
- **A stale (or corrupt) claim still makes the item unavailable** under the "Available to start" computation above. Reconciliation surfaces staleness; it does not clear it. This preserves the existing "reconciliation is read-only" posture (`research.md`, "Decision: claim safety") without exception.
- **Recovery is the explicit override release** defined in "Safe release" above: an actor who has just observed a `stale_claim` or `corrupt_claim` reconciliation finding for a specific `id` may delete that Claim Record on that basis, optionally immediately followed by acquiring a new one (a "replace"). This can happen the instant staleness is noticed — "explicit" means "on demand, whenever someone acts," not "after waiting out a timer." A stranded item is only ever as stuck as it takes someone to notice and run this one operation.
- **Evidence surfaced before an override**: the specific reconciliation finding for that `id` — which check was performed (worktree path or branch), and that it came back absent — so an override is never performed blind. Recording *why* a specific override happened is optional, not a new mandatory field: an Evidence Pointer (`kind = other`) MAY be appended to the Work Item noting the override, using the entity this model already has, rather than inventing a new audit-log concept.
- **Explicitly not solved by this model**: a claim whose worktree still exists but whose owner has simply stopped working (no absence to detect). This is a genuine, acknowledged gap — no automatic mechanism claims to catch it (per this feature's own constraint against leases/heartbeats/timeouts); a human noticing and applying judgment remains the only recourse, and they may still use the same override release, self-justified rather than reconciliation-justified, at their own discretion.

## Tombstone

Created in the same operation that archives a Work Item out of the active set (i.e., once its `status` has reached `done` or `superseded` and it is removed from active view — see `research.md`, "Decision: retention," for when archival happens). A Tombstone is deliberately smaller than the record it replaces: it exists solely to keep dependency resolution correct forever, not to preserve history.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Same identifier as the archived Work Item. |
| `status` | enum: `done` \| `superseded` | yes | The item's final status at archival time. Never `open` — an item is not archived while still open. |
| `superseded_by` | item `id`, optional | only when `status = superseded` | Carried over from the archived Work Item, so a chain of supersession remains followable even after archival. |

**Invariant**: A Tombstone is permanent once created — it is not itself later deleted by this model. It is tiny (three fields) and is not a growing log: one Tombstone per archived item, never appended to, never accumulating history beyond its own final state. This is why archival does not turn the ledger into a permanent task-history database (`docs/PHILOSOPHY.md` preservation rule, D016): the *full* record (title, source, evidence, claim history) is discarded at archival; only the minimum fact needed to keep other items' dependency truth resolvable survives, and that fact is a fixed few bytes per item, not an ever-growing narrative.

**Consequence for "attempts to archive an item still needed to resolve dependency truth"**: there is no such failure case to guard against. Archiving an item and creating its Tombstone happen together, so dependency truth is never lost at the moment of archival — a Work Item that depends on an archived one always finds the Tombstone in step 2 of "Dependency resolution" above. No precondition check ("is anyone still blocked on me?") is needed before archiving.

## Blocking Reference

Not a separate stored entity — it is simply an `id` value inside another Work Item's `blocked_by` list. Modeled here only to name the concept precisely, since spec.md's Key Entities lists it as distinct from a Claim or Evidence Pointer: a Blocking Reference asserts *this item cannot be considered eligible until that item resolves*, nothing about ordering, priority, or who should work on either one.

## Evidence Pointer

Embedded list entries on a Work Item — not a separate file, not a copy of the referenced content (D014 replaceability).

| Field | Type | Required | Notes |
|---|---|---|---|
| `kind` | enum: `branch` \| `commit` \| `pull_request` \| `other` | yes | |
| `value` | string | yes | The pointer itself — a branch name, a commit SHA (full, per `docs/WORKTREES.md`'s own "full HEAD commit SHA" convention), a PR URL/number, or a free-form pointer for `other`. |
| `recorded_at` | timestamp | yes | |
| `note` | string, optional | no | Free-text context, e.g. why this pointer was added — including, optionally, a note explaining a stale/corrupt-claim override (see Claim Record above). |

**Invariant**: Evidence Pointers are append-only and immutable once recorded (mirroring `docs/WORKTREES.md`'s evidence-immutability rule: "Later Git operations do not rewrite existing evidence"). A rebased/squashed/deleted branch's pointer is left in place as a historical observation, not deleted or "fixed."

## Source Reference

Embedded in a Work Item, not a separate file.

| Field | Type | Required | Notes |
|---|---|---|---|
| `kind` | enum: `speckit_task` \| `plan` \| `adhoc` | yes | |
| `locator` | string | yes | E.g. `specs/001-durable-work-ledger/tasks.md#T012`, `plans/active/2026-08-24-symphony-coordination-exploration.md#work`, or a free-form description when `kind = adhoc`. |
| `promoted_by` | string, optional | no | Who/what made the explicit promotion decision (FR-003), for traceability — not a claim, not an owner. |

**Invariant**: `locator` is a pointer, never a copy of the source text — if the source document is later edited or superseded, the Work Item's own `source.locator` is not automatically updated (spec.md Edge Cases: "the model MUST NOT require the ledger to auto-track upstream document revisions").

## Reconciliation Report

The read-only output of a reconciliation pass — not a stored entity, generated on demand from current Work Item records, Claim Records, Tombstones, plus observed repository state.

| Field | Type | Notes |
|---|---|---|
| `item_id` | string | Which item this finding is about. |
| `finding` | enum: `stale_claim` \| `corrupt_claim` \| `dangling_blocker` \| `dangling_evidence` \| `cycle_detected` \| `duplicate_source` | See spec.md Edge Cases and this file's "Claim Record"/"Dependency resolution" sections for the scenario each finding corresponds to. |
| `detail` | string | Human-readable explanation, e.g. which worktree path was checked and found absent, or which `blocked_by` id resolved to neither an active item nor a Tombstone. |

**Invariant**: Generating a Reconciliation Report never writes to any Work Item, Claim Record, or Tombstone (FR-010). It never releases a stale/corrupt claim itself — that remains a separate, explicit act (see "Claim Record" → "Staleness").
