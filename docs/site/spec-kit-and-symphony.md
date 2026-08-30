# Spec Kit & Symphony

This page is the practical, end-to-end answer to one question: **how do Spec
Kit, Bindle, and Symphony fit together, and how do I actually use them?** It
assumes you've either read [Getting Started](getting-started.md) or are
about to — this page goes one step further by showing the full loop,
including the optional Symphony branch, without repeating the architecture
explanation already in [How Bindle Works](how-bindle-works.md).

## Overview

* **Spec Kit defines work.** A feature moves through its own
  specification/planning process and ends in a `tasks.md` with one
  dependency-tracked, independently verifiable `T###` line per unit of work.
* **Bindle coordinates work.** Bindle imports that decomposition into its
  durable, repository-local coordination ledger, computes which tasks are
  dispatchable right now, and tracks claims, status, and evidence pointers.
* **Symphony optionally coordinates execution.** Symphony is an
  independently-run, independently-owned external coordinator. It reads
  Bindle's published coordination surface and can dispatch a coding agent
  against one dispatchable task at a time — but nothing about using Bindle
  requires it.
* **Claude Code or Codex performs the actual implementation work**, whether
  it was picked up manually or dispatched by Symphony.
* **Git/GitHub owns the resulting commits, branches, pull requests, and
  history.** Bindle never copies or re-stores them.
* **Bindle records pointers to that evidence**, and computes whether a
  milestone's children are all resolved and evidenced — a mechanical fact
  called *review-readiness*.
* **A human makes the actual accept/decline decision.** Review-readiness is
  computed; acceptance is not — it is never inferred from readiness alone.

## How it fits together

