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

This repository is defining the workshop, conventions, and first vertical slice.

Do not implement a memory platform, graph system, background daemon, orchestration framework, or generic agent harness without an approved plan.

The first likely product capability is durable cross-project session continuity.

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

* Use no more than three subagents concurrently.
* Only the primary agent may delegate.
* Subagents must not spawn, nest, or delegate to additional agents.
* Do not use teams, forks, workflows, repeated waves, or equivalent mechanisms to evade the limit.
* Prefer direct work in the primary agent for sequential, small, or context-heavy tasks.
* Use subagents only for genuinely independent, bounded work.
* Repository-local stricter limits take precedence.

This policy is enforced globally (not just advisory) via Claude Code hooks in
`~/.claude/settings.json`:

* `PreToolUse` on the `Agent` tool (`~/.claude/hooks/subagent-limit-guard`)
  denies any call whose payload carries an `agent_id` (a subagent calling
  `Agent` again — nesting), and denies new top-level calls once three
  subagents are concurrently active.
* `SubagentStart` / `SubagentStop` (`subagent-track-start` /
  `subagent-track-stop`) maintain the per-session active-subagent count the
  guard checks.

Known gap: the `Workflow` tool's internal `agent()` fan-out does not go
through the `Agent` tool, so `subagent-limit-guard` never sees it and cannot
cap a workflow's own internal concurrency (verified empirically — confirmed
via captured hook payloads that `SubagentStart`/`SubagentStop` do fire for
workflow-spawned agents with `agent_type: "workflow-subagent"`, but no
`PreToolUse` fires per individual `agent()` call, only once for the outer
`Workflow` tool invocation). Workflows remain bound only by their own
opt-in requirement and internal concurrency cap, not by this policy's
three-subagent ceiling — this is the "workflows... to evade the limit" case
called out above, left unpatched by choice rather than oversight.

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

grill-me
→ to-spec
→ local plan
→ implementation
→ verification
→ showcase

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

MCP servers are capability profiles, not a default tool buffet.

* Load only the profile relevant to the task.
* Prefer native repository tools when they provide the same capability clearly.
* Use MCP for capabilities not cleanly available through files, shell commands, or installed skills.
* Keep mutation permissions narrow.
* Prefer read-only access by default.
* Treat MCP output as evidence to verify, not unquestioned truth.

Code intelligence

code-review-graph is optional and project-scoped.

Use it when:

* reviewing a multi-file or cross-module change
* estimating blast radius
* tracing callers, dependents, or execution paths
* identifying potentially affected tests
* changing public interfaces or shared models
* investigating cross-language boundaries
* orienting in a large or unfamiliar subsystem

Do not use it when:

* the task concerns one or two known files
* rg, Git, or language tooling answers the question directly
* performing ordinary text search
* editing documentation only
* the repository is small
* the graph may be stale or absent

Tool precedence:

1. known files
2. rg, fd, Git, and language tooling
3. repository documentation and history
4. code-review-graph

Confirm material conclusions in source code.

Project memory (projectmem)

This repository trials projectmem as a local operational memory layer (see docs/TOOLCHAIN.md). It is machine-local working memory, not repository state:

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
- Do not use worktrees to bypass the three-subagent limit.
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

## Obsidian Mind trial (temporary)

An `om` MCP server may be registered during the current trial. om is local operational memory, not repository state:

* om is not required to build, test, run, or understand this repository. Do not assume another contributor — human or agent — has it installed or registered. Work normally when it is absent.
* The vault, its manifests, indexes, caches, and personal notes live outside this repository and must never be committed here. The only tracked om-related artifact is `.om-project`, a one-line routing label containing no personal or machine-specific data (tracked deliberately so every worktree and branch declares the same project identity; docs/WORKTREES.md).
* Durable decisions still belong to tracked docs: accepted decisions go to docs/DECISIONS.md, never only to the vault.

When om is available:

* Capture is checkpoint-based, not per-session (D019): at natural boundaries only — an experiment
  concludes, a retrospective is written, a substantial design or engineering review ends, or the
  same lesson surfaces in a second project — ask whether the lesson would change decisions in
  another repository or future project. If yes, offer `om remember` (cross-project lesson) or
  `om record_work` (session narrative worth keeping); if no, write nothing. The routing table in
  docs/DATA-OWNERSHIP.md governs; accepted decisions still go to docs/DECISIONS.md, never only to
  the vault.
* Durable capture requires a reason (D016). Do not record to satisfy tooling.
* Codex sessions: om currently sees an anonymous caller. Prefer `om search` over `recall`, and
  expect writes to land in the vault inbox. Do not work around this silently — it is under
  observation.
* `.om-project` is a routing label only; repository identity remains the git common directory (D018).
* Evidence lines in records are conditional; see plans/active/2026-08-02-om-trial-runbook.md.
