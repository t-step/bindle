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

* Superpowers — heavily used in practice (brainstorming, writing-plans, TDD, using-git-worktrees, finishing-a-development-branch, subagent-driven-development, and more; verified against real session history 2026-08-12)
* Caveman, default lite — used, lightly

Ponytail (previously documented "default lite") is dropped: zero invocations found across 158 real sessions checked 2026-08-12 (Valence, cover-story, bindle, the skills repo). <!-- private-ok: Bindle's own repo/decision names, not personal info -->

Frontend and product quality

Vercel skills, by actual use in Valence (verified 2026-08-12; "Vercel React Best Practices" and "Vercel Web Design Guidelines" — the previously documented pair — had zero invocations, and the second doesn't exist as an installed skill at all):

* vercel:nextjs
* vercel:vercel-cli
* vercel:vercel-storage

Backend and data

Nothing currently fills this role. "Supabase Postgres Best Practices" (previously documented) doesn't exist as an installed skill and had zero invocations.

No global generic backend, Python, ORM, or SQL-expert skill.

Security and correctness

Nothing currently adopted. The previously documented Trail of Bits names (Differential Review, Static Analysis, Variant Analysis, Insecure Defaults, Property-Based Testing) don't exist as installed skills and had zero invocations. What's actually installed is a different family, `testing-handbook-skills:*` (14 fuzzing-specific skills — AddressSanitizer, AFL++, libFuzzer, Wycheproof, and others) plus a separate general-purpose `security-review` skill — neither has been invoked in the sessions checked either.

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

Replaces a previously documented flow (grill-me, grilling, to-spec, to-tickets, triage) that is not installed — verified against the actual skill list 2026-08-12, see AGENTS.md's "Recommended flow."

Diagrams

No discrete diagram skill is adopted. "Mermaid skill" and "Draw.io skill" (previously documented) aren't installed skills — Artifacts render Mermaid natively, without a separate skill, and Draw.io was never confirmed to exist.

Showcase

* Visual Explainer — installed, but zero invocations found in the sessions checked 2026-08-12; unconfirmed whether it's actually useful in practice or just unused like the items above.

"Walkthrough" (previously documented as trial) doesn't exist as an installed skill; dropped.

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

No code intelligence MCP is currently registered. The code-review-graph trial was dropped (docs/DECISIONS.md D020) after zero real invocations across every available session in its two actual usage repos. See "Code intelligence" below for what would need to be true before a replacement gets documented here.

Academic later

* Zotero, read-only first
* arXiv

Scientific infrastructure later

* Globus
* Slurm or HPC MCP
* facility-specific compute MCPs

Code intelligence

code-review-graph (a globally-registered server, `codebase-memory-mcp`) was trialed and dropped 2026-08-12 (docs/DECISIONS.md D020). It was actually indexing two real repositories (Valence, cover-story — not CHILmesh, the originally named target, which was never indexed), kept current to exact HEAD, but a session-by-session audit found zero real invocations across all available sessions in either repo. Evidence, not the tool itself, was the problem: nothing had asked it anything. <!-- private-ok: Bindle's own repo/decision names, not personal info -->

Nothing currently fills this role. CodeGraph (github.com/colbymchenry/codegraph) was evaluated and failed its adoption gate — a real 71% tool-call reduction did not translate to lower cost (billing-category shift to cache-write, +64% overall) and it hallucinated a wrong answer on the most representative test question (docs/DECISIONS.md D021). If a candidate is adopted later, D007 (graphs are derived, never canonical) and D008 (project-scoped, not loaded by default) still govern it, and it should clear a higher bar than "available" before being documented here as adopted — demonstrated use and a real cost/correctness check in the target repo, checked the same way D020 and D021 were reached, not a vendor benchmark or a plausible-looking sample query. Default tooling for structural questions remains rg, fd, Git, and language tooling, per AGENTS.md's "Code intelligence" tool precedence.

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

Current:

* Conventional Commits
* Cocogitto validation

Deferred:

* Release Please
* semantic releases
* changelog automation
* package publication automation

Release automation should begin only when Bindle becomes an installable or externally consumed product.