![Diagram: Spec Kit's tasks.md flows into Bindle's coordination ledger (Bindle-owned). From there, work forks into two alternative execution paths — a manual path, where Bindle identifies dispatchable work and a human or coding session selects and claims a task directly, and an optional Symphony path, where Bindle publishes a dispatchable coordination surface for Symphony to read and dispatch from. Both paths converge on Claude Code or Codex performing the work, which becomes Git/GitHub evidence (commits, branches, pull requests). An evidence pointer is recorded back into Bindle's coordination ledger (Bindle-owned), which computes mechanical milestone review-readiness, ending in an explicit human accept/decline decision that is never automated from readiness alone.](../assets/spec-kit-bindle-symphony.svg)

Notice the fork in the middle: **the manual path and the Symphony path are
equally valid ways to execute dispatchable work**, not a primary path with a
fallback. Bindle never starts, supervises, or otherwise owns Symphony —
Symphony is external and optional at every point in this diagram.

## Step 1 — Initialize Bindle

```sh
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle init
```

This unconditionally provisions two things a fresh repository needs before
any coordination work can happen: the durable work ledger
(`.bindle-work/ledger.sqlite3`) and its read-only, Symphony-readable
projection (`.bindle-work/symphony-projection.sqlite3`) — both empty until
you load real work into them. See [Getting Started](getting-started.md) for
the full, disposable-repository walkthrough of this step, including what
the guardrail-layer output looks like.

## Step 2 — Define work with Spec Kit

A feature's specification/planning flow (spec → plan → tasks) is
[Spec Kit](https://github.com/github/spec-kit)'s own process, not
Bindle's — this page doesn't re-document it. What matters for Bindle is only
the artifact Spec Kit produces at the end: a feature directory's
`tasks.md`, with one dependency-tracked, independently verifiable `T###`
line per implementation step (this repository's own
`specs/005-work-state-visibility/tasks.md` is a real, worked example). That
file is the one thing Step 3 reads.

## Step 3 — Load the tasks into Bindle

```sh
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> \
  bindle work load-speckit <bindle-checkout>/specs/005-work-state-visibility
```

```
created: 26
  speckit:005-work-state-visibility:T001
  speckit:005-work-state-visibility:T002
  ...
resynced: 0
```

Loading is explicit and idempotent, never automatic — nothing runs this on
your behalf when you edit `tasks.md`. Every Spec Kit `T###` line becomes
exactly one Bindle `task` work item, 1:1, with its dependency edges intact
(`speckit:{feature-dir}:{task-id}` is the stable id). Re-running the same
load resyncs title/description on an already-loaded id; it never touches
status, claims, or evidence.

## Step 4 — Inspect available work

```sh
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work status
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work forecast
```

`bindle work status` reports, per task, whether it's **dispatchable** (open,
unclaimed, and every dependency resolved) or **blocked on** specific other
task ids — no separate vocabulary beyond that. `bindle work forecast` adds
the dependency frontier: which blocked tasks would become dispatchable next
if a given blocker resolved, and which are "convergence points" waiting on
more than one thing. Neither command requires Symphony, or anything beyond
a local ledger, to produce real output — see
[Getting Started](getting-started.md) for full sample output of both.

## Step 5 — Choose how work executes

This is the fork in the diagram above. Both options start from the same
dispatchable-task state Step 4 just showed you.

### Option A — Work manually

A human, or a coding-agent session working directly, claims a dispatchable
task, does the work, and marks it done — all through the ledger's own
atomic primitives:

```sh
bindle work claim  speckit:005-work-state-visibility:T001 --owner alice --worktree /path/to/worktree --branch feature/T001
bindle work status                                          # confirm the claim
bindle work done   speckit:005-work-state-visibility:T001
bindle work release speckit:005-work-state-visibility:T001 --owner alice   # only if you need to give it up unfinished
```

`claim`/`release`/`done` are silent on success (exit `0`, no stdout) —
`bindle work status` is how you confirm the claim or completion actually
took. This path needs nothing beyond the `bindle` CLI and a local ledger;
it's what [Getting Started](getting-started.md) already demonstrates without
ever mentioning Symphony.

### Option B — Use Symphony

Symphony is a separate program you build, configure, and run yourself —
Bindle only ever publishes a read-only file for it to read and calls
through a narrow claim/release/done write surface it already exposes to
anyone.

1. **Publish Bindle's Symphony-readable projection.** `bindle init`
   provisions this once, but it does **not** stay in sync automatically —
   after `load-speckit`, or any other change you want Symphony to see,
   regenerate it explicitly:

   ```sh
   bindle work publish
   ```

2. **Configure Symphony to read it.** This is Symphony-owned configuration,
   not a Bindle command. Symphony's own fork (`t-step/symphony`,
   `development` branch — the canonical reference is
   [docs/SYMPHONY.md](../SYMPHONY.md)) ships a `bindle`-backed tracker
   adapter, enabled in Symphony's own `WORKFLOW.md`/tracker configuration:

   ```toml
   [tracker]
   kind = "bindle"

   [tracker.provider]
   # repo_path defaults to the repository containing this WORKFLOW.md;
   # override only if the Bindle repository differs.
   # repo_path = "/absolute/path/to/the/bindle-managed-repo"
   ```

   (Verified directly against the adapter's own quickstart,
   `specs/003-bindle-tracker-adapter/quickstart.md` on the Symphony fork's
   `development` branch — this shape belongs to Symphony, and may move
   independently of this page.)

3. **Start Symphony.** Symphony runs as a foreground process the operator
   starts and stops directly (`./bin/symphony ./WORKFLOW.md`) — it is not a
   daemon, and Bindle has no command that starts, stops, or supervises it.
   Symphony's own build/runtime prerequisites (a `mise`-managed
   Erlang/Elixir toolchain, `codex`/`claude` on `PATH`, etc.) are recorded
   in [docs/SYMPHONY.md](../SYMPHONY.md), not here.

4. **What Symphony does with dispatchable tasks.** On each poll, Symphony's
   Bindle tracker adapter reads the published projection, and for a task it
   decides to dispatch, calls `bindle work claim <id> --owner <symphony-owner-id>`
   (no `--worktree`/`--branch` — those stay empty for a Symphony-claimed
   task) before spawning Claude Code or Codex against it. Symphony's
   `dispatchable`-gated decision only ever applies to *fresh* admission —
   once claimed, a task already running is never re-checked against
   `dispatchable` and interrupted mid-flight.

