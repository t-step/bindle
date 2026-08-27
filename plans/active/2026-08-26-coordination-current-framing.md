# Coordination current framing

Date: 2026-08-26. Status: **active framing; execution integration not yet adopted.**

## Outcome

Keep Bindle's coordination boundary unambiguous after implementation of the durable work ledger, so future work extends the architecture that now exists rather than re-implementing superseded experiments.

## Current facts

* `specs/001-durable-work-ledger/` is implemented in `src/bindle/work_ledger.py` and verified by `tests/test_work_ledger.py`. All 43 implementation tasks are complete.
* Bindle's durable coordination state is its own repository-scoped **SQLite ledger** under the Git common directory. SQLite is the current implementation and intended persistence model for this work.
* The earlier plain per-item/file-based coordination design is **superseded and out**. Do not restore TOML-per-item records, separate claim files, tombstones, or Git/file-layout-based coordination as an alternative persistence path.
* Git remains the workspace/history/evidence substrate. Branches, worktrees, commits, and repository state may be referenced by or reconciled against the ledger, but Git/file state is not the durable coordination store.
* This SQLite database belongs to Bindle, not to Symphony.
* The ledger owns a deliberately small set of orthogonal facts: work-item status, blocking edges, claims, evidence, and source provenance. It is not a scheduler, agent loop, workflow engine, or general DAG framework.
* `WorkLedger.generate_projection()` produces a disposable, coordinator-agnostic current-state projection. The projection is derived from Bindle's ledger; coordinator storage is never authoritative for Bindle work state.
* Symphony remains a referenced external coordinator candidate. The pinned fork's shipped `tracker.kind: local` adapter uses `.symphony/local_tracker.json`, not SQLite. Bindle has no current command, config, or runtime path that invokes Symphony.
* Claude Code and Codex worker-harness work belongs on the Symphony side of the boundary. Bindle should not grow a generic agent-runner abstraction to model them.
* The durable ledger implementation has met the repository's usual working-slice evidence bar, but no `docs/DECISIONS.md` entry has yet adopted it as standing repository policy. Adoption is the next policy step, not something this plan silently assumes.

## Authoritative boundary

The intended flow is:

```
source artifact / decomposition decision
        -> Bindle SQLite work ledger
        -> disposable coordinator projection
        -> Symphony execution
        -> isolated agent workspace / Git evidence
        -> Bindle reconciliation
```

Each arrow is a seam, not an invitation to collapse the neighboring systems into one model.

In particular:

* Do **not** replace SQLite with the earlier file-based design. That persistence model is superseded.
* Do **not** build or restore a Symphony-specific SQLite tracker merely because older planning material described one. That was an exploration-era assumption and is superseded.
* Do **not** make Symphony's JSON tracker the durable Bindle work ledger. It is coordinator-owned execution state.
* Do **not** make Spec Kit `tasks.md` the runtime ledger or automatically ingest every generated task. Promotion into durable work remains an explicit decomposition/promotion decision.
* Do **not** add scheduling, retry/backoff, workspace management, or generic agent-loop machinery to Bindle. Those are coordinator responsibilities.
* Do **not** broaden the ledger into a richer lifecycle ontology, graph engine, or event-history system without new evidence and a separate decision.

## Next coordination work

1. Record the durable work ledger adoption decision in `docs/DECISIONS.md`, including the bounded-coordination-state ownership category, SQLite as the persistence model, and the explicit supersession of the earlier file-based design.
2. Re-verify the pinned Symphony fork at the revision actually targeted for integration before changing either repository. Historical adapter details are evidence, not a standing API guarantee.
3. Define the smallest Symphony-specific mapping from `ProjectedWorkItem` into the tracker surface Symphony actually exposes. Prefer an adapter/materialization seam over schema sharing.
4. Prove one end-to-end execution path using Symphony itself: create/promote a Bindle work item, project it, dispatch it through Symphony, execute in an isolated workspace with the selected worker harness, record Git/evidence, and reconcile the result back against Bindle state.
5. Only after that proof decide whether Bindle needs any CLI lifecycle surface for Symphony (`init`, launch, status, or otherwise). Do not pre-build that surface.

## The unresolved hard problem

Creating and coordinating durable rows are now separate problems. Coordination mechanics are implemented; high-quality decomposition and promotion into work items are not generalized. That boundary is intentional. Do not respond to the absence of automatic row creation by building speculative graph/decomposition machinery into the coordinator or ledger.

## Historical plan

`plans/archive/2026-08-24-symphony-coordination-exploration.md` preserves the exploration that led here, including assumptions that were later corrected in-place. It is historical evidence, not current implementation guidance. Where it conflicts with this document, this document and the current `specs/001-durable-work-ledger/` artifacts govern.

## Adoption status

This document updates framing only. It does not itself adopt Symphony, the durable work ledger, a worker harness, or any new CLI surface. Those remain separate decisions under the repository's existing adoption rules.
