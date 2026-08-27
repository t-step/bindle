# SYMPHONY

## What this document is

Symphony is a candidate external work coordinator for Bindle's coordination
pillar (PLAN.md, "Next" item 3). This document is the intentional,
maintained reference to it: which repository is canonical, which revision
Bindle's own planning currently targets, and what Symphony itself requires
before it can run. It is not an integration guide, not a `bindle` command
reference, and not an architecture decision — see "Non-scope" below and
`docs/DECISIONS.md` D037 for why this document exists in this shape.

Symphony is referenced, never vendored. Bindle does not own coding-agent
execution or subagent orchestration (`docs/SCOPE.md`, "Bindle does not
own"); Symphony remains an externally-owned tool Bindle may point at
through a supported interface, per D014 (replaceability — no parsing or
embedding of another tool's private store or source).

## Canonical repository

* Fork (this project's own): `git@github.com:t-step/symphony.git`
  (`t-step/symphony`). This is the repository a future Bindle integration
  reads from.
* Upstream: `https://github.com/openai/symphony` (`openai/symphony`,
  read-only from the fork — the fork's own `upstream` remote has push
  disabled). Symphony's own spec lives at `SPEC.md` in this repository.
* Branch model, observed on the fork: `main` mirrors upstream
  `openai/symphony`'s own `main`. `development` carries the fork's
  additive work — a local JSON work tracker and a Claude Code worker
  harness, both added through Symphony's own extension seams (tracker
  adapter registry, `agent_execution.kind`) rather than by forking its
  orchestrator. `development` is the branch a future Bindle integration
  targets, not `main`.

Symphony is not cloned into this repository (no submodule, subtree, or
vendored copy) and is not a declared package dependency of Bindle. It is
expected as an independently managed sibling checkout the operator builds
and runs themselves, exactly like Claude Code and Codex are Native tools
Bindle does not vendor (`docs/TOOLCHAIN.md`).

## Pinned reference

Bindle's own planning currently targets:

* Branch: `development`
* Commit: `a9d577518b0354f1176ab9750a51d2d4250a3f9b`
* Nearest tag: `v0.0.2-42-ga9d5775` (42 commits past the fork's last
  tagged revision, `v0.0.2`; `development` has no tag of its own yet)

Bumped 2026-08-27 from the prior pin (`099535b`, `v0.0.2-40-g099535b`) by
this repository's own reconciliation pass, per D040: the two intervening
commits (`c9a657d`, `a9d5775`) are both spec-only — Symphony's own commit
messages state "authorizes zero source code changes" for both, and this
was independently verified against `git show --stat` for each. They write
down, in `specs/002-bindle-integration/`, the projection/write-surface
assumptions this reconciliation pass depends on being current, and add
FR-017 — the specification that `dispatchable` MUST be a start/admission
gate only, never a continuation/preemption gate. **FR-017 is a
specification, not a fix**: Symphony's runtime (`orchestrator.ex`,
`agent_runner.ex`) still violates it today (see D040's "Known,
confirmed-real gap" bullet); correcting the runtime is explicitly deferred
by Symphony's own spec to a subsequent implementation feature, not
performed by these two commits or by this pin bump.

This pin is deliberate, not a moving branch tip: bump it here, on purpose,
when a future implementation session adopts a newer revision. Do not treat
"whatever `development` currently points to" as the reference — re-read
this pin, then verify it against the fork before relying on it, since
Symphony's own repository is out of Bindle's control and may have moved on.

## What Symphony requires before first execution

Observed directly in the fork's own `elixir/README.md` and
`elixir/AGENTS.md` this session — none of this is provided, installed, or
managed by Bindle:

* A `mise`-managed Erlang/Elixir toolchain (`erlang 28`,
  `elixir 1.19.5-otp-28`; see `elixir/mise.toml`).
* `mix setup` and `mix build` (or a downloaded Burrito release binary for
  a tagged version, if one exists for the target platform).
* A `WORKFLOW.md` configuration file (YAML front matter — tracker,
  workspace, hooks, agent, and `codex:`/`claude_code:` blocks — plus a
  Markdown body used as the coding-agent's session prompt). Symphony
  defaults to `./WORKFLOW.md` and never invents one.
* A configured tracker. Symphony ships adapters for Linear, GitHub Issues,
  Jira Cloud, Asana, and GitLab (each needing its own credentials), plus a
  `tracker.kind: local` adapter that reads/writes a plain JSON file
  (`.symphony/local_tracker.json` by default — no SQLite, no database, no
  network access) after an explicit
  `./bin/symphony local-tracker init` step. Symphony never creates this
  file implicitly.
* `codex` and/or the `claude` CLI reachable at runtime, and `git`, on the
  machine that runs Symphony.
* Symphony runs as a foreground process the operator starts and stops
  directly (`./bin/symphony ./WORKFLOW.md`); it is not a daemon and does
  not background itself.

## Scheduling boundary: only tasks are dispatchable

Bindle's durable work ledger (`specs/001-durable-work-ledger/`, extended
by `specs/002-milestone-task-work-items/`; adopted in `docs/DECISIONS.md`
D038) distinguishes two work-item types: `task` (an execution unit) and
`milestone` (a human acceptance unit grouping one or more child tasks).
**Only `task` items are ever candidates for Symphony dispatch.** A
`milestone` is never translated into, or represented as, a Symphony
tracker entry — Bindle's own coordinator-facing projection
(`WorkLedger.generate_projection()`) filters to `type = 'task'` by
construction, so a milestone is structurally incapable of reaching
Symphony's tracker regardless of its own status (`open`, `review`,
`accepted`, `superseded`).

This means Symphony itself needs no milestone concept, no review-state
vocabulary, and no awareness of task-to-milestone attribution at all — it
only ever sees ordinary tasks, exactly as if milestones did not exist.
Bindle resolves blocking, claim, and milestone-attribution facts entirely
on its own side of the seam before a task is ever projected; Symphony is
asked only "is this task eligible, what is it, what execution metadata
do I need" (`specs/001-durable-work-ledger/contracts/`, extended by
`specs/002-milestone-task-work-items/contracts/coordinator-projection-v2.md`).
Whether a milestone itself is *ready for review* is a separate, mechanically
derived fact (`is_review_ready()`) computed from its children's own
resolved status and evidence; whether it is actually *accepted* remains a
human judgment recorded as an explicit transition, never inferred or
automated from readiness alone (D038).

