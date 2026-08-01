# SCOPE

## Purpose

Bindle is a continuity layer for engineering work performed across Claude Code, Codex, repositories, and projects.

Its primary human interface is expected to be a dedicated Obsidian vault generated from durable structured records.

Core loop

capture
→ promote
→ project
→ resume

Bindle owns

* cross-project session identity
* durable session records
* repository and agent metadata
* current versus stale knowledge
* explicit or proposed promotion
* supersession
* bounded resume context
* provenance and evidence links
* selective Obsidian projection
* toolchain manifests and audits

Bindle may later own

* context assembly across sessions and repositories
* cross-project related-session retrieval
* contradiction or stale-knowledge warnings
* temporal indexing adapters
* an optional Graphiti integration
* bootstrap and doctor workflows that enforce equivalent behavior across Claude Code and Codex, preferring shared repository-level mechanisms (git hooks, repository configuration) over harness-specific ones, with per-harness adapters only where no portable mechanism exists

Bindle does not own

* coding-agent execution
* model routing
* sandboxing
* subagent orchestration
* code editing
* browser automation
* external documentation retrieval
* code graphs
* Git history
* GitHub issue tracking
* scientific-computing frameworks
* note-taking
* release automation
* telemetry platforms
* security scanning
* a generic project-management system

Canonical state

Canonical state should be structured, local, inspectable, and portable.

Candidate layout:

~/.bindle/
├── sessions/
├── memories/
├── index.sqlite
└── config.yaml

The Obsidian vault is a projection and human-curation surface.

Graph databases and semantic indexes are derived and replaceable.

Session model

A session is immutable evidence that work occurred.

A session may contain:

* identifier
* timestamps
* agent
* project
* repository
* branch and worktree
* intent
* outcomes
* decisions
* changed files
* evidence
* remaining work
* uncertainties
* related projects

A session is not automatically durable project guidance.

Promotion

Use a small lifecycle:

observed → candidate → current → superseded

Promotion should initially be:

* explicit
* proposed by the agent
* approved or edited by the user

Do not invent a broad ontology.

Obsidian projection

The dedicated Bindle vault may contain:

* project notes
* current decisions
* superseded decisions when historically important
* patterns
* research findings
* open questions
* important session landmarks
* links across projects and evidence

Do not project every raw session.

Use ordinary Markdown, simple properties, and standard links.

Generated content must not overwrite human-authored content outside managed regions.

First milestones

M0: Workshop

* toolchain manifest
* skill manifest
* MCP profiles
* repository instructions
* doctor command

M1: Sessions

* start
* close
* list
* show
* durable structured records
* deterministic repository metadata

M2: Resume

* recent sessions
* unfinished work
* current knowledge
* stale-knowledge warnings
* evidence links
* Claude-to-Codex and Codex-to-Claude portability

M3: Obsidian projection

* preview generated notes
* publish approved promoted knowledge
* project notes
* Bases-compatible properties
* links across projects and knowledge

M4: Temporal-index experiment

* Graphiti adapter
* derived episode ingestion
* retrieval comparison
* provenance preservation
* removal path
