# Contract: `bindle work status --json` (read-model, version 1)

This is the **stable, machine-readable contract** for `bindle work status --json` (spec.md FR-007/FR-008) — a physically separate concern from `specs/003-symphony-task-integration/contracts/symphony-projection-v1.md` (a published SQLite file for an external coordinator) and from `specs/001`/`specs/002`'s own internal `ProjectedWorkItem`/`ExternalProjectionRow` contracts. This one is printed JSON on stdout from a single CLI invocation — never a file, never a database, never a network-accessible endpoint (FR-007's own explicit prohibition). A future presentation layer (`bindle view`, or a script) depends on this document's shape, never on `WorkStatusSnapshot`'s internal Python field names or `work_status.py`'s own source.

## Artifact

Standard output of `bindle work status --json` (single-shot) or, with `--watch` added, standard output of `bindle work status --json --watch` (one document per refresh — see "Watch-mode framing" below). Never a file on disk; never served over a socket.

## Version

This document itself is the version marker — there is no `PRAGMA user_version`-style embedded version field, because this is a CLI's own printed output, not a regenerable artifact a separate process opens later. A future incompatible shape ships as a new `work-status-json-v2.md` and a corresponding CLI change, exactly like `symphony-projection-v1.md` → a hypothetical `-v2.md` would.

## Shape (single-shot, pretty-printed)

```json
{
  "tasks": [
    {
      "id": "T001",
      "title": "Add work_status.py",
      "status": "open",
      "claim": null,
      "dispatchable": true,
      "blocking_ids": []
    },
    {
      "id": "T002",
      "title": "Wire the CLI",
      "status": "open",
      "claim": {
        "owner": "alice",
        "claimed_at": "2026-08-28T12:00:00Z",
        "worktree_path": "/path/to/worktree",
        "branch": "feature/x"
      },
      "dispatchable": false,
      "blocking_ids": ["T001"]
    }
  ],
  "milestones": [
    {
      "id": "M001",
      "title": "Ship visibility",
      "status": "open",
      "claim": null,
      "review_ready": false,
      "not_ready_reason": ["T001", "T002"],
      "blocking_ids": []
    }
  ]
}
```

| Field | Type | Meaning |
|---|---|---|
| `tasks` | array, ordered by `id` | Every live (`archived_at IS NULL`) `type = 'task'` work item. |
| `tasks[].id` | string | The work item's canonical id. |
| `tasks[].title` | string or `null` | `WorkItem.title`, verbatim. |
| `tasks[].status` | string | One of `open`, `done`, `superseded` — `WorkItem.status`, verbatim, never collapsed into a boolean. |
| `tasks[].claim` | object or `null` | `null` iff unclaimed. When present: `owner` (string), `claimed_at` (ISO-8601 string), `worktree_path` (string or `null`), `branch` (string or `null`) — `ClaimInfo`, verbatim, from `WorkLedger.get_claim()`. |
| `tasks[].dispatchable` | boolean | Sourced verbatim from `WorkLedger.list_available_work_items()`'s own return value — never re-derived from `status`/`claim`/`blocking_ids` in this contract's own generator (`data-model.md`). |
| `tasks[].blocking_ids` | array of strings, ordered | The specific still-blocking dependency ids (`WorkLedger.list_blocking()`, verbatim). Empty array — never omitted, never `null` — when not blocked. |
| `milestones` | array, ordered by `id` | Every live `type = 'milestone'` work item. |
| `milestones[].id`/`title`/`status`/`claim` | same shapes as the task fields above | `status` here is one of `open`, `review`, `accepted`, `superseded`. |
| `milestones[].review_ready` | boolean | Sourced verbatim from `milestone_review.review_milestone(id).view.review_ready` (itself `WorkLedger.is_review_ready()`, unmodified) — never merged with `tasks[].dispatchable` into one generic field name or value space. |
| `milestones[].not_ready_reason` | array of strings | Subset of `{"blocked", "no_children"}` plus one entry per outstanding child id, verbatim from `review_milestone()`'s own diagnostic (`specs/004`). Empty array whenever `review_ready` is `true`. |
| `milestones[].blocking_ids` | array of strings, ordered | Same meaning as `tasks[].blocking_ids`, for the milestone's own `blocked_by` edges. |

## Guarantees

- **No generic "ready"/"state" field anywhere.** `dispatchable` (task-only) and `review_ready` (milestone-only) are always distinct keys under distinct array items — this contract never encodes `"state": "ready"` for either kind (planning brief's own explicit instruction; Terminology's "no new word that spans both").
- **Deterministic, byte-identical output across two invocations against an unchanged ledger** (spec.md SC-004). Every array is explicitly ordered by `id` (never dict/set iteration order); no field carries a wall-clock "generated at" value — see `research.md`, "No timestamp field in the JSON contract," which states why that field's *absence* is load-bearing for this guarantee, not an oversight.
- **Identical semantic facts to the plain-text form of `bindle work status`, for the same ledger state** (spec.md SC-003) — both are formatted from the identical `WorkStatusSnapshot` object (`work_status.build_snapshot()`), never two independently-derived computations.
- **Read-only; stdout only.** No HTTP server, socket, or other network-accessible interface is started merely to serve this JSON (FR-007). Producing it never creates, mutates, or removes any ledger row.
- **No historical/event data.** Only current-state facts — no "what changed since the last call" field exists or is planned without a separate, explicit decision (matching spec.md's Assumptions on the transition-history gap).

## Watch-mode framing (`--json --watch`): JSON Lines (NDJSON)

Single-shot `--json` (no `--watch`) emits **one complete JSON document**, pretty-printed with `indent=2`, matching `bindle repo info --json`'s existing convention, and the process then exits.

`--json --watch` instead emits **[JSON Lines](https://jsonlines.org/) (also known as NDJSON)** — the established term for "one complete, compact JSON value per line, newline-delimited, no enclosing array" — not an ad hoc or Bindle-specific streaming format. Each refresh prints exactly one line (`json.dumps(..., separators=(",", ":"))`, no `indent`) conforming to the identical shape documented above.

The contract, made explicit and testable:

- Each line is one complete JSON document conforming to this contract's own shape (`tasks`/`milestones`, every field above) — never a watch-specific variant schema.
- No partial JSON object is ever streamed: a line is only ever emitted after `build_snapshot()` has returned in full and `json.dumps()` has produced the complete string for that refresh.
- Deterministic ordering (every array ordered by `id`) applies identically inside each line — watch mode does not relax SC-004's determinism, it only repeats it once per refresh.
- Interruption (Ctrl+C) can only land between two already-flushed, complete lines, or before the current refresh has produced any output at all — never mid-line, since nothing in this design holds a JSON value open across multiple writes.

The two modes intentionally differ in whitespace formatting only (pretty vs. compact-JSON-Lines); the JSON *shape* itself (every field documented above) is identical in both.

## What this contract does not do

- It does not include the Dependency Frontier (`bindle work forecast`'s own output) — that remains plain-text-only in this feature (no FR/SC requires a `--json` form of it; `data-model.md`'s "What `bindle work status --json` serializes").
- It does not include Symphony runtime facts of any kind — this feature adds no Symphony-facing read at all (`research.md`, "Symphony endpoint discovery has no safe zero-config default").
- It does not assume a consumer beyond a script or a future renderer reading from stdout — there is no file to open, no schema-version pragma to check, and no persistence guarantee: this is a snapshot at print time, not a store.
