# AGENTS

Bindle Working Instructions

Repository purpose

Bindle is a stateless toolchain bridge. It moves useful context and evidence between tools that already own their domains; it is not itself a store of user history (docs/PHILOSOPHY.md, D014–D016).

Claude Code and Codex remain the execution harnesses.

Bindle may provide:

* toolchain manifests, doctor checks, and drift diagnosis
* deterministic evidence blocks emitted from git state
* pointers and provenance links between provider-owned records
* lightweight adapters, hooks, templates, and commands at tool seams
* bounded resume-context assembly from provider-owned records
* selective projection emission into surfaces the owning systems maintain

Bindle does not replace:

* Claude Code
* Codex
* Obsidian
* Git or GitHub
* project management tools
* documentation lookup
* browser automation
* code intelligence
* security scanners
* scientific tooling
* graph databases
* agent execution loops

Current phase

The workshop is established: manifests, doctor checks, the decision log, and toolchain policy are in place (docs/DECISIONS.md, docs/TOOLCHAIN.md). Implementation of the first vertical slice has not started — there is no package manifest, build system, linter, or test suite yet. Current milestone sequence lives in PLAN.md and docs/SCOPE.md.

Do not implement a memory platform, graph system, background daemon, orchestration framework, or generic agent harness without an approved plan.

Repository tooling precedence

Before proposing or adding tooling:

1. Inspect repository instructions, scripts, manifests, task runners, CI workflows, configuration, and development documentation.
2. Prefer repository-present commands and conventions.
3. Adapt project-scoped and global skills to the repository.
4. Extend existing tooling before introducing a parallel mechanism.
5. Replace tooling only when it is broken, unsafe, contradictory, abandoned, or explicitly under review.
6. Explain the concrete gap before adding a dependency or system.

Inherit first. Extend second. Replace deliberately. Invent last.

Scope and safety

* Confirm the repository root before making changes.
* Do not modify sibling repositories.
* Inspect git status before and after work.
* Preserve existing uncommitted changes.
* Do not discard, reset, or overwrite user work.
* Use the repository’s established verification commands.
* Do not claim completion without running relevant checks.
* Verification is local-first: this repository is private, so GitHub CI runs rarely and must never be the first place checks execute. Run every relevant check locally and confirm it passes before opening a PR.
* Do not commit unless explicitly requested.
* Do not bypass repository hooks.

Agent delegation policy

* Use no more than five subagents concurrently.
* Only the primary agent may delegate.
* Subagents must not spawn, nest, or delegate to additional agents.
* Do not use teams, forks, workflows, repeated waves, or equivalent mechanisms to evade the limit.
* Prefer direct work in the primary agent for sequential, small, or context-heavy tasks.
* Use subagents only for genuinely independent, bounded work.
* Repository-local stricter limits take precedence.

This policy may be enforced by provider- or machine-specific mechanisms (for
example, Claude Code hooks) outside this repository. Such mechanisms are not
portable across harnesses and are not documented here — the policy above
governs regardless of what any specific mechanism does or does not catch.

One gap agents should account for regardless of enforcement: a workflow or
similar fan-out tool's internal concurrency is not necessarily bound by any
external enforcement of this policy's five-subagent ceiling. Do not treat
the absence of a technical block as permission — the "do not use
workflows... to evade the limit" rule above applies whether or not it is
mechanically enforced.

Secrets and environment files

* Never read, print, search, summarize, modify, copy, or transmit secret-bearing files.
* Treat .env, .env.local, .env.*.local, private keys, credential files, and secrets/ directories as inaccessible.
* Use .env.example, .env.template, documentation, and environment-variable names to understand configuration.
* Do not run commands intended to reveal secret values, including env, printenv, shell startup dumps, Keychain reads, or credential-manager lookups.
* Ask the user to confirm that a required variable exists rather than requesting or inspecting its value.
* Do not include secrets in logs, commits, generated files, prompts, or handoffs.

Commits

* Use Conventional Commits.
* Inspect the staged diff before selecting a commit type and scope.
* Describe the purpose of the change, not merely the files touched.
* Keep commits cohesive.
* Recommend splitting unrelated changes.
* Run relevant verification before committing.
* Do not bypass commit hooks.
* Do not create a commit without explicit approval.

Examples:

docs: define initial toolchain
chore: add repository hygiene defaults
feat(session): add durable session records
fix(projection): preserve human-authored note sections

