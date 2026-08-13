# SCOPE

## Purpose

Bindle is a stateless toolchain bridge for engineering work performed across Claude Code, Codex, repositories, and projects (docs/PHILOSOPHY.md).

It moves context and evidence between tools that already own their domains. The knowledge vault, the harnesses, git, and repository memory tooling remain the stores; Bindle helps work cross the seams between them.

Core loop, stated as seam crossings

capture — deterministic evidence stamped at a session boundary, embedded in a record another system owns
→ promote — working reasoning routed into the store that owns durable knowledge, only with a reason (D016)
→ project — selected knowledge emitted into human surfaces the owning systems maintain
→ resume — bounded context assembled from provider-owned records through supported interfaces

Bindle owns

* toolchain manifests, doctor checks, and drift diagnosis
* evidence-block formats and their deterministic emission
* pointers and provenance links between provider-owned records
* lightweight adapters, hooks, templates, and commands at tool seams
* bounded resume-context assembly from provider-owned records
* selective projection emission (the receiving surface owns the result)

Bindle may later own

* context assembly across sessions and repositories
* contradiction or stale-knowledge warnings derived from evidence blocks
* temporal indexing adapters (derived, disposable)
* an optional Graphiti integration (a provider experiment, removable)
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
* notes, transcripts, embeddings, or narrative session records
* canonical project memories or user knowledge
* release automation as a product other projects delegate to (ordinary CI, versioning, tagging, or packaging for Bindle's own repository is a separate question and is not excluded by this — docs/TOOLCHAIN.md, "Release policy")
* telemetry platforms
* security scanning
* a generic project-management system

Bindle-owned state

Bindle is stateless with respect to user history (D015). Its own state, under `BINDLE_HOME` (default `~/.local/share/bindle`), is limited to:

* configuration
* disposable cache, rebuildable from providers at any time
* explicit exports the user asked for

There is no Bindle sessions store, memories store, or index database that acts as the only copy of anything. Durable artifacts live with their owners: decisions in repository decision logs, knowledge in the vault, transcripts with the harnesses, history in git.

The Obsidian vault is a projection and human-curation surface owned by the vault, not by Bindle.

Graph databases and semantic indexes are derived and replaceable.

Evidence blocks

An evidence block is an immutable observation that work occurred at a specific place and code state. Field list and worktree semantics live in docs/WORKTREES.md; in summary a block records repository identity (git common directory, remote), execution identity (worktree path), code state (HEAD SHA, dirty summary, detached flag), branch as descriptive context, timestamps, agent, and optional pointers (transcript, thread, PR).

Blocks are embedded in records other systems own — a vault work record, a handoff file, a commit message. Bindle emits them; it does not accumulate them.

An evidence block is not automatically durable project guidance.

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

These are the fixed milestone labels PLAN.md and docs/DECISIONS.md cite. Current status and next-step sequencing live in PLAN.md, not here.

M0: Workshop — done. Toolchain policy and MCP recommendations as prose in docs/TOOLCHAIN.md (not separate manifest files: `config/skills.yaml` and `config/mcp-profiles.yaml` were added, then deliberately removed once neither tool ever consumed them as data), repository instructions, doctor command.

M1: Evidence — schema done (docs/WORKTREES.md: fields and worktree semantics). Not yet built:

* deterministic emission from git state
* embed into provider-owned records (vault work record, handoff file, commit message)
* list and show blocks Bindle has emitted (disposable cache, rebuildable)

M2: Resume — not started.

* recent sessions
* unfinished work
* current knowledge
* stale-knowledge warnings
* evidence links
* Claude-to-Codex and Codex-to-Claude portability

M3: Obsidian projection — not started. The vault and the om MCP server are on active trial (demoted from adopted, D025) as the intended write target; generation and publication into it are not built.

* preview generated notes
* publish approved promoted knowledge
* project notes
* Bases-compatible properties
* links across projects and knowledge

M4: Temporal-index experiment — not started. Governed by the same derived-not-canonical graph policy (D007) that governed the separate code-intelligence graph trials concluded in D020 (dropped) and D021 (adoption gate failed) — those trials evaluated structural code graphs, not Graphiti, so they set a precedent for the evaluation bar rather than substitute for one.

* Graphiti adapter
* derived episode ingestion
* retrieval comparison
* provenance preservation
* removal path
