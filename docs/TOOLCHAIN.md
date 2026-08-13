# Toolchain

Bindle describes and audits a development workshop shared by Claude Code and Codex.

The repository records desired state. It does not store credentials or blindly rewrite client configuration.

Machine-readable configuration

This document is the single source for toolchain policy — skill bundles and task-conditional MCP recommendations are prose here, not duplicated into a parallel YAML file. "Task-conditional MCP recommendations" is Bindle's own organizing scheme, not a client feature: no MCP client has a native profile concept that loads or switches server bundles by task type — what follows is a curated reference list for deciding what's worth registering, consulted by convention, not enforced by any mechanism. No cross-tool skill-recommendation manifest exists yet either (Claude Code's project-scoped `enabledPlugins` is real but Claude-only; Codex has no equivalent — see [openai/codex#18115](https://github.com/openai/codex/issues/18115)). The one exception is MCP servers that are unconditionally default (currently just Context7, below): those are committed as real, natively-consumed config in `.mcp.json` (Claude Code) and `.codex/config.toml` (Codex), not described here as data to keep in sync by hand.

Tool precedence

1. Repository-present tooling
2. Repository-local instructions
3. Project-scoped skills and MCP recommendations
4. Global skills
5. Generic defaults

Inherit first. Extend second. Replace deliberately. Invent last.

Native tools

Coding agents

* Claude Code
* Codex

Both remain native execution harnesses.

Bindle does not implement:

* model routing
* tool execution
* agent loops
* approval systems
* compaction
* sandboxing
* subagent runtimes

Knowledge

* Obsidian
* dedicated Bindle vault
* ordinary Markdown
* Obsidian CLI
* Obsidian Bases when useful
* JSON Canvas when useful

The user’s personal vault remains separate.

Source and collaboration

* Git
* GitHub when collaboration requires it
* Conventional Commits
* Cocogitto for validation

Terminal and discovery

* Ghostty
* tmux
* rg
* fd
* fzf
* jq
* sqlite3

fzf is primarily a human navigation tool. Agents should generally prefer deterministic textual tools.

Web and documentation

* Context7
* Playwright

Scientific and mesh work

* CHILmesh
* ADCIRCPy
* ADCIRC
* ADCIRC test suite
* OceanMesh2D
* QGIS
* Hugging Face
* DesignSafe or Zenodo when publication requires them

Game development

* Godot 4.x

Other engines are outside the initial toolchain.

Skills

Core engineering

* Superpowers — heavily used in practice (brainstorming, writing-plans, TDD, using-git-worktrees, finishing-a-development-branch, subagent-driven-development, and more)
* Caveman, default lite — used, lightly

Ponytail (previously documented "default lite") is dropped: zero invocations found in real session history checked 2026-08-12.

Frontend and product quality

Vercel skills, by actual use (verified 2026-08-12):

* vercel:nextjs
* vercel:vercel-cli
* vercel:vercel-storage

Previously documented "Vercel React Best Practices" and "Vercel Web Design Guidelines" are dropped — the second was never an installed skill at all.

Backend and data

Nothing currently fills this role. "Supabase Postgres Best Practices" (previously documented) is dropped — never an installed skill.

No global generic backend, Python, ORM, or SQL-expert skill.

Security and correctness

Nothing currently adopted. Previously documented Trail of Bits skill names never existed as installed skills. What's actually installed is unrelated: `testing-handbook-skills:*` (fuzzing-specific) and a general-purpose `security-review` skill — neither has seen real use yet.

Scientific and academic

From the selected scientific skill collection:

* Scientific Critical Thinking
* Statistical Analysis
* Uncertainty and Units
* Exploratory Data Analysis
* Scientific Visualization
* Scientific Writing
* Literature Review
* Peer Review

Package-specific scientific skills remain project-scoped.

Obsidian

* Obsidian Markdown
* Obsidian CLI

On demand:

* Obsidian Bases
* JSON Canvas

Deferred:

* Defuddle

Planning

* Superpowers brainstorming
* repo-orientation
* slice-plan
* slice-review
* slice-retro
* next-best-slice

Replaces a previously documented flow not installed here; see AGENTS.md's "Recommended flow" for detail.

Diagrams

No discrete diagram skill is adopted. Artifacts render Mermaid natively, without a separate skill.

Showcase

* Visual Explainer — installed but unused so far (checked 2026-08-12); usefulness in practice unconfirmed.

"Walkthrough" (previously documented as trial) never existed as an installed skill; dropped.

Project-scoped

* Godot 4 skills
* Hugging Face CLI
* Hugging Face Jobs
* dataset publication
* evaluations
* Spaces deployment
* package-specific scientific skills

MCP recommendations by task

Default (committed as real config: `.mcp.json`, `.codex/config.toml`)

* Context7

Web

* Context7
* Playwright

GitHub work uses the `gh` CLI directly, not a dedicated MCP server — no MCP server was ever wired up here, and `gh` already covers PR/issue/repo interaction for both harnesses without the added context cost of a registered server.

Research and ML

* Context7
* Hugging Face MCP

Code intelligence

No code intelligence MCP is adopted. code-review-graph was trialed and dropped — available in nearly every session but never actually invoked (docs/DECISIONS.md D020). A replacement candidate, CodeGraph, was evaluated and failed its adoption gate: real-world cost went up despite fewer tool calls, and it hallucinated on the most representative test question (docs/DECISIONS.md D021).

D007 (graphs are derived, never canonical) and D008 (project-scoped, not loaded by default) govern any future candidate. A replacement needs a higher bar than availability — demonstrated use and a real cost/correctness check in the target repo, audited the same way D020 and D021 were, not a vendor benchmark or a sample query. Default tooling for structural questions remains rg, fd, Git, and language tooling, per AGENTS.md's "Code intelligence" precedence.

Academic later

* Zotero, read-only first
* arXiv

Scientific infrastructure later

* Globus
* Slurm or HPC MCP
* facility-specific compute MCPs

Memory and sessions

Bindle does not own memory or sessions. Providers do, and Bindle bridges them (docs/PHILOSOPHY.md, docs/DATA-OWNERSHIP.md):

* repository-local working memory: projectmem, adopted (D022) — branch-blind; treat as working notes, never accepted truth
* durable personal knowledge and work records: obsidian-mind vault with the om MCP server, adopted (docs/DECISIONS.md D023)
* transcripts and live context: Claude Code and Codex natively
* deterministic evidence: git, stamped into evidence blocks by Bindle

Candidate temporal index:

* Graphiti, deferred — a derived, removable provider experiment

Durable artifacts must remain independent of any graph backend, and no Bindle code may parse a provider's private store (D014).

Observability

No generic observability skill is selected.

Projects should use repository-appropriate:

* structured logs
* metrics
* traces
* diagnostic commands
* health checks

OpenTelemetry should be introduced only when project complexity earns it.

Release policy

Current, for Bindle's own commit discipline:

* Conventional Commits
* Cocogitto validation (a local `commit-msg` hook, not tracked by git; see CLAUDE.md "Repository state")

No CI or release-automation machinery exists in this repository yet — no GitHub Actions workflow, no tagging, no changelog generation, no package publication. Nothing below is partially built or imminent; it is deferred.

Two distinct questions, kept separate:

* Ordinary release infrastructure for Bindle itself (CI checks, versioning, changelog generation, package publication) is deferred until Bindle ships an installable or externally consumed artifact. Release Please, semantic-release, or an equivalent would be evaluated then, under the same precedence as any other tool (inherit first, extend second, replace deliberately, invent last).
* Bindle becoming a generic release-automation capability — a tool other projects delegate their own release automation to — is a different and larger claim than "Bindle has CI." Nothing above implies it; it is out of scope and would need its own pass against the admission test in docs/PHILOSOPHY.md if ever proposed.
