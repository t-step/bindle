# DATA OWNERSHIP

Who owns what, where information routes, and how Claude Code and Codex share authority without fighting.

## Authority model

Durable project guidance lives in versioned repository files that both harnesses read. There is one authoritative copy of every policy.

1. `AGENTS.md` — provider-neutral working instructions. The single authoritative policy file.
2. `CLAUDE.md` — thin Claude-specific bridge. It defers to `AGENTS.md` and contains only what cannot be expressed portably. Codex reads `AGENTS.md` directly. Neither file restates the other's policy; a duplicated rule is a bug fixed by deleting one copy and pointing at the other.
3. `docs/DECISIONS.md` — accepted project decisions. Numbered, append-only, superseded in place rather than edited away.
4. `PLAN.md` and `plans/` — current intent.
5. Provider-native auto-memory (Claude Code's per-project memory, Codex's memory store) is soft recall only. It may make a session faster; it is never project authority, and nothing durable may live only there.

When a durable session summary or handoff is worth writing, Claude Code and Codex write it to the same shared location (see routing) — never to competing per-provider stores.

## Ownership table

| Category | Owner | Durability | Bindle's role |
| --- | --- | --- | --- |
| Git history | Git | durable | read via git commands |
| Collaboration record | GitHub | durable | hold pointers (PR, issue numbers) |
| Transcripts | Claude Code / Codex | retention-limited | pointer only, never a copy |
| Live session context | the harness | ephemeral | none |
| Working reasoning in a repo (issues, attempts, fixes) | projectmem (adopted, D022) | working notes — not truth | route to it; never parse its store |
| Accepted project decisions | `docs/DECISIONS.md` in each repository | durable | route to it |
| Cross-project lessons, durable personal knowledge | no standing provider — the obsidian-mind/om trial closed (docs/DECISIONS.md D028); a human or a narrowly scoped skill (e.g. `promote-learning`) synthesizes across projects deliberately, when a concrete need exists | not a durable store | none |
| Session narrative and work records | a dated repository handoff file under `plans/` | durable when reasoned | provide templates |
| Program structure | LSPs, code graphs | derived | none |
| Toolchain desired state | `docs/TOOLCHAIN.md` (policy/recommendations); `.mcp.json` and `.codex/config.toml` (unconditional MCP config, natively consumed) | durable | owned |
| Deterministic git evidence blocks | Bindle emits the format; owning records embed the block | derived from git at capture time | owned format — never an owned store |
| Bindle runtime state | `BINDLE_HOME` | configuration, disposable cache, explicit export only | owned |

## Routing table

| Information | Goes to | Never to |
| --- | --- | --- |
| Accepted project decision | `docs/DECISIONS.md` (repo-scoped); a vault decision record when personal and cross-repo | projectmem alone, chat, auto-memory |
| Significant attempt, failure, or fix | projectmem as a working record; promote the durable lesson explicitly | projectmem's summary treated as settled truth |
| Temporary exploration, speculative branches | transcript or scratch space — allowed to disappear | any durable store |
| Session narrative worth keeping | a dated handoff file under `plans/` | per-provider session summaries |
| Cross-project lesson | deliberate human or skill-driven synthesis (e.g. `promote-learning`) when a concrete need exists — no standing cross-project store | projectmem global gotchas, provider auto-memory |
| Project instructions | `AGENTS.md` | `CLAUDE.md` duplicates, global skills |
| Personal preferences | provider-native memory (soft recall) | repository files |
| Deterministic git evidence | an emitted block embedded in the receiving record | prose reconstruction from memory |
| Transcripts | stay with the harness; record the pointer | copies in the vault or a repository |

## Durable versus derived

Durable: version-controlled repository files, vault notes, git history, explicit Bindle exports.

Derived and disposable: regenerated summaries, semantic indexes, dashboards, graph projections, caches, anything under Bindle's cache. Everything derived must be rebuildable from a durable source; deleting it loses nothing.

Trust boundary worth stating plainly: projectmem is branch-blind (events carry only a HEAD SHA — no branch, no worktree, no rewrite handling), so a note recorded on a later-abandoned branch survives as unqualified project memory. Treat its contents as leads, not conclusions; confirm material claims against git, the decision log, or source.

## When to preserve

Apply the preservation rule (`docs/PHILOSOPHY.md`): durable capture requires a reason — an accepted decision, a significant attempt/failure/fix, a reusable cross-project lesson, a meaningful work record, a stable handoff boundary, or a reproducible verification result. Everything else is allowed to disappear with the transcript.
