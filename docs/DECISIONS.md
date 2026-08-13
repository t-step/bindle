
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

Claude Code and Codex may use no more than five concurrent subagents.

Amended 2026-08-11: the ceiling was raised from three to five after two weeks of practice showed audit fan-outs routinely queuing behind the lower cap. Enforcement (the `subagent-limit-guard` hook default) was updated in the same change.

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

D019: Promotion is a checkpoint, not a routine

Cross-project capture is prompted at natural boundaries, not per session.

The trial's original capture phrasing named destinations ("route session narratives worth keeping…") but no moment at which routing would happen; across the first trial period it produced zero durable memories while genuine cross-project lessons went unpromoted. Promotion to the vault is therefore prompted only at natural boundaries — an experiment concludes, a retrospective is written, a substantial design or engineering review ends, or the same lesson surfaces in a second project — and the prompt is a question, not an obligation: would this lesson change decisions in another repository or a future project? A "no" writes nothing. No per-session capture, no broad backfill, no automatic promotion. D016 is unchanged; this decision supplies the checkpoint at which D016's reason is actually checked.

Deployment: for Claude Code the live copy of this rule sits in the user-global `~/.claude/CLAUDE.md` (accepted placement: the rule is cross-project by nature, and the global file is what Claude reads in every repository); consuming repositories' AGENTS.md trial sections carry the same wording per D017 where the trial snippet is applied.

D020: Code intelligence trial concluded — dropped, not promoted

The code-review-graph trial from D008 is dropped.

Evaluated 2026-08-12. The server (registered globally as `codebase-memory-mcp`, not per-repository as D008 originally envisioned) was actually indexing two real repositories — Valence and cover-story, not CHILmesh, the originally named target, which was never indexed — and both indexes were kept current to exact HEAD by a mechanism outside any logged session. A string search for the tool's name across session transcripts initially suggested real usage, but that was a false positive: it was matching the tool being *listed* as available, not invoked. A rigorous parse of every session's actual `tool_use` blocks, across all 96 Valence sessions and all 5 cover-story sessions (101 total, spanning 2026-08-02 through 2026-08-12), found zero real invocations of any codebase-memory-mcp tool, and zero `ToolSearch` queries ever looking for it — despite the server being available in the near totality of those sessions. <!-- private-ok: Bindle's own repo/decision names, not personal info -->

D007 (graphs are derived, never canonical) and D008 (code intelligence is project-scoped, not loaded by default) remain correct policy; this decision only concludes the specific trial. No code intelligence MCP is currently documented as adopted. A future candidate must clear a higher bar than availability before being documented as adopted: demonstrated use, checked by the same method (a real session audit, not a sample query) — a plausible-looking single query was not sufficient evidence on its own and nearly produced the wrong conclusion here.

D021: CodeGraph adoption gate — failed, not adopted

CodeGraph (github.com/colbymchenry/codegraph) was evaluated as a candidate to fill the role D020 left open, and failed its gate.

Rather than repeat D020's mistake (deploy broadly, hope it gets used, find out much later), the candidate was gated on a single controlled benchmark before any standing deployment — see the concluded plan at plans/archive/2026-08-12-codegraph-agent-eval-gate.md for full method and numbers. Run 2026-08-12 in Valence: 4 real questions grounded in Valence's actual codebase (a cross-app publish flow, a blast-radius question, a route trace, a caller-dependency question), 2 arms (CodeGraph-assisted vs. baseline grep/read/bash), contamination-checked. CodeGraph cut tool calls by 71% (7 vs. 24) but cost 64% *more* ($0.6611 vs. $0.4024) — its responses bill at cache-write rates while baseline benefits from cheap cache-read reuse, so fewer tokens and fewer calls still cost more. It also hallucinated a wrong answer on the single most representative question (falsely claimed no code path from the web app to a HuggingFace-publish function that in fact exists), while getting a closely related question right — a reliability failure, not a fixed blind spot.

Worth stating plainly: CodeGraph's own disclosed README benchmark claims "44% cheaper." This real-world test found the opposite. A benchmark with genuinely disclosed methodology can still not hold in a specific target repo — evaluate empirically in the actual context that matters, not on a vendor's published numbers, however well-sourced.

CodeGraph was fully uninstalled and unregistered from Valence and global Claude Code config; nothing was left standing. D007 and D008 remain the governing policy; no code intelligence MCP is currently adopted anywhere. The next candidate, if one appears, clears the same gate before any standing deployment — not the other way around.

D022: projectmem promoted from trial to accepted

projectmem is accepted as Bindle's local operational memory layer. No longer documented as a trial.

Running since 2026-08-01 across bindle, Valence, cover-story, and skills. <!-- private-ok: Bindle's own repo/decision names, not personal info --> In bindle alone: 48 events by 2026-08-12 — dated, attributed gotchas and decisions, an issue/fix pair — substantive content, not noise, plus a demonstrated real hit: the churn/stale-memory-citation check at commit time correctly flagged this repository's own decision-log and AGENTS.md citations as due for a re-check during today's commits.

This changes projectmem's documented status, not its epistemic weight. It remains branch-blind (events carry only a HEAD SHA, no branch or worktree awareness — docs/DATA-OWNERSHIP.md), its content stays working notes rather than accepted truth, and it remains optional and machine-local: no contributor may be assumed to have it installed or registered, and durable decisions still route to docs/DECISIONS.md, never to projectmem alone. "Accepted" means Bindle formally keeps using it as part of the workflow — it does not mean its recorded content becomes authoritative.

D023: Obsidian Mind promoted from trial to accepted

obsidian-mind/om is accepted as Bindle's durable-knowledge and work-record vault. No longer documented as a trial.

The interop audit (2026-08-02, plans/active/2026-08-02-obsidian-mind-interop-audit.md) and the five-session checkpoint (2026-08-11) found the vault, templates, write behavior, and retrieval stack genuinely provider-neutral and safe for shared writes, with real consumption already observed (a memory recorded 08-05 got its first real recall hit on 08-11). One structural gap remains, and is accepted as a known limitation rather than a pending trial item: Codex's MCP client sends no `roots` capability, and om derives caller identity exclusively from that handshake, so every Codex session is an anonymous caller — project-scoped recall is invisible, writes fall to the vault inbox. This is not fixable by configuration; closing it needs a roots-injecting MCP proxy or an upstream om change. Until then, Codex sessions should prefer `om search` over `recall` and must not work around the gap silently.

D019 (capture is a checkpoint, not a routine) is unchanged and continues to govern when anything gets written. D016 (preservation requires a reason) and the routing table in docs/DATA-OWNERSHIP.md are unchanged: durable decisions still go to docs/DECISIONS.md alone, never only to the vault. "Accepted" means Bindle formally keeps using om as the cross-project knowledge layer with its Codex gap documented as a known limitation — not that the gap is resolved, or that vault content becomes authoritative on its own.

Deployment note, not resolved here: the om trial section in AGENTS.md ("Obsidian Mind trial (temporary)") is renamed "Obsidian Mind" in this repository. Per D017, consuming repositories carrying the same trial snippet (Valence, cover-story, and any others) need the equivalent wording update in their own AGENTS.md — out of scope here, since Bindle does not modify sibling repositories. <!-- private-ok: Bindle's own repo/decision names, not personal info --> D019's live global copy in the user's `~/.claude/CLAUDE.md` may also carry trial-status language of its own worth reviewing — also out of scope for a repository-local edit.
