# SCOPE

## Purpose

Bindle is a stateless toolchain bridge for engineering work performed across coding harnesses, repositories, and projects (`docs/PHILOSOPHY.md`).

Claude Code and Codex are the currently supported execution harnesses.

Bindle moves context and evidence between tools that already own their domains. Harnesses, Git, repository memory, and knowledge systems remain the stores; Bindle helps work cross the seams between them.

The core loop is expressed as seam crossings:

capture → promote → project → resume

* capture — deterministic evidence stamped at a work boundary and embedded in a record another system owns
* promote — working reasoning routed into the system that owns durable knowledge, only with a reason (D016)
* project — selected knowledge emitted into human-facing surfaces maintained by owning systems
* resume — bounded context assembled from provider-owned records through supported interfaces

## Bindle owns

* toolchain manifests, doctor checks, and drift diagnosis
* evidence-block formats and deterministic emission
* pointers and provenance links between provider-owned records
* lightweight adapters, hooks, templates, and commands at tool seams
* bounded resume-context assembly from provider-owned records
* selective projection emission; the receiving system owns the result

## Bindle may later own

* context assembly across sessions and repositories
* contradiction or stale-knowledge warnings derived from evidence
* optional derived temporal or semantic indexing adapters
* cross-harness bootstrap and doctor workflows, preferring portable repository-level mechanisms where possible

Experimental providers or integrations do not become part of Bindle’s permanent scope merely by being evaluated or adopted temporarily.

## Bindle does not own

* coding-agent execution
* model routing
* sandboxing
* subagent orchestration
* code editing
* browser automation
* external documentation retrieval
* canonical code graphs
* Git history
* GitHub issue tracking
* scientific-computing frameworks
* note-taking systems
* canonical notes, transcripts, embeddings, project memories, or user knowledge
* release automation for other projects
* telemetry platforms
* security scanning
* generic project management

Bindle may interact with these systems through supported interfaces without becoming their owner.

## Bindle-owned state

Bindle is stateless with respect to user history (D015).

State under BINDLE_HOME is limited to:

* configuration
* disposable cache that can be rebuilt from owning providers
* explicit exports requested by the user

There is no Bindle sessions store, memories store, or index database that acts as the only copy of durable information.

Durable artifacts remain with their natural owners. Decisions belong in repository decision logs, knowledge in approved knowledge systems, transcripts with execution harnesses, and source history in Git.

Projection and human-curation surfaces remain owned by their receiving systems, not by Bindle.

Graph databases, semantic indexes, and similar retrieval structures are derived and replaceable.

## Evidence blocks

An evidence block is an immutable observation that work occurred at a specific place and code state.

Its schema, repository identity rules, and worktree semantics live in docs/WORKTREES.md.

Evidence blocks may be embedded in records owned by other systems, such as knowledge records, handoff files, or commits.

Bindle emits evidence blocks; it does not accumulate them as canonical history.

An evidence block establishes provenance. It is not automatically durable project guidance or promoted knowledge.

## Promotion

Use a small lifecycle:

observed → candidate → current → superseded

Promotion should initially be:

* explicit
* proposed by the agent
* approved or edited by the user

Temporary reasoning does not need promotion merely because it exists.

Do not invent a broad ontology.

## Projection

Bindle may emit selected, human-useful knowledge into approved projection and curation surfaces.

Projection is selective. Do not project every raw session, command, transcript, or intermediate attempt.

Projected material may include:

* project notes
* current decisions
* historically important superseded decisions
* patterns
* research findings
* open questions
* important work landmarks
* links across projects, evidence, and knowledge

The receiving system owns the projected result.

Generated content must not overwrite human-authored content outside clearly managed regions.

For Markdown-based knowledge surfaces such as Obsidian, prefer ordinary Markdown, simple properties, and standard links. Use provider-specific features only when they add clear value without making the durable content unnecessarily dependent on that provider.

Initial publication should be preview-first and approval-based.

## Milestones

These labels define the stable product decomposition. Current status, sequencing, and active work live in PLAN.md.

### M0: Workshop

Establish repository instructions, toolchain policy, diagnostics, development conventions, and the boundaries required to build Bindle safely.

### M1: Evidence

Emit deterministic evidence describing work and code state into provider-owned records while preserving provenance and worktree identity.

### M2: Resume

Assemble bounded context from provider-owned records to support resuming work across sessions, repositories, and supported execution harnesses.

### M3: Projection

Emit selected promoted knowledge into human-facing knowledge and curation surfaces without transferring canonical ownership to Bindle.

### M4: Derived indexing experiment

Evaluate optional derived indexing for retrieval, contradiction detection, or stale-knowledge discovery while preserving provenance, replaceability, and a clean removal path.

Any provider evaluated for this milestone remains an implementation choice rather than part of Bindle’s fundamental scope.

## Scope test

Before adding a capability to Bindle, ask:

1. Who naturally owns the underlying information or behavior?
2. Can that owner be replaced without losing durable Bindle-owned truth?
3. Does the proposed information deserve to survive beyond the work that produced it?
4. Is Bindle crossing a tool seam, or absorbing another tool’s responsibility?

If the capability requires Bindle to become the canonical owner of another system’s domain, it is outside scope unless the architecture and scope are deliberately revised.

Proposals that survive this screen must pass the full feature-admission test in `docs/PHILOSOPHY.md`.
