# TOOLCHAIN

## Purpose

Bindle describes and audits a development workshop shared by Claude Code and Codex.

The repository records desired toolchain state. It does not store credentials or blindly rewrite client configuration.

This document is the source of truth for Bindle’s toolchain policy, adopted skills, and task-specific tool recommendations.

Native client configuration remains in the configuration files the clients actually consume. Unconditionally registered MCP servers belong in `.mcp.json` for Claude Code and `.codex/config.toml` for Codex.

Task-specific skill and MCP recommendations in this document are guidance, not executable profiles. Do not duplicate them into machine-readable manifests unless a supported consumer requires such data.

## Selection policy

Choose tools according to demonstrated need and repository context.

Tool precedence

1. Repository-present tooling
2. Repository-local instructions
3. Project-scoped skills and MCP recommendations
4. Global skills
5. Generic defaults

Inherit first. Extend second. Replace deliberately. Invent last.

Before adding a dependency, integration, skill, or service:

* identify the concrete capability gap
* check whether repository-present tooling already addresses it
* prefer established standards and upstream tools over local reinvention
* consider operational and context cost as well as implementation cost
* avoid duplicating an existing provider merely because its integration is imperfect
* verify that the proposed tool belongs at the repository, project, or workshop scope

Availability or installation alone does not constitute adoption.

## Adoption states

Tooling in this workshop uses these states:

* Native — supplied by an execution environment or underlying development platform and used directly.
* Adopted — selected for its stated role and recommended when that role applies.
* Trial — actively being evaluated; availability does not imply permanent adoption.
* Project-scoped — adopted only within repositories whose domain requires it.
* Deferred — a plausible future candidate, not part of the current toolchain.
* Dropped — not part of the current toolchain. Historically important outcomes belong in docs/DECISIONS.md rather than the active inventory.

## Workshop baseline

### Execution

| Tool | State | Role |
| --- | --- | --- |
| Claude Code | Native | coding-agent execution harness |
| Codex | Native | coding-agent execution harness |

Bindle does not implement model routing, agent loops, approval systems, compaction, sandboxing, tool execution, or subagent runtimes.

### Coordination

| Tool | State | Role |
| --- | --- | --- |
| Symphony | Trial | candidate external work coordinator — referenced only, not installed, run, or invoked by Bindle |

Symphony is Bindle's candidate coordinator for the coordination pillar (PLAN.md, "Next" item 3): the canonical fork, pinned revision, and Symphony's own bootstrap requirements are recorded in `docs/SYMPHONY.md` (`docs/DECISIONS.md` D037). Bindle does not own subagent orchestration (see "Bindle does not own" in `docs/SCOPE.md`); Symphony stays externally owned, and this Trial state reflects an evaluated reference, not adoption. `plans/active/2026-08-24-symphony-coordination-exploration.md` records the architecture direction a future implementation would follow.

### Source and collaboration

| Tool | State | Role |
| --- | --- | --- |
| Git | Native | source history and repository state |
| GitHub / gh | Adopted | collaboration, pull requests, issues, and repository interaction when needed |
| Conventional Commits | Adopted | commit-message convention |
| Cocogitto | Adopted | commit-message validation |

Prefer portable repository-level mechanisms, such as Git hooks and repository configuration, when Claude Code and Codex need equivalent behavior.

## Terminal and discovery

| Tool | State | Role |
| --- | --- | --- |
| rg | Adopted | textual search |
| fd | Adopted | filesystem discovery |
| jq | Adopted | JSON inspection and transformation |
| sqlite3 | Adopted | direct inspection of appropriate SQLite data |
| fzf | Adopted | interactive human navigation |
| Ghostty | Native | terminal environment |
| tmux | Native | terminal session management |

Agents should generally prefer deterministic textual tools over interactive navigation tools such as fzf.

Never use direct datastore inspection to bypass the supported-interface and private-store rules in docs/PHILOSOPHY.md.

## Documentation and web

| Tool | State | Role |
| --- | --- | --- |
| Context7 | Adopted | external library and framework documentation |
| Playwright | Adopted | browser automation and web verification when required |

Context7 is part of the default MCP configuration. Playwright is task-specific rather than a reason to load browser automation for unrelated work.

## Skills

Skills are procedures, not authorities. Repository instructions and repository-present tooling take precedence.

Use the smallest relevant skill set and do not infer adoption from installation alone.

### Core engineering

* Superpowers — adopted for applicable engineering workflows, including brainstorming, planning, TDD, worktrees, branch completion, and bounded subagent-driven development.
* Caveman, default lite — adopted as lightweight engineering guidance where applicable.

### Planning and review

No discovery/planning/review sequence is canonical or default (docs/DECISIONS.md D029).

* repo-orientation
* brainstorming
* slice-plan
* slice-review
* slice-retro
* next-best-slice

These remain installed and available on demand; none of them defines this workflow's canonical stages. See AGENTS.md, "Planning" for current guidance and what remains intentionally unassigned.

### Frontend and product

Use project-scoped frontend skills when the repository’s stack requires them.

Currently relevant Vercel skills include:

* vercel:nextjs
* vercel:vercel-cli
* vercel:vercel-storage

These are not a requirement for repositories that do not use the corresponding stack.

### Scientific and academic

The adopted general scientific skill set includes:

* Scientific Critical Thinking
* Statistical Analysis
* Uncertainty and Units
* Exploratory Data Analysis
* Scientific Visualization
* Scientific Writing
* Literature Review
* Peer Review

Package-specific scientific procedures remain project-scoped.

### Knowledge surfaces

For Obsidian-based work:

* Obsidian Markdown
* Obsidian CLI