**Task granularity is the schedulable unit; there is no task-under-task
nesting (D040).** `parent_id` on a task can only ever name a milestone
(schema `CHECK`, `specs/002-milestone-task-work-items/`) — never another
task — and it records human-review attribution only, never execution
decomposition. A task attached to a milestone is projected and computed
`dispatchable` identically to a parentless one; `generate_external_projection()`
carries no `parent_id` filter (`specs/003-symphony-task-integration/`). The
Spec Kit loader (`src/bindle/speckit_loader.py`) never sets `parent_id` at
all — every loaded task is `parent_id = NULL`. Concretely: one Spec Kit
`T###` task line is one Bindle `type = 'task'` row is one projected,
independently schedulable Symphony unit — the same granularity a Spec Kit
`tasks.md` already uses for its own bounded, dependency-tracked,
independently verifiable implementation steps. A primary coding-agent
session that claims a task may decompose or use subagents internally to
complete it; that internal decomposition is deliberately never written to
Bindle's ledger and has no representation here — Bindle's coordination
state stops at the task boundary, consistent with owning coordination
state rather than execution internals (`docs/SCOPE.md`, "Bindle does not
own"). See D040 for why no `parent_id`-based filter, new work-item type,
or loader change was needed to express this.

## Published projection and write surface

`specs/003-symphony-task-integration/` (adopted in `docs/DECISIONS.md`)
gives Bindle a narrow, explicit path from a settled Spec Kit task
decomposition to a form an external coordinator can actually read and
act on, without adopting Symphony itself or any of its tracker formats:

* An explicit, maintainer-invoked loader (`src/bindle/speckit_loader.py`)
  reads one Spec Kit feature directory's `tasks.md` and creates canonical
  `type = 'task'` work items from it, idempotently — never automatically,
  never as a side effect of editing `tasks.md`.
* A published, versioned, read-only SQLite export
  (`src/bindle/symphony_projection.py`'s `publish()`,
  `contracts/symphony-projection-v1.md` in that feature's spec directory)
  — a physically separate artifact from Bindle's own internal ledger
  file, containing task-only rows with a direct status and a derived
  `dispatchable` fact. This is the "supported interface" referenced
  above and in `docs/PHILOSOPHY.md`'s D014: an external reader depends on
  this file and its documented contract, never on Bindle's internal
  schema.
* A narrow write surface (`claim_task`/`release_task`/`complete_task`,
  and the `bindle work claim`/`release`/`done` CLI equivalents) built
  directly on the ledger's own existing atomic claim/release/mark-done
  primitives — no new arbitration mechanism, no raw SQL exposed as the
  contract (`contracts/task-write-surface.md`).

This remains a one-directional, disposable projection and a fixed set of
narrow write operations — not a Symphony-specific tracker adapter, and
not a translation into Symphony's own `local_tracker.json` shape. See
"Non-scope" below for what specifically remains out of scope even with
this in place.

## Non-scope

This document establishes a reference only. Even with the published
projection and write surface above, Bindle still does not:

* install, build, configure, start, stop, or supervise Symphony;
* build a Symphony-specific tracker adapter — that adapter, if built,
  remains future work, deferred until a first end-to-end integration is
  actually attempted, and would read the published projection and map
  its rows onto `Tracker.Issue` directly, never translate into Symphony's
  own separate, standalone local tracker format
  (`.symphony/local_tracker.json`), which is unrelated;
* make its published SQLite projection a second copy of, or a
  replacement for, Symphony's own tracker/storage — the projection is a
  disposable, regenerable read model derived from Bindle's own canonical
  ledger (`docs/DECISIONS.md` D038, `specs/001-durable-work-ledger/`,
  `specs/002-milestone-task-work-items/`), never a durable store Symphony
  or any other consumer may treat as authoritative;
* standardize a `bindle` command to launch or manage Symphony.

`plans/active/2026-08-24-symphony-coordination-exploration.md` records the
architecture direction a future implementation is expected to follow once
that work actually starts (Symphony remains the coordinator; Bindle adds
only the smallest seams Symphony already exposes). This document does not
change or narrow that plan — it only gives that future work, and any
other future reference to Symphony, a fixed, intentional starting point
instead of an assumed or rediscovered one.