Planning

* Prefer local Markdown planning.
* PLAN.md is the concise project orientation.
* Active work lives in plans/active/.
* Completed work moves to plans/archive/.
* Read only the relevant plan unless broader context is required.
* Update plans when scope, status, decisions, verification, or uncertainties materially change.
* Do not require GitHub Issues.
* Publish work to GitHub only when collaboration, review, notification, or external tracking makes it useful.
* Prefer reviewable outcomes over tiny task fragments.

Recommended flow:

repo-orientation (when unfamiliar with the repo)
→ brainstorming
→ slice-plan
→ implementation
→ slice-review
→ slice-retro
→ next-best-slice (decides what's next, then repeat)

grill-me, to-spec, to-tickets, triage, and grilling — the previously documented flow — are not
installed; this replaces them with what's actually available (verified 2026-08-12).

Do not use the full flow for obvious, mechanical, or already-approved work.

Skills

Skills are advisory procedures, not repository authorities.

* Repository-local instructions and tooling take precedence.
* Use the smallest relevant skill set.
* Do not load unrelated specialist skills.
* Do not allow a skill to introduce frameworks, dependencies, or project structure without a demonstrated need.
* Prefer proven upstream skills over local reinvention.
* Treat third-party skills as executable dependencies and review them before installation.

MCP usage

MCP servers are capability tools, not a default buffet — registering one doesn't mean every session should reach for it. No MCP client has a native "profile" concept; docs/TOOLCHAIN.md's "MCP recommendations by task" section is a curated reference list for deciding what's worth registering, not something any client loads or switches automatically based on task type — and nothing in this repository enforces consulting it either. Treat it as a reference to check, not a trigger that fires on its own.

* Load only the server relevant to the task.
* Prefer native repository tools when they provide the same capability clearly.
* Use MCP for capabilities not cleanly available through files, shell commands, or installed skills.
* Keep mutation permissions narrow.
* Prefer read-only access by default.
* Treat MCP output as evidence to verify, not unquestioned truth.

Code intelligence

No code intelligence MCP is currently registered or documented as adopted. The code-review-graph trial was dropped (docs/DECISIONS.md D020) after a session audit found zero real invocations despite the server being available in the near totality of sessions across its two actual usage repos.

Default tool precedence for structural or cross-file questions:

1. known files
2. rg, fd, Git, and language tooling
3. repository documentation and history
4. a documented code intelligence tool, only if one is adopted

A future candidate — reviewing a multi-file or cross-module change, estimating blast radius, tracing callers/dependents/execution paths, cross-language boundaries, orienting in a large unfamiliar subsystem — would be evaluated against this same precedence, and should not be documented here as adopted on availability alone; it needs demonstrated use, checked the way D020 was (a real session audit, not a sample query).

Confirm material conclusions in source code.

Project memory (projectmem)

This repository adopts projectmem as a local operational memory layer (accepted, docs/DECISIONS.md D022; see docs/TOOLCHAIN.md). It is machine-local working memory, not repository state:

* projectmem is not required to build, test, run, or understand this repository; everything durable lives in tracked files. Do not assume another contributor — human or agent — has it installed or registered. Work normally when it is absent.
* Durable architecture, decisions, product rules, and operating instructions live in tracked repository docs (docs/DECISIONS.md, docs/, AGENTS.md), never only in a memory tool.
* `.projectmem/` (generated summaries, event logs, issues, plans) is gitignored and must not be committed.

When projectmem is available, use its workflow:

* At session start, load the project instructions and summary before answering questions about the project — via the projectmem MCP tools (`get_instructions`, `get_summary`, and `get_project_map` when structure matters) where the server is connected, otherwise via the CLI: `pjm instructions`, `pjm show`, `pjm map`.
* Before modifying a file, check its failure history: `precheck_file(path)` or `pjm precheck <path>`.
* Log while working: bug found → `log_issue` / `pjm log`; each fix attempt → `record_attempt` / `pjm attempt`; confirmed fix → `record_fix(summary, issue_id=...)` / `pjm fix` with the explicit issue id — never let the tool infer the target from "most recent open issue"; design choice → `add_decision` / `pjm decision`; gotcha or setup detail → `add_note` / `pjm note`.
* Never edit `.projectmem/` files directly; `summary.md` regenerates from `events.jsonl`, and direct edits break audit replay. `PROJECT_MAP.md` and `plan.md` are the exceptions and may be edited directly.
* Prefer these tools over re-scanning source files when they answer the same question.

Harness note: registration is machine-local (no tracked `.mcp.json`). On this machine the projectmem MCP server is registered for Claude Code (project scope in user config) and globally for Codex (no `--root`; the server parent-walks from the session directory to find `.projectmem/`, so only initialized repos answer). Prefer the MCP tools when connected; the `pjm` CLI is the fallback.

Sessions and durable knowledge

A session is evidence that work occurred. It is not automatically durable truth.

Route information to its owner, not into Bindle: the authority model and routing table live in docs/DATA-OWNERSHIP.md. Bindle distinguishes evidence (deterministic, immutable observations), working reasoning (provider-owned, disposable), and promoted knowledge (owned by the decision log or the vault).

Not every thought deserves to be preserved. Durable capture requires a reason (D016); temporary exploration stays in transcripts and scratch space and is allowed to disappear.

Obsidian should receive selected, human-useful projections rather than every command, transcript, or intermediate attempt.

Promotion should initially be explicit or proposed for approval.

The intended lifecycle is:

observed → candidate → current → superseded

Do not invent a broad ontology.

Graphs and semantic indexes are derived conveniences, not canonical state.

Architecture rules

* Replaceability (D014): no Bindle code parses another tool's private store; call supported interfaces, emit blocks others embed, hold pointers owners resolve.
* Durability (D015): durable artifacts live with their owners; Bindle-owned state is configuration, disposable cache, or explicit export.
* Preservation (D016): capture requires a reason.
* Worktrees (D018): repository identity is the git common directory; never assume one checkout per repository (docs/WORKTREES.md).
* Every proposal answers three questions first — who naturally owns this, can that owner be replaced, does this deserve to survive. A weak answer to any of them ends the proposal.
* Proposals that survive the screen must pass the full admission test in docs/PHILOSOPHY.md.

Obsidian projection

Use a dedicated Bindle vault rather than the user’s personal vault.

The Bindle vault may contain:

* project notes
* promoted decisions
* patterns
* research findings
* open questions
* important session landmarks
* generated views and links

Do not project every raw session into Obsidian.

Prefer:

* ordinary Markdown
* standard Obsidian links
* simple properties
* Bases for curated views
* JSON Canvas only when spatial representation helps

Generated content must not overwrite human-authored content outside clearly managed sections.

Initial publication should be preview-first and approval-based.

Showcase

Showcasing is part of the definition of done for meaningful work.

When applicable, preserve:

* before and after states
* architecture diagrams
* screenshots
* traces
* benchmarks
* scientific figures
* verification output
* important tradeoffs
* known limitations
* a short walkthrough path

Prefer existing repository showcase tooling, demos, documentation sites, Storybook instances, notebooks, or scripts before introducing a new presentation mechanism.

Communication style

Use concise technical prose during interactive coding.

Do not apply compressed or fragmentary style to:

* repository documentation
* academic writing
* scientific explanations
* stakeholder communication
* showcases
* external correspondence
* material intended for unfamiliar readers

Identify the audience and write complete prose for durable artifacts.

## Development isolation

- Do not implement features directly in the primary `bindle` checkout.
- Use one Git worktree and feature branch per active product slice.
- Treat the primary checkout as the integration and release workspace.
- Confirm the current branch, repository root, and worktree before editing.
- Do not modify sibling worktrees.
- Do not use worktrees to bypass the five-subagent limit.
- Keep `main` releasable.

## Runtime isolation

- Never use live Bindle state during development or tests.
- Development commands must use a repository-local or temporary Bindle home.
- Prefer:

  `BINDLE_HOME="$PWD/.bindle-dev" uv run bindle ...`

- Tests must use temporary directories.
- Do not modify:
  - `~/.local/share/bindle/`
  - the real Bindle Obsidian vault
  - global Claude Code configuration
  - global Codex configuration
  - installed skills
  - live MCP configuration

- Inspection is read-only unless an approved plan explicitly covers mutation.
- Any future mutation command must support preview before apply.

## CLI invocation

- Use `uv run bindle ...` when testing development code.
- Treat plain `bindle ...` as the stable installed release.
- Do not reinstall or replace the stable CLI unless explicitly requested.
