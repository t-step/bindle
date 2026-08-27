# Contract: Spec Kit Task Load

This documents the loading operation's input/output contract — what a maintainer or automation invoking it may rely on.

## Input

Exactly one Spec Kit feature directory (`specs/NNN-slug/`), containing a `tasks.md` file in the shape `specs/001-durable-work-ledger/tasks.md` and `specs/002-milestone-task-work-items/tasks.md` already use: lines of the form

```
- [ ] T### [optional bracketed tag] Description text... [Depends on: T00X, T00Y.]
```

The loading operation is never invoked implicitly — no file watcher, no Git hook, no side effect of `tasks.md` being created, edited, or committed triggers it (FR-002). It is always a maintainer's or automation's own explicit call naming one feature directory.

## What loading does

For each parseable task line in the named `tasks.md`:

1. Derive `id = "speckit:{feature-directory-name}:{task-id}"` and `source_locator = "{feature-directory-path}/tasks.md#{task-id}"` (`data-model.md`).
2. If no work item with this `id` exists yet: create one (`type = 'task'`, `status = 'open'`, `source_kind = 'speckit_task'`, the derived `source_locator`, title/description from the line's text).
3. If a work item with this `id` already exists: call `resync_declarative_fields()` to update only its `title`/`description` from the current line text — nothing else on that row changes.
4. After every task line in the file has been processed (pass 1), resolve every `Depends on:` clause against the same file's own now-created/updated task ids and add any `blocked_by` edge not already recorded (pass 2) — never removing a previously recorded edge.

## Guarantees

- **Idempotent.** Invoking the operation twice against an unchanged `tasks.md`, with no intervening lifecycle activity, leaves the ledger's set of ids, statuses, claims, and evidence completely unchanged (SC-002).
- **Non-destructive to runtime state.** A task's `status`, claim, and evidence are never read or written by this operation, on either the first load or any subsequent reload (FR-006, SC-003).
- **Declarative fields only, additive dependencies only.** `title`/`description` may change on reload to match the current source text; `blocked_by` edges may only be added, never removed (FR-007, FR-008).
- **No cross-feature collision.** Two different feature directories that each declare a "T001" produce two independently identifiable work items (FR-004, SC-004).
- **Partial-file tolerance.** A single unparseable line is reported and skipped; every other well-formed line in the same file still loads (FR-011) — this operation is not required to be all-or-nothing across a whole file, consistent with the ledger's own documented non-goal of no transactional multi-item write (`specs/001-durable-work-ledger/contracts/work-item-record.md`).
- **Dependency-not-yet-loaded is reported, not silently dropped or silently written as a dangling reference.** A `Depends on:` clause naming a task id absent from the same `tasks.md` is surfaced to the caller as a distinct outcome (FR-010).
- **Checkbox-state independent.** The `- [ ]`/`- [x]` marker on a task line is never read or required by this operation (FR-012).

## Non-goals

- This is not a general Markdown task-list parser — a differently-structured Markdown checklist is out of scope and is not expected to load correctly.
- This operation never creates, moves, or deletes a milestone work item — Spec Kit's own task lines have no milestone concept, so nothing here ever produces `type = 'milestone'`.
- This operation never deletes or archives a work item — removing a task line from `tasks.md` after it has been loaded has no effect on the already-loaded work item.