Use on demand:

* Obsidian Bases
* JSON Canvas

Provider-specific features should add clear value without making durable content unnecessarily dependent on that provider.

### Project-scoped skills

Domain-specific skills belong to the repositories that require them rather than the Bindle baseline.

Examples include:

* Godot skills
* Hugging Face CLI and Jobs
* dataset publication
* evaluation workflows
* deployment workflows
* package-specific scientific skills

### Showcase

Visual Explainer remains a Trial skill for work where visual presentation materially improves the result.

Do not introduce a separate showcase mechanism when the repository already provides an appropriate documentation, demo, notebook, Storybook, or visualization surface.

## MCP

MCP servers are capability providers, not a default buffet.

Registration means a capability is available. It does not mean every session should use it.

### Default

| Server | State | Role |
| --- | --- | --- |
| Context7 | Adopted | external documentation lookup |

Default MCP configuration is committed in the native client configuration files:

* `.mcp.json` for Claude Code
* `.codex/config.toml` for Codex

### Task-specific

Use additional MCP servers only when their capability is relevant to the task.

Current recommendations include:

| Capability | Provider | State |
| --- | --- | --- |
| browser automation | Playwright | Adopted, task-specific |
| Hugging Face interaction | Hugging Face MCP | Project-scoped |
| project working memory | projectmem | Adopted |

GitHub interaction uses the gh CLI directly. A dedicated GitHub MCP server is not currently adopted.

### Code intelligence

No code-intelligence MCP is currently adopted.

For structural and cross-file questions, default to:

1. known files
2. rg, fd, Git, and language tooling
3. repository documentation and history
4. an adopted code-intelligence provider, if one exists

Previous candidates failed their adoption evaluations; see D020 and D021.

Any future candidate must demonstrate real value in representative repository work, including correctness and total cost. Availability, vendor benchmarks, or a successful sample query are insufficient.

Graphs remain derived rather than canonical (D007).

## Memory and knowledge

Bindle does not own user memory, working reasoning, transcripts, or durable knowledge. It bridges systems that do.

| Role | Current provider | State | Ownership |
| repository-local working memory | projectmem | Adopted | provider-owned, machine-local |
| local retrieval over durable Markdown | QMD | Project-scoped (D036) | provider-owned, worktree-local, derived/rebuildable |
| durable knowledge and work records | no standing provider | Closed (D028) | none — deliberate, human/skill-driven when a concrete need emerges |
| live sessions and transcripts | Claude Code / Codex | Native | harness-owned |
| deterministic code-state evidence | Git + Bindle evidence blocks | Bindle capability | emitted into provider-owned records |

### projectmem

projectmem is operational working memory, not accepted project truth.

It may reduce rediscovery and preserve useful local working context, but durable architecture, product rules, decisions, and operating instructions remain in tracked repository files.

Its detailed operating rules live in AGENTS.md.

### QMD

QMD (`tobi/qmd`, published as `@tobilu/qmd`) is an optional, repository-scoped local search index over a repository's own durable Markdown — BM25 full-text search always available, vector/hybrid retrieval available once embedding models are pulled explicitly via QMD's own CLI.

Opt in per repository via `bindle init --qmd`; `bindle status` reports read-only adoption state. The index is derived and rebuildable from the same Markdown files that already remain authoritative — deleting and rebuilding it never loses knowledge, and `bindle remove` never touches it (docs/DECISIONS.md D036).

Not used for work coordination, agent-prompt retrieval, or Projectmem promotion in this slice — see D036 for the full scope boundary.

### Durable knowledge

Durable lessons and work records belong to an approved knowledge surface rather than Bindle itself.

The Obsidian Mind (om) trial closed without adoption (docs/DECISIONS.md D028). No standing durable-knowledge or cross-project memory provider is currently adopted. Cross-project synthesis is deliberate and human-driven, or performed by a narrow, purpose-built skill when a concrete need emerges, rather than a continuously installed memory system. Historical trial evidence is preserved in `plans/archive/`.

### Evidence

Git provides deterministic repository state. Bindle may stamp that state into evidence blocks according to docs/WORKTREES.md.

Evidence blocks are provenance, not a Bindle-owned history database.

## Observability

No generic observability skill or platform is adopted.

Projects should use repository-appropriate observability, which may include:

* structured logs
* metrics
* traces
* diagnostic commands
* health checks

Prefer established observability standards and libraries when observability is required. Introduce additional infrastructure only for a demonstrated need.

OpenTelemetry is an appropriate standard to evaluate when structured instrumentation or interoperability across observability providers is useful; its use does not require Bindle to own an observability platform.

## Release tooling

Bindle uses Conventional Commits and Cocogitto for commit discipline and validation.

CI, versioning, changelog generation, tagging, packaging, and publication for Bindle itself are ordinary repository infrastructure. They may be introduced or changed according to demonstrated repository needs and the normal tooling precedence.

Maintaining Bindle’s own release infrastructure does not make generic release automation part of the Bindle product.

A capability that other projects delegate their release automation to would be a separate scope proposal and must pass the feature-admission test in `docs/PHILOSOPHY.md`.

Current implementation status and sequencing belong in PLAN.md, not in this policy.

## Deferred candidates

Deferred tools are not part of the current toolchain and should not be loaded, installed, or introduced merely because they appear here.

Current candidates include:

* temporal or semantic indexing providers such as Graphiti
* Zotero integration, read-only first
* arXiv integration
* Globus
* Slurm or HPC integrations
* facility-specific compute integrations

A deferred candidate becomes a trial only when a concrete need, evaluation scope, and removal path are defined.

Durable artifacts must remain independent of optional provider backends.
