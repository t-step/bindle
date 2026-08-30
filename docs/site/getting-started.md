# Getting Started

This walkthrough runs the real coordination flow end to end: provision Bindle in a
disposable repository, load a Spec Kit feature's tasks into the ledger, and see
dispatchable/blocked work state and a dependency forecast — all without installing,
configuring, or running Symphony.

**Run this against a scratch repository, not a repository with real coordination
state you care about.** `bindle init` and the loader are safe to rerun, but this
walkthrough is meant for a disposable clone, not your working repository.

## Prerequisites

There is no published, installable Bindle package yet. The only currently truthful
install path is a cloned development checkout run via `uv run bindle ...`:

```sh
git clone <bindle-repository-url> <bindle-checkout>
cd <bindle-checkout>
uv run bindle --version
```

## Step 1 — Create a disposable scratch repository

`bindle init` requires a Git repository with at least one commit (a bare, commit-less
`git init` has no resolvable `HEAD` yet, and `bindle init` needs one):

```sh
mkdir -p <scratch-dir> && cd <scratch-dir>
git init
git commit --allow-empty -m "init"
```

## Step 2 — Provision Bindle, with an isolated `BINDLE_HOME`

Point `BINDLE_HOME` at a directory inside your scratch repo so this walkthrough never
touches your real Bindle configuration:

```sh
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle init
```

Expected output (abbreviated — the guardrail-layer lines will vary by environment):

```
== Bindle guardrails for <scratch-dir> ==
== Preflight ==
== Git hook layer ==
  ✓ installed dispatcher + 19 standard hook symlinks at <scratch-dir>/.git/bindle-hooks
  ✓ set repo-local core.hooksPath to <scratch-dir>/.git/bindle-hooks for <scratch-dir>
...
Initialized Bindle.
SQLite work ledger: ready
Symphony projection: ready
```

The last two lines are the ones that matter here: `bindle init` unconditionally
provisions the durable coordination ledger (`.bindle-work/ledger.sqlite3`) and its
Symphony-readable projection. Nothing about this step involves Symphony itself.

## Step 3 — Load a Spec Kit feature's tasks into the ledger

This repository's own `specs/005-work-state-visibility/` is a real, complete Spec Kit
feature already in this repository — a representative worked example, not an invented
CLI surface:

```sh
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> \
  bindle work load-speckit <bindle-checkout>/specs/005-work-state-visibility
```

Expected output:

```
created: 26
  speckit:005-work-state-visibility:T001
  speckit:005-work-state-visibility:T002
  ...
  speckit:005-work-state-visibility:T032
resynced: 0
```

Every task from that feature's `tasks.md` is now a work item in your scratch
repository's ledger, with dependency edges intact.

## Step 4 — See dispatchable and blocked work state

```sh
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work status
```

Expected output (abbreviated):

```
tasks:
  speckit:005-work-state-visibility:T001  open  dispatchable
  speckit:005-work-state-visibility:T005  open  dispatchable
  speckit:005-work-state-visibility:T006  open  blocked on: speckit:005-work-state-visibility:T005
  speckit:005-work-state-visibility:T009  open  blocked on: speckit:005-work-state-visibility:T008
  ...
milestones:
```

Tasks with no unmet dependency are `dispatchable`; tasks waiting on another task show
exactly what they're `blocked on`. This is real, ledger-derived state — no Symphony
process was involved in producing it.

The same snapshot is available as JSON:

```sh
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work status --json
```

```json
{
  "tasks": [
    {
      "id": "speckit:005-work-state-visibility:T001",
      "title": "...",
      "status": "open",
      "claim": null,
      "dispatchable": true,
      "blocking_ids": []
    },
    {
      "id": "speckit:005-work-state-visibility:T006",
      "title": "...",
      "status": "open",
      "claim": null,
      "dispatchable": false,
      "blocking_ids": ["speckit:005-work-state-visibility:T005"]
    }
  ],
  "milestones": []
}
```

## Step 5 — See the dependency forecast

```sh
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work forecast
```

Expected output (abbreviated):

```
dispatchable now: speckit:005-work-state-visibility:T001, ..., speckit:005-work-state-visibility:T032
blocked:
  speckit:005-work-state-visibility:T006  blocked on: speckit:005-work-state-visibility:T005
  speckit:005-work-state-visibility:T018  blocked on: speckit:005-work-state-visibility:T004, speckit:005-work-state-visibility:T008  (convergence point)
  ...
if speckit:005-work-state-visibility:T005 resolves:
  unblocked-next: speckit:005-work-state-visibility:T006, speckit:005-work-state-visibility:T015
  dispatchable-next: speckit:005-work-state-visibility:T006, speckit:005-work-state-visibility:T015
...
milestone review frontier:
```

`forecast` shows the dependency frontier: which currently-blocked tasks would become
dispatchable if a given blocker resolved, and which blocked tasks are "convergence
points" waiting on more than one thing.

## What you just did — and didn't do

You provisioned Bindle's durable coordination ledger, loaded real Spec Kit task
data into it, and observed dispatchable/blocked state and a dependency forecast —
entirely through the `bindle` CLI against a local SQLite ledger. At no point did
this require installing, configuring, or starting Symphony; Symphony is a separate,
independently-run external coordinator (see [Symphony](../SYMPHONY.md)) that can
later read this same ledger's projection, not a prerequisite for using it.

A few CLI subcommands you may see listed in `bindle --help` — `bindle list`,
`bindle update`, `bindle upgrade`, `bindle doctor` — are interface-only placeholders
today and are not exercised by this walkthrough.

To understand what Bindle durably owns, what it doesn't, and where human judgment
stays in the loop, read [How Bindle Works](how-bindle-works.md) next.
