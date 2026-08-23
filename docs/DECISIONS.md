# DECISIONS

This is the append-only decision log for Bindle.

Later decisions may amend, supersede, or reverse earlier ones. Earlier entries remain intact as historical records; the latest applicable decision governs.

## D001: Native coding harnesses

Claude Code and Codex remain the native execution harnesses.

Bindle will not implement a generic agent loop or model router.

Where equivalent behavior is required across harnesses, prefer portable mechanisms both already defer to, such as Git hooks, repository configuration, and filesystem conventions. Use thin harness-specific adapters only where no portable mechanism provides the required capability.

## D002: Repository tooling precedence

Repository-present tools and instructions take precedence over project-scoped skills, global skills, and generic defaults.

Inherit first. Extend second. Replace deliberately. Invent last.

## D003: Dedicated knowledge vault

Bindle may project selected engineering knowledge into a dedicated knowledge vault.

The user's personal vault remains separate.

## D004: Canonical state remains with owners

Sessions, promoted knowledge, Git history, and other durable artifacts remain canonical with the systems that naturally own them.

Knowledge surfaces such as Obsidian are projection and human-curation surfaces, not Bindle-owned canonical stores.

## D005: No broad ontology

Bindle will use only the minimal lifecycle and relationships required by the workflow.

It will not require or invent a broad domain ontology.

## D006: Promotion lifecycle

The initial promotion lifecycle is:

`observed → candidate → current → superseded`

Agents may propose promotion. Human approval remains authoritative initially.

## D007: Graphs and indexes are derived

Graphiti, code-intelligence graphs, semantic indexes, and future graph systems do not own canonical project knowledge.

They are derived, replaceable analysis or retrieval providers.

## D008: Code intelligence is project-scoped

Code-intelligence providers, when evaluated, are project-scoped rather than loaded by default.

Availability does not imply adoption.

Later evaluation outcomes are recorded in D020 and D021.

## D009: Local Markdown planning

Planning defaults to repository-local Markdown.

GitHub Issues remain optional and should be used when collaboration, review, notification, or external tracking makes them useful.

## D010: Conventional Commits

Bindle uses Conventional Commits.

Cocogitto validates commit messages.

Bindle's own CI and release infrastructure are ordinary repository concerns and may evolve independently of whether release automation is part of the Bindle product.

## D011: Five-subagent ceiling

Claude Code and Codex may use no more than five concurrent subagents.

Only the primary agent may delegate. Nested delegation is prohibited.

The limit applies regardless of provider-specific enforcement or fan-out mechanism.

This ceiling was raised from three to five on 2026-08-11 after routine audit fan-outs repeatedly queued behind the lower limit.

## D012: Secret-bearing files are inaccessible

Agents must not read, print, search, summarize, modify, copy, or transmit `.env` files, local environment overrides, credential files, private keys, secret directories, or equivalent secret-bearing material.

Configuration should be understood through documentation, examples, templates, and variable names rather than secret values.

## D013: Showcasing is part of meaningful completion

Meaningful work should preserve enough evidence to communicate what changed and how it was verified.

Applicable evidence may include walkthroughs, diagrams, screenshots, traces, benchmarks, scientific figures, verification output, tradeoffs, and known limitations.

## D014: Blocks and pointers, never private-store parsers

No Bindle code may parse another provider's private or internal datastore.

Bindle may:

- call supported interfaces
- emit portable blocks that other systems embed
- hold pointers that owning systems resolve

This is the replaceability rule. Replacing or removing a provider may invalidate pointers, but must not invalidate Bindle-owned durable truth or require Bindle to understand that provider's private storage format.

## D015: Durability remains with natural owners

Every durable artifact lives with the system that naturally owns it.

Bindle-owned runtime state is limited to configuration, disposable cache, and explicit export.

Nothing under Bindle's control may be the only copy of user history.

## D016: Preservation requires a reason

Not every thought deserves to be preserved.

Temporary exploration, conversational branches, speculative ideas, and intermediate reasoning may remain in transcripts or scratch space and disappear.

Durable capture requires a reason, such as:

- an accepted project decision
- a significant attempt, failure, or fix
- a reusable cross-project lesson
- a meaningful work record
- a stable handoff boundary
- a reproducible benchmark or verification result

## D017: One authoritative copy of repository policy

`AGENTS.md` is the provider-neutral instruction set and the authoritative copy of repository working policy.

`CLAUDE.md` is a thin Claude Code-specific bridge and must not duplicate portable policy already expressed in `AGENTS.md`.

Provider-native auto-memory is soft recall, never repository authority.

Durable summaries, decisions, and handoffs must route to shared owning systems rather than competing provider-private stores.

## D018: Worktree identity

Bindle distinguishes:

- repository identity: Git common directory, with stable remote metadata when available
- execution identity: absolute worktree path
- code-state identity: full commit SHA plus dirty state
- branch: descriptive context only

No Bindle feature may assume one checkout per repository.

The Git common-directory path is machine-local identity, not a portable cross-machine identifier. Detailed semantics live in `docs/WORKTREES.md`.

## D019: Promotion is checkpoint-based, not routine

Cross-project capture is considered at natural boundaries rather than at the end of every session.

Examples include:

- an experiment concluding
- a retrospective completing
- a substantial design or engineering review ending
- the same lesson surfacing in another project

At such a boundary, ask whether the lesson would materially change decisions in another repository or future project.

A negative answer writes nothing.

