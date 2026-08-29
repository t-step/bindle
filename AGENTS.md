AGENTS

Bindle Working Instructions

Repository purpose

Bindle is a stateless toolchain bridge. It moves useful context and evidence between tools that already own their domains; it is not itself a store of user history (docs/PHILOSOPHY.md, D014–D016).

Claude Code and Codex remain the execution harnesses.

Bindle may provide:

* toolchain manifests, doctor checks, and drift diagnosis
* deterministic evidence pointers recorded against Git/GitHub state (docs/DECISIONS.md D046)
* pointers and provenance links between provider-owned records
* lightweight adapters, hooks, templates, and commands at tool seams
* bounded resume-context assembly from provider-owned records
* selective projection into surfaces maintained by owning systems

Bindle does not replace execution harnesses, Git/GitHub, Obsidian, project management, documentation lookup, code intelligence, security or scientific tooling, graph databases, or generic agent loops.

Current phase

The workshop is established. Manifests, doctor checks, the decision log, and toolchain policy are in place. Implementation of the first vertical slice has not started.

Use PLAN.md for current orientation and docs/SCOPE.md for scope and milestone sequencing.

Do not implement a memory platform, graph system, background daemon, orchestration framework, or generic agent harness without an approved plan.

Repository tooling precedence

Before proposing or adding tooling:

1. Inspect repository instructions, scripts, manifests, task runners, CI, configuration, and development documentation.
2. Prefer repository-present commands and conventions.
3. Adapt project-scoped and global skills to the repository.
4. Extend existing tooling before introducing a parallel mechanism.
5. Replace tooling only when it is broken, unsafe, contradictory, abandoned, or explicitly under review.
6. Explain the concrete gap before adding a dependency or system.

Inherit first. Extend second. Replace deliberately. Invent last.

Scope and safety

* Confirm the repository root, branch, and worktree before making changes.
* Do not modify sibling repositories or worktrees.
* Inspect git status before and after work.
* Preserve existing uncommitted changes.
* Do not discard, reset, or overwrite user work.
* Use established repository verification commands.
* `bash scripts/check.sh` is the canonical repository verification gate. Run it locally before opening a PR, and rerun it before declaring an updated PR ready for review whenever relevant repository changes were made.
* Do not use GitHub CI as the first execution of a check. GitHub Actions (.github/workflows/ci.yml) reruns `scripts/check.sh` independently on each PR revision as a backstop, not as the first execution of these checks.
* Do not commit unless explicitly requested.
* Do not bypass repository hooks.

Agent delegation

* Use no more than five subagents concurrently.
* Only the primary agent may delegate.
* Subagents must not spawn or delegate to additional agents.
* Prefer direct work for sequential, small, or context-heavy tasks.
* Delegate only genuinely independent, bounded work.
* The five-subagent ceiling applies regardless of provider-specific enforcement or fan-out mechanism.
* Repository-local stricter limits take precedence.

Secrets and environment files

Never read, print, search, summarize, modify, copy, or transmit secret-bearing files.

Treat .env, .env.local, .env.*.local, private keys, credential files, and secrets/ directories as inaccessible.

Use examples, templates, documentation, and environment-variable names to understand configuration. Ask the user to confirm that a required variable exists rather than inspecting its value.

Do not run commands intended to reveal secrets, including env, printenv, shell startup dumps, Keychain reads, or credential-manager lookups.

Do not include secrets in logs, commits, generated files, prompts, or handoffs.

Commits

Use Conventional Commits.

Before committing:

* inspect the staged diff
* choose type and scope from the purpose of the change
* keep the commit cohesive
* recommend splitting unrelated changes
* run relevant verification
* allow repository hooks to run

Never create a commit without explicit approval.

Commit messages are validated by Cocogitto. If the local commit-msg hook is absent in a fresh checkout, install it with:

cog install-hook commit-msg

Planning

Prefer local Markdown planning.

* PLAN.md is concise project orientation.
* Active work lives in plans/active/.
* Completed work lives in plans/archive/.
* Read only the relevant plan unless broader context is required.
* Update plans when scope, status, decisions, verification, or uncertainties materially change.
* Do not require GitHub Issues.
* Publish work to GitHub when collaboration, review, notification, or external tracking makes it useful.
* Prefer reviewable outcomes over tiny task fragments.

