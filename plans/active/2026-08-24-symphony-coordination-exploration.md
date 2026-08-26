# Symphony coordination exploration

Date: 2026-08-24. Status: **architecture settled for the exploration phase; no
implementation code written under this plan yet.** This document captures the
constraints a design review reached so a future implementation session
inherits them instead of re-deriving or drifting from them. `PLAN.md`'s Next
item #2 still governs: this remains exploration, not adoption, until a
`docs/DECISIONS.md` entry says otherwise.

## Outcome

Bindle's coordination pillar is an evaluation of the existing upstream
OpenAI Symphony reference implementation, patched with the smallest
practical modification, not a Bindle-built coordinator. The target first
vertical proof (see "Expected first vertical proof" below) is the evidence
that would justify a future adoption decision. This plan records the
settled shape of that evaluation and the architecture explicitly rejected
along the way, so a future session does not reopen the broad design
question `PLAN.md` line 14 originally left open.

## Why now

A design review this session (working from `main` and from
`feat/local-orchestration` as experimental evidence only, cross-checked
against a live clone of `openai/symphony` at the pinned commit
`8001b52e3062495a16e520e4ceaf8f9de868c4d0`, which is also upstream's
current default-branch HEAD) resolved the open questions `PLAN.md` line 14
deferred. Nothing has been implemented from that review yet. Left
undocumented, a future session picking up "evaluate Symphony-style
scheduling semantics" has no way to tell that a dependency/DAG model, a
Python orchestration package, a 9-state lifecycle, and a generic
provider/harness framework were all considered and rejected — it would be
likely to reintroduce them from the still-present `feat/local-orchestration`
branch, which contains exactly that architecture. This document exists to
prevent that.

## Scope

**Settled direction (in scope for future implementation):**

* Symphony remains the coordinator. Bindle does not implement its own
  scheduler, retry loop, workspace manager, reconciliation logic, or
  generic agent loop — Symphony's `orchestrator.ex` already owns dispatch
  ordering, concurrency, retry/backoff, and reconciliation, all driven by
  plain WORKFLOW.md config, not Bindle code.
* A repository-scoped local SQLite database replaces Linear as Symphony's
  tracker, through Symphony's own tracker-adapter seam
  (`SymphonyElixir.Tracker` behaviour) — not a new Bindle-invented
  interface.
* Claude Code becomes a first-class Symphony worker harness, added through
  the smallest available harness seam (`agent_runner.ex`'s
  `agent.worker_harness` config resolution), matching the existing
  `Codex.AppServer` contract exactly (`start_session/2`, `run_turn/4`,
  `stop_session/1`) so no orchestrator code changes.
* Codex remains supported as long as doing so stays cheap and close to
  upstream. If preserving Codex later proves to materially increase
  implementation or maintenance complexity, Claude Code may be prioritized
  and Codex support revisited — that tradeoff is not decided yet.
* One orchestration run selects one worker harness via configuration. No
  per-item or mixed Claude/Codex routing within a run.
* `bindle init` is the repository opt-in/setup boundary for Symphony
  coordination: it establishes the repository-local SQLite database and
  the Symphony configuration Symphony needs, and nothing more. It must not
  start Symphony or begin executing work.
* Symphony must be explicitly run, separately from `bindle init`, to do
  work. The expected initial operating model is a foreground process
  (e.g. a terminal/cmux pane) that stops when the process is stopped — not
  a daemon, not something `bindle init` backgrounds.
* Work items are loaded into SQLite manually for now.
* The eventual Bindle command used to launch Symphony is not yet decided
  and is deliberately not standardized by this document.

**Explicitly out of scope for this coordination work (do not reintroduce):**

* a Bindle-owned Symphony implementation, or any Python
  coordinator/scheduler standing in for one
* graph semantics, dependency/DAG modeling, or automatic decomposition
* automatic Spec Kit ingestion into SQLite — loading Spec Kit tasks/plans
  is an explicit, acknowledged gap, not this exploration's job
* mixed-provider (Claude + Codex) task assignment within one run
* additional work-item kinds, or a Bindle-specific task ontology
* a Bindle-specific lifecycle/state ontology beyond the minimum strings
  Symphony itself requires to operate (an `active_states`/`terminal_states`
  list of arbitrary strings — Symphony has no opinion on their names)
* the prior experimental branch's 9-state lifecycle
  (`backlog, ready, todo, in_progress, human_review, merging, rework, done,
  canceled`) as standing policy — legitimate as a future Bindle policy
  layer, but not carried forward by default
