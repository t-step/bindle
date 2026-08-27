# Durable work ledger (001): task generation and composition handoff

Date: 2026-08-26. Status: **superseded by completion.** The S1-S7
composition and waves recorded below were executed by a later session on
this same date, following this handoff exactly (no reopened decisions, T022
resolved as recorded here). All 43 tasks in `specs/001-durable-work-ledger/
tasks.md` are implemented and verified (`src/bindle/work_ledger.py`,
`tests/test_work_ledger.py`, `bash scripts/check.sh` passing) as of commits
`aace54f` (S1-S2), `3547ec1` (S3-S4), `97a7f07` (S5-S6), `583503c`/`169952d`
(S7) on `spec/work-ledger-task-generation`. This document is retained,
unedited below, as the historical record of the composition analysis and
the T022 resolution — not as an open resumption point. This document
originally existed so a fresh session (no memory of the session that
produced `specs/001-durable-work-ledger/tasks.md`) could resume
implementation of `specs/001-durable-work-ledger/` without re-deriving the
task graph, without re-running task-composition analysis, and without
reopening decisions already settled in `research.md`/`data-model.md`/
`plan.md`.

## Outcome

`specs/001-durable-work-ledger/tasks.md` (43 tasks, Setup → Foundational →
US1 → US2 → US3 → US4 → Polish) exists and has been analyzed into seven
agent-sized delivery slices, S1–S7, with dependencies, parallel-safety
judgments, and one resolved ambiguity (T022's fixture-construction method).
This handoff makes that composition — and the reasoning behind it —
resumable from tracked repository state rather than from conversation
history, per `docs/DATA-OWNERSHIP.md` ("Session narrative and work
records" → "a repository handoff file under `plans/`").

## Why now

Two sessions produced this state: one generated `tasks.md` and ran a
task-composition analysis (a skill available locally but not registered as
an installed plugin in that session, so its method was read and applied
directly); a second resolved the one real ambiguity that analysis
surfaced and was asked to persist all of it durably before any
implementation begins. Left only in conversation history, a fresh session
would have to re-read all of `spec.md`/`plan.md`/`research.md`/
`data-model.md`/`contracts/`/`quickstart.md`/`tasks.md`, re-derive the
same dependency graph, and re-discover the same T022 ambiguity — or worse,
resolve it differently and silently introduce the S3→S4 coupling this
handoff exists to prevent.

## Scope

**In scope for this document:** the S1–S7 composition, the waves, the
parallelism/collision guidance, the T022 resolution, and the recorded next
action.

**Out of scope, and not reopened by anything here:**
- The SQLite persistence decision (`research.md`, `data-model.md`) — settled.
- The spec itself (`spec.md`) — not re-clarified, not re-scoped.
- The task decomposition in `tasks.md` — not renumbered or regenerated,
  beyond the single T022 clarification described below.
- Any actual implementation of `src/bindle/work_ledger.py` or
  `tests/test_work_ledger.py` — neither file exists yet.
- Dispatching any subagent — none has been dispatched under this plan.

## Evidence

- Branch: `spec/work-ledger-task-generation`, based on `main` @ `312d7fa`.
- `specs/001-durable-work-ledger/plan.md` — "2026-08-26 task-generation
  scope correction" note: this feature originally deferred task generation
  (`tasks.md # NOT created`); that deferral is lifted, in place, with the
  original constraint's text preserved as history rather than deleted.
- `PLAN.md` item 3 — updated to list `tasks.md` among 001's artifacts and
  note the deferral was lifted.
- `specs/001-durable-work-ledger/tasks.md` — 43 tasks (T001–T043) across
  Setup (2), Foundational (5), US1 (6), US2 (9), US3 (11), US4 (4), Polish
  (6). Format-validated: every task line matches
  `- [ ] T### [P?] [US#?] ... <file path>`.

## Work: the S1–S7 composition

Spec Kit's 43 tasks are a **detailed implementation decomposition, not 43
independent agent jobs.** The composed units below, not the raw phase
list, are the appropriate candidate boundaries for agent-sized execution.
**Do not assume one task equals one subagent.**

| Slice | Tasks | Delivers | Depends on | Parallel-safe with |
|---|---|---|---|---|
| **S1** — Ledger bootstrap | T001–T007 | DB location resolution, SQLite connection configuration (PRAGMAs), schema initialization, schema/version verification | none | — |
| **S2** — Work item creation & durability | T008–T013 | create/get/list, cross-session durability | S1 | — |
| **S3** — Blocking & availability computation | T014–T022 | dependency edges, blocked evaluation, availability computation, status transitions | S1, S2 | **S4** — once T022 is built via direct SQLite fixture construction for claimed state (now resolved, see below) |
| **S4** — Claims, evidence & reconciliation | T023–T033, T040–T042 | atomic claim/release/override, evidence, reconciliation, dangling-blocker detection, duplicate-source detection, cycle detection | S1, S2 | **S3** |
| **S5** — Coordinator projection | T034–T037 | disposable, deterministic coordinator-facing projection | S3, S4 (convergence) | S6 |
| **S6** — Archival | T038–T039 | in-place thinning of terminal items, dependency truth preserved forever | S3, S4 (convergence) | S5, subject to explicit integration — both ultimately touch the same two implementation/test files |
| **S7** — End-to-end integration checkpoint | T043 | quickstart.md Scenarios 1–5 as one coherent pass | S2, S3, S4, S5, S6 | — (final checkpoint) |

`T040–T042` belong in S4, not in a separate "Polish" slice, because they
are tests of `reconcile()` (T027) — despite having originally landed in
Spec Kit's own Polish phase purely by phase-number convention, not by any
real dependency or file-ownership reason.

### Recommended execution waves

```
Wave 1: S1
Wave 2: S2
Wave 3: S3 ∥ S4
Wave 4: S5 ∥ S6
Wave 5: S7
```

**Available parallelism is intentionally modest: at most two concurrent
implementation units at any wave.** The task-composition analysis was
explicit about not manufacturing more parallelism than the graph actually
supports — every implementation task currently targets one of only two
files (`src/bindle/work_ledger.py`, `tests/test_work_ledger.py`), so
parallelism here is **semantic, not file-isolated**: two slices are
judged safe to run concurrently because their new functions/tests don't
overlap in meaning, not because they touch different files. Every wave
boundary (S2→{S3,S4}, {S3,S4}→{S5,S6}, {S5,S6}→S7) requires deliberate
integration — merging two agents' independent additions to the same two
files — not a conflict-free merge by construction.

### What the composition analysis found that the raw phase list didn't

- **S3 and S4 are independent siblings**, not a serialized US2→US3 pair —
  the raw task list's own Phase 3→4→5→6→7 numbering implied a
  serialization nothing in the actual dependency graph requires.
- **T040–T042 belong with T027** (`reconcile()`), not in Polish — the raw
  list separated a function's own verification from its implementation
  across a phase boundary for no dependency-driven reason.
- **S5 (projection) and S6 (archival) are a second, separate parallel
  wave**, once S3/S4 land — not visible from reading phase numbers alone,
  since the raw list places "Polish" strictly after "User Story 4."
- The analysis deliberately avoided inventing parallelism beyond two
  concurrent workers at any point — this is a conclusion, not a
  limitation the analysis failed to overcome.

**The primary agent should retain ownership of the overall implementation
and integration** — merging S3/S4 at the end of Wave 3, and S5/S6 at the
end of Wave 4, is integration work belonging to whoever is coordinating
the waves, not something either parallel worker resolves unilaterally.

These are implementation/orchestration observations for resuming this
feature, not new product requirements — nothing above adds to, narrows, or
reinterprets `spec.md`'s functional requirements or success criteria.

## Verification

- `bash scripts/check.sh` — **all checks passed** (see this plan's commit
  for the exact run this handoff was validated against).
- `tasks.md` line-format validation — all 43 task lines conform to
  `- [ ] T### [P?] [US#?] Description <file path>`.
- No source files under `src/` or `tests/` exist or were touched by this
  plan or the session that generated `tasks.md`.

## Decisions

**T022 fixture-construction ambiguity — resolved.** T022 (User Story 2's
own Independent Test: a full availability enumeration over a ledger
mixing open/unclaimed, open/claimed, blocked, done, and superseded items)
needs at least one "open/claimed" item to exist. The open question was
whether that fixture is built by calling US3's `claim()` (T023) — which
would make US2's own test suite depend on US3 landing first, destroying
the S3 ∥ S4 parallel-execution opportunity — or by inserting directly into
`work_item_claims` at the SQLite persistence boundary, which keeps US2 and
US3 independently implementable.

**Resolution**: T022 constructs its claimed-state fixture by **direct
`work_item_claims` insertion**, not via `claim()`. Rationale: T022 is
testing availability computation given a valid ledger state, not claim
acquisition — proving that the public `claim()` operation itself produces
that state correctly is squarely US3's own responsibility, already covered
by T028/T029. This is recorded in `tasks.md` at T022's own task line, in
the "Phase Dependencies" and "User Story Dependencies" sections, and in
the "Parallel Opportunities" section (distinguishing this file-level `[P]`
marker's narrower meaning from the composition-level S3 ∥ S4 parallelism
recorded here).

## Open questions

None currently blocking. The one real ambiguity the task-composition
analysis surfaced (T022) is resolved above.

## Showcase evidence

Not applicable — this is a planning/task-composition handoff with no
executable behavior to demonstrate yet. `tasks.md` itself and this file
are the artifacts.

## Next action

**Begin implementation with S1, Ledger bootstrap, T001–T007.** Do not
regenerate `spec.md` or `tasks.md`, and do not reopen the SQLite
persistence decision (`research.md`'s "Decision: storage format" and
"Decision: storage location" are settled).

After S1 and S2 are implemented, integrated, and verified, **S3 and S4
become the first candidate subagent-parallel wave** (per the "Recommended
execution waves" table above) — dispatching those agents is explicitly
**not** done by this handoff or the session that wrote it; it is the next
session's decision to make once S1/S2 are actually done.