There is no default per-session capture, broad historical backfill, or automatic promotion.

This decision operationalizes D016 by defining when the preservation question should be asked.

## D020: code-review-graph trial dropped

The code-review-graph trial concluded without adoption.

A session audit on 2026-08-12 examined actual tool invocations rather than textual mentions of the tool. Across the Valence and cover-story session history available for the audit, the provider had been available broadly but had no real tool invocations and no evidence that agents sought it out. <!-- private-ok: Bindle's own repo/decision names, not personal info -->

The initial search had produced a misleading positive signal because tool availability appeared in transcripts even when the tool was never used. The corrected audit parsed actual `tool_use` activity.

Conclusion:

- code-review-graph was dropped
- no code-intelligence MCP was adopted in its place
- availability alone is not evidence of value
- future candidates require demonstrated use or a controlled evaluation in representative repository work

D007 and D008 remain governing policy.

## D021: CodeGraph adoption gate failed

CodeGraph was evaluated as a replacement candidate after D020 and was not adopted.

The 2026-08-12 evaluation used four representative Valence questions across two arms: CodeGraph-assisted and repository-native baseline tooling.

The candidate reduced tool calls substantially but increased total measured cost and produced an incorrect answer on the most representative cross-application path question. The baseline was cheaper and correct on that case.

The detailed method and measurements are preserved in:

`plans/archive/2026-08-12-codegraph-agent-eval-gate.md`

Conclusion:

- CodeGraph was not adopted
- the provider was removed after the evaluation
- vendor benchmarks and lower tool-call counts are insufficient adoption evidence
- future code-intelligence candidates must demonstrate correctness and total-value improvement in the target repository before standing deployment

D007 and D008 remain governing policy.

## D022: projectmem accepted as operational project memory

projectmem is accepted as Bindle's machine-local operational project-memory layer.

The acceptance decision followed real use across multiple repositories beginning 2026-08-01, including substantive notes, decisions, issue/fix records, and useful retrieval during later work.

Acceptance defines workflow status, not epistemic authority.

projectmem remains:

- optional
- machine-local
- non-canonical
- unsuitable as the only copy of durable architecture or decisions

Tracked repository documentation remains authoritative.

Provider-specific limitations do not change this ownership model. Current operating guidance lives in `AGENTS.md` and `docs/TOOLCHAIN.md`.

## D023: Obsidian Mind initially promoted to accepted

Obsidian Mind (`om`) was promoted from trial to accepted status after its initial interoperability audit and five-session checkpoint.

The evaluation found its vault, templates, write behavior, and retrieval model usable across the intended workflow, with real retrieval of previously captured knowledge observed.

A provider limitation remained: Codex did not supply the MCP roots information `om` relied on for caller identity, leaving project-scoped recall incomplete from Codex.

The limitation was accepted at the time rather than treated as a blocker.

D019 and D016 continued to govern capture and promotion.

**Superseded by D025.**

## D024: Context7 MCP tracks `@latest`

Bindle deliberately configures Context7 using `@upstash/context7-mcp@latest` in both Claude Code and Codex MCP configuration.

Reviewed 2026-08-12.

The rationale is specific to this dependency:

- Context7 proxies live documentation whose content changes independently of the client version
- the package had a high release cadence
- pinning the client would not make returned documentation reproducible
- maintaining a rapidly stale isolated pin would add operational cost without providing the reproducibility normally sought from build-critical dependency pinning

This decision does not establish a general preference for unpinned dependencies.

Dependencies that affect build, test, or runtime determinism should still be pinned or locked when appropriate.

## D025: Obsidian Mind returned to trial

D023's promotion is reversed.

Obsidian Mind (`om`) returns to **Trial** status.

This is a readiness decision rather than evidence that the provider technically failed. The earlier interoperability findings remain historical evidence, but they are insufficient to establish current acceptance indefinitely.

The underlying provider limitations noted in D023 remain open trial considerations.

This decision changes status only. It does not itself remove:

- the vault
- `.om-project`
- local MCP registration
- trial artifacts

D016 and D019 remain unchanged.

Any future promotion must satisfy the adoption bar that exists at that time rather than inheriting acceptance from D023.

## D026: Vaporwave statusline tracked as a deliberate scope exception

The Vaporwave Claude Code statusline is tracked in this repository as a deliberate scope exception for portability and backup.

Tracking the statusline does not mean Bindle owns Claude Code presentation or depends on the script at runtime.

The artifact is:

- personal tooling
- repository-local
- optional
- outside `BINDLE_HOME`
- not installed or required by Bindle
- not precedent for unrelated personal tooling

The statusline plausibly resembles the lightweight adapters and tool-seam artifacts allowed by `docs/SCOPE.md`, but its inclusion was approved explicitly as an exception rather than used to broaden Bindle's general scope.

D027 later removes one companion mechanism originally included with this decision.

## D027: Vaporwave SessionEnd marker hook removed

The SessionEnd marker mechanism introduced alongside D026 was removed after empirical evidence showed it was unnecessary.

The original implementation assumed Claude Code appended across `/clear` boundaries and therefore required an external marker to reset TURN counting.

Observed transcript behavior contradicted that premise: `/clear` produced a fresh transcript/session, so the marker written under the previous session identifier could not affect the new transcript and was dead code.

The marker hook and corresponding lookup logic were removed.

The statusline now derives TURN directly from the active transcript.

D026 remains in force for tracking the statusline itself; D027 supersedes only the removed SessionEnd marker mechanism.