* a generic provider or `AgentRunner` framework
* durable run/event/history infrastructure, unless Symphony itself
  requires it (it doesn't — see Evidence)
* retrieval/QMD/Projectmem integration with coordination — retrieval is a
  separate Bindle pillar, out of scope here
* LangGraph, PlanDB, Beads, or any other orchestration framework

**Provider neutrality posture — read carefully, do not overinterpret:**
practical interoperability with both Claude Code and Codex is wanted, but
that is not permission to build a generic abstraction layer. The
preferred implementation is concrete and small: the existing upstream
Codex path stays as untouched as practical; Claude Code is added through
the smallest Symphony worker-harness seam; configuration selects Claude or
Codex for a run; no per-item worker routing; no hypothetical third-provider
architecture.

## Evidence

Gathered this session, verified against actual code rather than the prior
branch's own claims about itself:

* The prior branch's vendored patch — `tracker.ex` (+1 line, one adapter
  registry entry), `agent_runner.ex` (+29 lines, worker-harness config
  resolution, 2 call sites), `config/schema.ex` (+51 lines, additive only)
  — was independently diffed against a live upstream clone at the pinned
  commit and confirmed genuinely minimal, not inflated. `orchestrator.ex`,
  `codex/app_server.ex`, `tracker/issue.ex`, and `tracker/memory.ex` are
  byte-identical to upstream.
* Symphony's orchestrator owns 100% of dispatch ordering
  (`sort_issues_for_dispatch/1`, hardcoded priority-rank tie-break),
  concurrency (global + per-state + per-worker-host caps), retry/backoff
  (exponential, capped, in-memory), and reconciliation (every poll cycle,
  driven purely by `active_states`/`terminal_states` set membership).
  `active_states`/`terminal_states` are arbitrary WORKFLOW.md strings, not
  Elixir atoms — a SQLite-backed project reuses this surface with zero
  scheduler changes.
* `dispatchable` must be adapter-computed per upstream `SPEC.md` §11.3
  ("the generic scheduler never tries to reconstruct those checks"); the
  vendored SQLite adapter's SQL correctly has no `ORDER BY` — all ranking
  stays in the orchestrator.
* No durable runs/events/history store is required by Symphony core —
  `running`/`blocked`/`retry_attempts` are plain in-memory GenServer
  state; Ecto is used only for WORKFLOW.md config validation, with no
  `Ecto.Repo` or migrations anywhere in the vendored tree.
* A real correctness bug was found in the vendored `claude/app_server.ex`:
  `collect_result/3`'s `{:noeol, _partial}` clause discards a partial
  NDJSON chunk instead of accumulating it (unlike Codex's equivalent
  loop), which can silently drop the terminal `"type":"result"` event on
  large tool outputs. Must be fixed before this is trusted for real work,
  independent of anything else in this plan.
* The prior branch's `slice_dependencies` table, `add_dependency()`, and
  blocker-aware `dispatchable` computation (present in both `ledger.py`
  and the vendored `tracker/sqlite.ex`) are dependency/DAG modeling this
  exploration explicitly rejects. Confirmed dead weight for a single
  manually-inserted item with no blockers.
* The prior branch's `ledger.py` `eligible_slices()`/priority-rank/sort
  duplication is not required by Symphony at all (confirmed: the adapter
  does no ordering) — it existed only to power a `bindle orchestration
  queue` CLI preview column, and is exactly the kind of hand-duplicated
  logic this exploration rejects.
* Reusable pieces from `feat/local-orchestration`: the SQLite tracker
  adapter's shape (shell out to the `sqlite3` CLI with `-json`, no new
  Hex/mix dependency) and the Claude worker-harness adapter's shape
  (matching `Codex.AppServer`'s exact contract, `--session-id`/`--resume`
  turn handling, `acceptEdits` permission mode preserving hooks/
  CLAUDE.md/AGENTS.md/skills). Not reusable as architecture: its Python
  `src/bindle/orchestration/` package, its dependency model, its 9-state
  lifecycle, and its `workflow.py` prompt-injected lifecycle-transition
  assumptions built on top of that richer state model.

## Work

Not started under this plan. Future implementation work is expected to
land as its own PR(s), scoped no larger than the vertical proof below,
and should:

* patch upstream Symphony at exactly the two seams above (tracker adapter
  registry, worker-harness resolution), keeping the SQLite tracker adapter
  and Claude worker-harness adapter close to `feat/local-orchestration`'s
  versions in shape, simplified to drop dependency/eligibility logic
* fix the `{:noeol, _partial}` bug in the Claude worker harness
* establish only the SQLite database and Symphony configuration `bindle
  init` needs to hand off to Symphony — no scheduler, no Python
  orchestration package
* leave "how Symphony is actually launched" as a separate, later decision

## Expected first vertical proof

No broader than:

```
manual SQLite INSERT -> Symphony retrieves item -> Symphony creates
isolated workspace -> selected Claude Code or Codex worker executes it ->
item reaches the configured terminal state
```

Using Symphony itself directly. It must not require a new Bindle Python
orchestration subsystem.

## Verification

This change is documentation-only; no code verification applies. `bash
scripts/check.sh` was run to confirm the decision-reference consistency
check and the private-info scan pass with this plan and the `PLAN.md` edit
in place.

## Decisions