No discovery/planning/review workflow is canonical or default (D029). repo-orientation, brainstorming, slice-plan, slice-review, slice-retro, and next-best-slice remain installed and may be invoked ad hoc when one genuinely fits the task at hand; none of them defines this repository's required workflow stages.

Discovery, specification, technical planning, task decomposition, and next-change selection are intentionally unassigned. Do not silently fill this gap with a personal skill, framework, or tool merely because it is installed or available.

Skills

Skills are advisory procedures, not repository authorities.

* Repository-local instructions and tooling take precedence.
* Use the smallest relevant skill set.
* Do not load unrelated specialist skills.
* Do not allow a skill to introduce frameworks, dependencies, or project structure without demonstrated need.
* Prefer proven upstream skills over local reinvention.
* Treat third-party skills as executable dependencies and review them before installation.

See docs/TOOLCHAIN.md for the current skill and tooling recommendations.

MCP usage

MCP servers provide capabilities; registration is not an instruction to use them.

* Use only servers relevant to the task.
* Prefer repository-native tools when they provide the capability clearly.
* Use MCP when the capability is not cleanly available through repository files, shell commands, language tooling, or installed skills.
* Keep mutation permissions narrow and prefer read-only access.
* Treat MCP output as evidence to verify, not unquestioned truth.

docs/TOOLCHAIN.md contains Bindle’s task-oriented MCP recommendations. They are reference guidance, not native client profiles or automatic routing.

Code intelligence

No code-intelligence MCP is currently adopted.

For structural or cross-file questions, prefer:

1. known files
2. rg, fd, Git, and language tooling
3. repository documentation and history
4. an adopted code-intelligence tool, if one exists

Do not treat tool availability as adoption. Confirm material conclusions in source code.

See D020 for the prior code-intelligence trial and its outcome.

Project memory

projectmem is an optional, machine-local operational memory layer, not repository state.

Tracked repository files remain authoritative. projectmem must never be required to build, test, run, or understand Bindle.

When projectmem is available:

* At session start, load project instructions and summary before substantive project work; load the project map when structure matters.
* Prefer projectmem MCP tools when connected; use the pjm CLI as fallback.
* Before modifying a file, check its recorded failure history.
* Record useful bugs, fix attempts, confirmed fixes, design decisions, and durable setup gotchas while working.
* Associate confirmed fixes with their explicit issue IDs rather than relying on implicit “most recent” selection.
* Never edit generated .projectmem/ state directly. PROJECT_MAP.md and plan.md are the exceptions where direct editing is supported.
* Use projectmem to avoid unnecessary rediscovery, but verify material current-state conclusions against tracked repository state.

.projectmem/ is gitignored and must not be committed.

Durable architecture, product rules, decisions, and operating instructions belong in tracked repository documentation, never only in projectmem.

See docs/TOOLCHAIN.md and D022 for details.

Local retrieval (QMD)

QMD is an optional, repository-scoped local search index over this
repository's own durable Markdown (root-level *.md, docs/, plans/), not a
source of truth and not a work-coordination system. Markdown files remain
authoritative; the QMD index is derived and rebuildable.

Opt in per repository, per worktree, with:

bindle init --qmd

This ensures a project-local QMD collection (`.qmd/`, untracked, never
committed) exists and is indexed via QMD's own native CLI. `bindle status`
reports read-only adoption state (`ready`, `not-initialized`,
`unavailable`, `conflict`). `bindle remove` never touches `.qmd/`.

When a repository has opted in:

* Use QMD's own native CLI directly — `qmd search`/`qmd query`/`qmd get` —
  rather than re-deriving retrieval through file reads or grep when the
  question is "what does this repository's Markdown already say about X."
* After adding or editing tracked Markdown, run `qmd update` yourself if
  you need the index to reflect it immediately; nothing refreshes it
  automatically.
* Do not run `qmd embed`, `qmd pull`, or any command that downloads
  embedding models unless the user explicitly asks for semantic/hybrid
  search — BM25 (`qmd search`) requires no model download and is the
  default mode.
* Never register or invoke QMD's MCP server (`qmd mcp`) or its Claude Code
  plugin as part of Bindle setup — not part of this integration's scope.

See docs/TOOLCHAIN.md and D036 for details.

Durable knowledge

A session is evidence that work occurred, not automatically durable truth.

Route information to its natural owner according to docs/DATA-OWNERSHIP.md.

Temporary exploration may remain disposable. Durable capture requires a reason.

