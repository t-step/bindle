
# DECISIONS

D001: Native coding harnesses

Claude Code and Codex remain the native execution harnesses.

Bindle will not implement a generic agent loop or model router.

Where Bindle needs equivalent behavior across harnesses, it should prefer mechanisms both harnesses already defer to — git hooks, repository configuration, filesystem conventions — over harness-specific hook systems. A thin per-harness adapter (a Claude Code hook, a Codex equivalent) is justified only when a capability has no portable equivalent, such as injecting context at session start.

D002: Repository tooling precedence

Repository-present tools and instructions take precedence over project-scoped and global skills.

D003: Dedicated Obsidian vault

Bindle may project knowledge into a dedicated engineering vault.

The user’s personal vault remains separate.

D004: Structured canonical state

Sessions and promoted knowledge remain canonical outside Obsidian.

The Obsidian vault is a human-readable projection.

D005: No broad ontology

Bindle will begin with sessions, memories, lightweight links, and promotion state.

It will not require a domain ontology.

D006: Promotion lifecycle

The initial lifecycle is:

observed → candidate → current → superseded

Agents may propose promotion. Human approval remains authoritative initially.

D007: Graphs are derived

Graphiti, code-review-graph, Graphify, or future graph systems do not own canonical project knowledge.

They are replaceable indexes or analysis tools.

D008: Code intelligence is project-scoped

code-review-graph is trialed only in repositories large enough to benefit.

It is not loaded by default.

D009: Local Markdown planning

Planning defaults to repository-local Markdown.

GitHub Issues remain optional.

D010: Conventional Commits

Bindle uses Conventional Commits.

Cocogitto validates commit messages.

Release automation remains deferred.

D011: Subagent ceiling

Claude Code and Codex may use no more than three concurrent subagents.

Only the primary agent may delegate.

Nested delegation is prohibited.

D012: Secret-bearing files are inaccessible

Agents must not read or reveal .env files, local environment overrides, credential files, private keys, or secret directories.

D013: Showcasing is part of completion

Meaningful work should preserve enough evidence to produce a clear walkthrough, diagram, benchmark, scientific figure, or demonstration.

D014: Blocks and pointers, never parsers

No Bindle code may parse another tool’s store; it may only emit blocks others embed and hold pointers others resolve.

This is the replaceability law: losing or swapping a provider (harness, memory tool, vault, index) may cost Bindle pointers, but must never break it. Bindle may call supported interfaces; it may never read a provider's private datastore directly.

D015: Durability

Every durable artifact lives with the system that naturally owns it.

Bindle-owned runtime state is limited to configuration, disposable cache, and explicit export. Nothing under Bindle's control may be the only copy of user history.

D016: Preservation requires a reason

Not every thought deserves to be preserved.

Temporary exploration, conversational branches, and intermediate reasoning remain in transcripts or scratch space and are allowed to disappear. Durable capture requires a reason: an accepted decision, a significant attempt or failure or fix, a reusable cross-project lesson, a meaningful work record, a stable handoff boundary, or a reproducible verification result.

D017: One authoritative copy of policy

AGENTS.md is the provider-neutral instruction set and the single authoritative copy of working policy. CLAUDE.md is a thin Claude-specific bridge that defers to it. Provider-native auto-memory is soft recall, never project authority. Claude Code and Codex write durable summaries and handoffs to one shared location, never to competing per-provider stores.

D018: Worktree identity

Repository identity is the Git common directory plus stable remote metadata. Execution identity is the absolute worktree path. Code-state identity is commit SHA plus dirty state. Branch names are descriptive context, never primary identity. No Bindle feature may assume one checkout per repository.