5. **How claims and completion return through Bindle.** When the
   coding-agent session Symphony spawned finishes the task, Symphony calls
   `bindle work done <id>` followed automatically by `bindle work publish`,
   so the projection reflects the new state without a manual step. If
   Symphony gives up on a task (a crash, a terminal failure, or startup
   reconciliation after a restart), it calls
   `bindle work release <id> --owner <symphony-owner-id>` — the same
   primitive Option A uses by hand.

This proof (adapter reading the projection, claiming, running, completing,
releasing on crash) has been independently exercised end to end against a
real Bindle repository — see `docs/DECISIONS.md` D041 — but it is entirely
Symphony-repository work; nothing here changes what `bindle` itself does.

## Step 6 — Evidence and milestone review

The intended chain is:

```
implementation → Git/GitHub evidence → Bindle evidence pointer
  → mechanical milestone readiness → explicit human accept/decline
```

`bindle milestone review <id>` shows a milestone's status, computed
readiness (or the specific reason it isn't ready yet), its current claim,
and every child task's recorded evidence pointers:

```
milestone <id>: open, not ready (task <child-id> has no recorded evidence)
  <child-id>  done  evidence: none  blocked: no
```

`bindle milestone list` enumerates milestones (`--status`, `--ready-only`);
`bindle milestone enter-review`/`claim`/`release` manage the review claim
itself; `bindle milestone accept`/`decline` record the explicit,
human-invoked decision — optionally with `--evidence <locator> --note
<text>`, a rationale pointer (e.g. a `docs/DECISIONS.md` anchor) recorded
against the milestone, separately from the decision itself.

**A real gap, stated plainly rather than papered over:** everything above
this paragraph is a documented, verified `bindle` CLI command. Two pieces
of what "readiness" actually depends on are not, today:

* There is no `bindle work` command that attaches an evidence pointer
  (branch, commit, pull request) to a *task*. `WorkLedger.add_evidence()`
  exists and is exercised in this repository's own test suite, but nothing
  in the current CLI surface calls it for a task — only
  `bindle milestone accept`/`decline --evidence` records a pointer, and
  only against the milestone itself, as a rationale locator.
* There is no `bindle` command that creates a milestone work item at all.
  Milestones are created only through direct library use
  (`WorkLedger.create_work_item(type="milestone", ...)`); the Spec Kit
  loader never creates one, since Spec Kit's own task lines have no
  milestone concept.

In other words: `bindle milestone review`/`list`/`enter-review`/`claim`/
`release`/`accept`/`decline` are real and correct for milestones that
already exist in the ledger with evidenced children — but reaching that
state today requires direct library access this page won't invent a
newcomer command for. If you hit this, treat it as the honest current
boundary of the CLI surface, not a missing step in this walkthrough.

## Ownership at a glance

| Concern | Owner |
| --- | --- |
| Specification / task decomposition | Spec Kit |
| Durable coordination state (status, blocking, claims, evidence pointers) | Bindle |
| Dispatch / execution coordination, when Symphony is used | Symphony |
| Code execution | Claude Code / Codex |
| Commits, branches, pull requests, history | Git / GitHub |
| Evidence pointers and mechanical readiness | Bindle |
| Semantic milestone acceptance | A human |

## Go deeper

* [Getting Started](getting-started.md) — the smallest, Symphony-free
  newcomer path, with full sample output for every command above.
* [How Bindle Works](how-bindle-works.md) — architecture, ownership
  semantics, and why the system is shaped this way.
* [Symphony reference](../SYMPHONY.md) — the canonical fork, pinned
  revision, and Symphony's own bootstrap requirements.
* [Data Ownership](../DATA-OWNERSHIP.md) — the full routing table for
  what's durable, what's derived, and where each kind of information goes.
* [Scope](../SCOPE.md) — what Bindle owns, what it may later own, and what
  it deliberately does not.