The intended lifecycle is:

observed → candidate → current → superseded

Do not invent a broad ontology. Graphs and semantic indexes are derived conveniences, not canonical state.

Architecture rules

Apply these rules to proposals before implementation:

* Replaceability (D014): do not parse another tool’s private store. Use supported interfaces and owner-resolved pointers.
* Durability (D015): durable artifacts live with their owners. Bindle-owned state is configuration, disposable cache, or explicit export.
* Preservation (D016): capture requires a reason.
* Worktrees (D018): repository identity is the Git common directory; never assume one checkout per repository.

Every proposal must first answer:

1. Who naturally owns this?
2. Can that owner be replaced?
3. Does this deserve to survive?

A weak answer ends the proposal. Proposals that survive this screen must pass the full admission test in docs/PHILOSOPHY.md.

Obsidian projection

Use the dedicated Bindle vault, not the user’s personal vault.

Project only selected, human-useful durable material. Do not project every command, transcript, session, or intermediate attempt.

Prefer ordinary Markdown, standard Obsidian links, simple properties, and Bases for curated views. Use JSON Canvas only when spatial representation adds value.

Generated content must not overwrite human-authored content outside clearly managed sections.

Initial publication should be preview-first and approval-based.

See docs/DATA-OWNERSHIP.md for routing and authority.

Development isolation

Do not implement features directly in the primary bindle checkout.

* Use one Git worktree and feature branch per active product slice.
* Treat the primary checkout as the integration and release workspace.
* Confirm repository root, branch, and worktree before editing.
* Do not modify sibling worktrees.
* Do not use worktrees to bypass delegation limits.
* Keep main releasable.
* Start new work from an up-to-date main. Routine implementation and
  maintenance work must branch from main before modifying tracked files.
  main is canonical and read-only for routine work otherwise.
* development is retained only as historical/incubation material. Do not
  branch new work from development and do not merge it wholesale into main,
  unless the user explicitly directs otherwise.

See docs/WORKTREES.md for the identity model and operating details.

Runtime isolation

Never use live Bindle state during development or tests.

Development commands must use a repository-local or temporary Bindle home. Prefer:

BINDLE_HOME="$PWD/.bindle-dev" uv run bindle ...

Tests must use temporary directories.

Do not modify:

* ~/.local/share/bindle/
* the real Bindle Obsidian vault
* global Claude Code configuration
* global Codex configuration
* installed skills
* live MCP configuration

Inspection is read-only unless an approved plan explicitly covers mutation.

Any future mutation command must support preview before apply.

CLI invocation

Use:

uv run bindle ...

when testing development code.

Treat:

bindle ...

as the stable installed release.

Do not reinstall or replace the stable CLI unless explicitly requested.

Cross-project synthesis

The Obsidian Mind (om) trial is closed (D028); it is not repository authority and is not registered or used by this repository.

No standing cross-project memory system replaces it. Cross-project synthesis is deliberate and human-driven, or performed by a narrow, purpose-built skill when a concrete need actually emerges — never routine capture merely because a tool is available.

Accepted decisions belong in tracked repository documentation (docs/DECISIONS.md), never only in a memory or knowledge-vault tool.

Showcase

For meaningful work, preserve useful evidence when applicable:

* before and after states
* architecture diagrams
* screenshots
* traces or benchmarks
* scientific figures
* verification output
* important tradeoffs
* known limitations
* a short walkthrough path

Prefer existing repository showcase tooling before introducing a new presentation mechanism.

Communication

Use concise technical prose during interactive coding.

For durable documentation, academic or scientific material, stakeholder communication, showcases, and external correspondence, identify the audience and use complete prose rather than compressed working notes.

Canonical references

Consult these when their subject is material to the task:

* PLAN.md — current project orientation and near-term work
* docs/SCOPE.md — ownership boundaries and milestones
* docs/DECISIONS.md — accepted decisions and historical rationale
* docs/TOOLCHAIN.md — tooling, skills, and MCP guidance
* docs/PHILOSOPHY.md — architecture principles and feature admission
* docs/DATA-OWNERSHIP.md — authority, routing, and durable knowledge
* docs/WORKTREES.md — repository/worktree identity and operations
* docs/PRIVACY.md — disclosure threat model and repository privacy rules
* docs/SYMPHONY.md — canonical Symphony fork reference, pinned revision, and bootstrap requirements
