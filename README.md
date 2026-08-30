# README

A small project about making good tools work well together.

Why “Bindle”?

A bindle is a small bundle carried from place to place. It isn’t everything you own. It’s the few things worth bringing with you.

## Overview

Modern software development has no shortage of excellent tools. Git remembers history. Obsidian captures ideas. Claude Code and Codex are becoming capable engineering partners. Context7, Playwright, Hugging Face, and countless other projects each solve a very specific problem well.

The interesting work happens somewhere in the middle. Bindle is an experiment in reducing the friction between them without replacing them. The goal isn’t to build another platform. It’s to build as little as possible while making the existing workshop feel more connected.

Concretely, Bindle is a stateless toolchain bridge with respect to your history, knowledge, and transcripts. Each tool in the workshop owns its own domain — Git owns history, the harnesses own transcripts, the vault owns knowledge — and Bindle helps context and evidence cross the seams between them: it calls supported interfaces, collects deterministic facts, records evidence pointers other systems can embed, and holds pointers that the owning systems resolve. It keeps no database of your history, notes, or transcripts. Bindle does durably own one thing of its own: a small, repository-local coordination ledger — work-item status, blocking, claims, and evidence pointers (docs/DECISIONS.md D038) — tracking which specified work is currently schedulable; this is the state behind the `bindle work` and `bindle milestone` commands below. If a better provider appears for any other responsibility, the provider gets replaced; Bindle doesn’t get rewritten. For the full newcomer picture — what Bindle owns, what it doesn't, and how a piece of work moves from specification to accepted evidence — see [How Bindle Works](docs/site/how-bindle-works.md); the underlying architecture rules and the admission test for new features live in [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md), with data ownership and routing in [docs/DATA-OWNERSHIP.md](docs/DATA-OWNERSHIP.md).

## Principles

Inherit first. Extend second. Replace deliberately. Invent last.

A few concepts guide the project.

* Prefer existing tools over custom implementations.
* Keep repository conventions authoritative.
* Make useful things explicit before making them automated.
* Build only after a pattern appears more than once.

## CLI

Bindle has a minimal, provider-neutral CLI. Run it in development with `uv run`:

```sh
uv run bindle --version
uv run bindle repo info
uv run bindle repo info --json
```

* `bindle --version` — deterministic package version.
* `bindle repo info` — repository/execution/code-state identity (docs/WORKTREES.md): repository root, current worktree root, Git directory, Git common directory, current branch (when attached), and HEAD SHA. Add `--json` for machine-readable output.
* `bindle branch <name>` — creates a new feature branch off freshly-fetched `origin/main` in its own linked Git worktree, following the development-isolation model in AGENTS.md and docs/WORKTREES.md. `main` itself is left untouched as the clean baseline. Refuses to reuse an existing branch name or worktree path, and refuses to fall back to a stale local `main` if the fetch fails.

The CLI stays intentionally small and provider-neutral. It is not an execution/orchestration engine — it never runs a coding agent, a build, or a test itself, and dispatch/execution stay with an external harness such as Symphony (see [How Bindle Works](docs/site/how-bindle-works.md), AGENTS.md, docs/SCOPE.md). What it does durably do is track dependency-ordered coordination state and expose which work is currently schedulable.

### Work and milestone coordination

`bindle work` loads a Spec Kit feature's `tasks.md` into the durable, repository-local coordination ledger and reports which tasks are currently schedulable; `bindle milestone` is the human-facing review/accept/decline surface over that same ledger. The commands below are illustrative CLI syntax — see [Getting Started](docs/site/getting-started.md) for the safe, isolated-`BINDLE_HOME` version to actually run:

```sh
uv run bindle work load-speckit specs/005-work-state-visibility
uv run bindle work status
uv run bindle work status --json
uv run bindle work forecast
uv run bindle milestone review <milestone-id>
```

* `bindle work load-speckit <feature-dir>` — loads one Spec Kit feature's `tasks.md` into the ledger.
* `bindle work status` (`--json` for the stable machine-readable read model, `--watch` for continuous refresh) — a snapshot of every task's and milestone's dispatchable/blocked/claim state.
* `bindle work forecast` — the dependency frontier: what's dispatchable now, and what would become eligible next if a given blocker resolved.
* `bindle work claim` / `release` / `done` — claim, release, or complete a task through the ledger's own atomic primitives.
* `bindle work publish` — regenerate the read-only, versioned Symphony-facing projection.
* `bindle milestone review` / `list` / `enter-review` / `claim` / `release` — inspect and manage milestone review state.
* `bindle milestone accept` / `decline` — the explicit, human-invoked decision on a milestone in review; never inferred from readiness alone.