None recorded here for the architecture this plan settles. This plan does
not adopt Symphony, SQLite tracking, or a Claude worker harness as
repository policy — it only sharpens what `PLAN.md` line 14 already
marked as exploration. A `docs/DECISIONS.md` entry for *that* adoption is
still expected only after the vertical proof above is actually observed
working.

A narrower, separate decision has since landed: `docs/DECISIONS.md` D037
records only an intentional reference to the Symphony fork (canonical
repository, a pinned `development` revision) in a new `docs/SYMPHONY.md`,
with no execution, `bindle init`/`status` wiring, or work-item model of
any kind. It does not start this plan's "Work" section and does not
constitute the vertical-proof decision described above. D037 also found,
by inspecting the pinned fork revision directly, that Symphony's finished
local tracker (`tracker.kind: local`) reads and writes a plain JSON file
(`.symphony/local_tracker.json`), not SQLite — this plan's "Settled
direction" bullet above ("a repository-scoped local SQLite database
replaces Linear as Symphony's tracker") was accurate to the evidence
available on 2026-08-24 but does not match what the fork actually shipped;
a future implementation session should re-verify the tracker adapter's
real shape against the pinned revision rather than this plan's original
SQLite framing.

## Open questions

Narrow implementation facts still needing verification — not reasons to
redesign anything above:

1. Whether Symphony's workspace/runtime behavior truly requires tracker
   fields such as `branch_name` or `url` (i.e. whether `workspace.ex`
   reads them), so the SQLite schema can stay minimal rather than carrying
   fields defensively.
2. Whether Symphony orchestrator's unconditional read of
   `Config.settings!().codex.stall_timeout_ms` means a Claude-selected
   WORKFLOW.md still requires a populated `codex:` config block to pass
   validation, even when Codex is not the active harness.

Also intentionally left open, not deferred by oversight:

* The exact `bindle` command/subcommand used to launch Symphony as a
  foreground process — deliberately not standardized yet.
* Whether Codex support is kept indefinitely or deprioritized later, per
  the provider-neutrality posture above — not decided.
* How Spec Kit tasks/plans eventually reach SQLite — explicit, acknowledged
  gap, not this exploration's problem to solve.

## Showcase evidence

None — documentation-only change. The design review this plan summarizes
was conducted and verified against live upstream Symphony and the
`feat/local-orchestration` branch in this session's own tool-call history.

## Deferred: delivery-flow diagnostics

Status: **deferred, non-normative.** Recorded here only so a future session
does not re-derive it from scratch. This section does not change scope,
adopt a design, or authorize any implementation.

A future need has been identified: diagnosing *where* delivery throughput
is constrained once work is decomposed into agent-sized slices and executed
concurrently under whatever coordination model is eventually adopted.

Candidate diagnostic signals (questions of interest, not an approved
Bindle-owned telemetry model, and not a committed metric list):

* valid delivery throughput
* cycle time
* runnable vs. active concurrency
* blocked time
* first-pass correctness
* rework

None of these signals are adopted, defined precisely, or assigned an owner
by this section. In particular, this section does **not**:

* define a new Bindle lifecycle/state ontology — the ontology rejection
  above (arbitrary Symphony `active_states`/`terminal_states` strings only,
  no richer state model) still applies in full;
* introduce Bindle-owned dependency-eligibility or scheduling semantics
  that duplicate Symphony's orchestrator — the "runnable concurrency"
  signal above is a question to answer, not a mandate to build a second
  eligibility computation alongside Symphony's `dispatchable`;
* prescribe a durable event/history store — the rejection of durable
  run/event/history infrastructure above still applies; if these signals
  are ever instrumented, where and how they're recorded is unresolved, not
  assumed to be a new Bindle-owned log;
* change `SCOPE.md`, `PLAN.md`, schema, or runtime code. `SCOPE.md`
  currently lists telemetry platforms under "Bindle does not own" — that
  line is untouched by this section, and any future ownership decision
  must reconcile with it explicitly rather than by drift.

Ownership of the underlying observations is unresolved. The data these
signals would be computed from may ultimately be derivable from Symphony
itself, from its tracker/coordination state, from existing repository or
CI evidence, or from another analytics surface entirely — rather than
stored or computed by Bindle. Which of these is correct cannot be judged
usefully before real coordination state exists.

Revisit instrumentation and ownership only after the first vertical
coordination proof (see "Expected first vertical proof" above) provides
evidence about what data naturally exists as a byproduct of running
Symphony, and what is actually missing — not speculatively before that
proof lands.

**Diagnostic intent**, recorded for continuity: the eventual goal is not,
at least initially, to optimize throughput or automatically prescribe a
remedy. It is to distinguish whether constrained delivery appears
primarily attributable to:

1. work decomposition/topology,
2. scheduling or available execution capacity,
3. execution/correctness,
4. integration/rework.

This distinction — not a metric, dashboard, or scoring system — is the
actual thing worth preserving from this deferral. Everything else in this
section is disposable and expected to be re-derived once real evidence
exists.
