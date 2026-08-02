# Toolchain

Bindle describes and audits a development workshop shared by Claude Code and Codex.

The repository records desired state. It does not store credentials or blindly rewrite client configuration.

Tool precedence

1. Repository-present tooling
2. Repository-local instructions
3. Project-scoped skills and MCP profiles
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

* Superpowers
* Ponytail, default lite
* Caveman, default lite

Frontend and product quality

* Vercel React Best Practices
* Vercel Web Design Guidelines

Backend and data

* Supabase Postgres Best Practices

No global generic backend, Python, ORM, or SQL-expert skill.

Security and correctness

From Trail of Bits:

* Differential Review
* Static Analysis
* Variant Analysis
* Insecure Defaults
* Property-Based Testing

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

* Superpowers brainstorming and planning
* grill-me
* grilling
* to-spec
* to-tickets
* triage

Diagrams

* Mermaid skill

On demand:

* Draw.io skill

Showcase

* Visual Explainer

Trial:

* Walkthrough

Project-scoped

* Godot 4 skills
* Hugging Face CLI
* Hugging Face Jobs
* dataset publication
* evaluations
* Spaces deployment
* package-specific scientific skills

MCP profiles

Default

* Context7

Web

* Context7
* Playwright

GitHub

* Context7
* restricted GitHub MCP

Research and ML

* Context7
* Hugging Face MCP

Code intelligence

* code-review-graph

This profile is restricted to larger repositories and graph-shaped questions.

Academic later

* Zotero, read-only first
* arXiv

Scientific infrastructure later

* Globus
* Slurm or HPC MCP
* facility-specific compute MCPs

Code intelligence

code-review-graph is currently a bounded trial.

Initial target repositories:

* Valence
* CHILmesh

Purpose:

* impact analysis
* callers and dependents
* affected tests
* cross-module review
* cross-language tracing

It is not:

* general project memory
* a documentation graph
* an Obsidian graph
* canonical source truth
* appropriate for every repository

Generated state remains local and uncommitted.

Memory and sessions

Bindle does not own memory or sessions. Providers do, and Bindle bridges them (docs/PHILOSOPHY.md, docs/DATA-OWNERSHIP.md):

* repository-local working memory: projectmem, trial only — branch-blind; treat as working notes, never accepted truth
* durable personal knowledge and work records: obsidian-mind vault with the om MCP server, candidate under evaluation
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
