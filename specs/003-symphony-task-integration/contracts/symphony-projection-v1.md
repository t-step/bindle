# Contract: Symphony Projection (published SQLite export, version 1)

This is the **published, versioned, external contract** for the Symphony-facing projection — a physically separate artifact from `specs/001-durable-work-ledger/contracts/coordinator-projection.md` and `specs/002-milestone-task-work-items/contracts/coordinator-projection-v2.md`, which remain the contract for Bindle's own internal, in-process `generate_projection()`/`ProjectedWorkItem` and are unchanged by this document. An external reader depending on this contract never needs to read either of those, and never needs to open or understand `ledger.sqlite3`.

## Artifact

A SQLite database file at `{repo_root}/.bindle-work/symphony-projection.sqlite3` (`repo_root` = the repository's Git common directory — the same one every linked worktree resolves via Bindle's own identity model, `docs/WORKTREES.md`). Regenerated in full on every publish; never hand-edited; never itself a source of truth for anything.

## Version

`PRAGMA user_version = 1` inside the export file itself. An external reader MUST check this before relying on the schema below — a future incompatible shape ships as a new `symphony-projection-v2.md` with a bumped `user_version`, never as a silent change to this document's own schema.

## Schema

One table, `task_projection`:

| Column | Type | Never NULL | Meaning |
|---|---|---|---|
| `id` | `TEXT` (primary key) | yes | A stable identifier for this task, unique across every Spec Kit feature ever loaded. Opaque — an external reader MUST NOT parse its internal structure. |
| `identifier` | `TEXT` | yes | A non-empty, workspace-name-safe identifier (no `:`) suitable for naming an external workspace/branch/directory for this task. |
| `title` | `TEXT` | no | Human-readable title. |
| `description` | `TEXT` | no | Human-readable description text. |
| `status` | `TEXT` | yes | One of `open`, `done`, `superseded` — the task's status, exposed directly as a readable value (never as a pair of booleans an external reader must reconstruct from). |
| `dispatchable` | `INTEGER` (`0` or `1`) | yes | Whether this task may currently be claimed and started: `status = 'open' AND` not claimed `AND` not blocked, computed entirely inside Bindle. |
| `created_at` | `TEXT` | yes | The canonical work item's own creation timestamp, preserved verbatim — never derived or synthesized at publish time. Symphony's own dispatch ordering ranks simultaneously-eligible candidates by `(priority_rank, created_at, identifier)`; without a real value here that ordering would silently collapse to alphabetical-by-`identifier`. |

## Guarantees

- **Task rows only, always.** No row in `task_projection` ever corresponds to a `type = 'milestone'` work item, under any status, claim, or blocking state (FR-014, SC-007). This holds structurally, by the generating query's own `WHERE` filter — not by convention a future change could silently break.
- **`dispatchable` needs no further evaluation.** An external reader MUST NOT need to inspect blocking edges, claims, or dependency state itself to decide whether a row is currently eligible — `dispatchable = 1` is the complete answer (FR-016).
- **Disposable and regenerable.** Two publishes from an unchanged ledger produce an equivalent `task_projection` table (SC-006). This file is never the only record of any fact it contains — every value here is derivable again from the canonical ledger at any time (FR-017).
- **No write path for external callers.** External consumers MUST open this file using SQLite read-only mode (e.g. `sqlite3.connect("file:...?mode=ro", uri=True)`) and MUST NOT create, migrate, repair, or otherwise mutate it. `publish()` is the sole writer; nothing in this contract grants or implies write access to any other caller.
- **No delivery/acknowledgment guarantee.** Exactly like the existing internal projection contract, this is a snapshot at generation time, not an event stream — a status change that happens after generation is simply not reflected until the next publish.
- **Publish is atomic; never torn.** `publish()` rewrites the whole `task_projection` table and `PRAGMA user_version` inside one SQLite transaction against the existing file. Adversarially verified (research.md's "Decision: publish atomicity mechanism") under concurrent reads, a mid-transaction failure, and a hard process kill before commit: a reader never observes a partial table, a missing table, or a schema/version mismatch. **An external reader MUST wrap its own schema-version check and row read in one transaction** (e.g. `BEGIN` ... `PRAGMA user_version` ... `SELECT ... FROM task_projection` ... `COMMIT`) — two separate, unwrapped autocommit statements can otherwise observe two different publish generations, since each such statement is its own implicit transaction. A long-lived open reader transaction can, in the current default journal mode, cause a concurrent `publish()` to fail with "database is locked" after a 5-second timeout — a liveness consideration, not an atomicity one; keep reader transactions short.

## What this contract does not do

- It does not choose a dispatch order, priority, or concurrency limit — no such column exists, and none is planned to be added without a separate, explicit decision.
- It does not translate into any Symphony-side tracker format. A future Symphony-side `Tracker` adapter, if built, would read this artifact and map its rows onto `Tracker.Issue` directly — that adapter is separate future work outside this feature's scope (`docs/SYMPHONY.md`) and is unrelated to Symphony's own separate, standalone local tracker (`.symphony/local_tracker.json`).
- It does not assume Symphony, or any particular external reader, is installed or running — this file and its guarantees hold with zero external consumer present.