See [Getting Started](docs/site/getting-started.md) for the full, execution-verified walkthrough, and [How Bindle Works](docs/site/how-bindle-works.md) for what this ledger owns versus what it hands off to an execution harness.

### Lifecycle commands

`bindle --help` advertises the intended lifecycle command surface —
`init`, `remove`, `migrate-legacy-global`, `list`, `status`, `update`,
`upgrade`, and `doctor`. Some of these are real today; the rest are
interface-only placeholders ahead of later slices:

* **Real today**: `bindle --version`, `bindle repo info`, `bindle init`
  (including `--projectmem`), `bindle remove`, `bindle status`, `bindle
  migrate-legacy-global`.
* **Still interface-only** (stable `--help` text, but running one directly
  prints `bindle <command>: not implemented yet` and exits non-zero):
  `bindle list`, `bindle update`, `bindle upgrade`, `bindle doctor`.

`bindle init`/`bindle remove` manage the repo-local guardrail capability —
a Git hook layer (protected `main`, hook composition, installed via
repo-local `core.hooksPath`) and a Claude Code PreToolUse guard plus
`permissions.deny` hardening (installed into the target repository's own
`.claude/settings.local.json`) — plus, with `bindle init --projectmem`,
Projectmem: `--projectmem` ensures Projectmem is initialized for the
repository through its own native `pjm init` CLI, narrowed to core
repository-local working-memory setup while suppressing unrelated
cross-project, daemon, provider-specific, history-backfill, MCP, and
repository-analysis conveniences. Its normal capture hooks are then
installed via Projectmem's own `pjm hooks install`, targeted at the
repository's shared Git common directory rather than a linked worktree's
own `.git` (a file there, not a directory) — so hooks land correctly and
compose with Bindle's `core.hooksPath` dispatcher whether `bindle init
--projectmem` runs from the main checkout or a linked worktree (never
invoked for a repository where Projectmem is already installed, and
refused outright — before guardrails mutate anything — over ambiguous
partial/conflicting `.projectmem/` state or a missing `pjm` executable;
docs/DECISIONS.md D033). `bindle remove` never touches `.projectmem/` —
Projectmem is provider-owned working memory Bindle has no ownership record
proving it may destroy, so it survives `bindle remove` regardless of how it
got there. Bindle is not yet a general Symphony/skill-pack composition
command; that's future work. `bindle init` is the explicit opt-in
boundary — a repository becomes Bindle-managed by running it there — and
`bindle remove` reverses the guardrail layer, scoped to that one repository
only. Both refuse to run (rather than silently migrating or removing it) if
a recognized legacy, pre-repo-local, **machine-global** Bindle guardrail
install is still present; `bindle migrate-legacy-global` is the explicit,
repo-independent command that clears that legacy state, and only that.
`bindle status` reports read-only Git guardrail, Claude guardrail, and
Projectmem adoption state for the current repository — it never installs,
repairs, or otherwise mutates any of the three.

The repository is the primary unit of Bindle management, and most
lifecycle commands target the current repository rather than the whole
machine:

* Global/machine-level: `bindle list` (inventory of repositories that have opted into Bindle), `bindle update` (refresh Bindle's own component/catalog knowledge — never mutates a managed repository), and `bindle migrate-legacy-global` (remove a recognized legacy machine-global guardrail install — never touches an unrelated global value).
* Repository-targeted (current repository by default): `bindle init`, `bindle remove`, `bindle status`, `bindle upgrade` (upgrade this repository's installed components), `bindle doctor`, and `bindle repo info`.

## Current workshop

Today Bindle assumes a fairly standard engineering toolkit — coding harnesses, a knowledge vault, source control, and a handful of domain-specific tools spanning scientific computing and game development.

These aren’t dependencies so much as assumptions. Bindle should adapt to them rather than competing with them. The full, current toolchain — and why each tool is there — lives in [docs/TOOLCHAIN.md](docs/TOOLCHAIN.md); this file doesn't duplicate that list.

## Current focus

The repository-local coordination ledger and its `bindle work`/`bindle milestone` CLI surface (above) are real and implemented, not planned. Beyond that ledger, the project is intentionally still small: before writing a memory system, graph database, or general orchestration framework, it is defining:

* the toolchain
* shared conventions
* portable skills
* MCP recommendations by task
* project boundaries

What Bindle owns — and what it refuses to own — is written down in [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md) and [docs/SCOPE.md](docs/SCOPE.md).

## Non-goals

Bindle is not trying to become:

* another coding agent
* another project manager
* another note-taking application
* another documentation system
* another graph database
* another memory system, context database, or retrieval engine
* the canonical owner of notes, transcripts, session records, or user knowledge

Excellent tools already exist in each of those spaces.

The measure of Bindle is not how many responsibilities it acquires, but how many responsibilities it can confidently decline because another tool already owns them.
