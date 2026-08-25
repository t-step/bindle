# PLAN

Outcome

Define and validate the smallest useful Bindle vertical slice.

Current

Repository baseline integrity is promoted: `main` is protected via an active ruleset and changes land through PR review. `bash scripts/check.sh` is the canonical local repository verification gate, and GitHub Actions CI (`.github/workflows/ci.yml`) reruns it as a required check on each PR revision, not as the first execution of these checks. The Obsidian Mind (`om`) trial is closed (docs/DECISIONS.md D028); no standing cross-project memory system replaces it. The repo-orientation → brainstorming → slice-plan → implementation → slice-review → slice-retro → next-best-slice sequence is retired as this repository's canonical/default workflow (docs/DECISIONS.md D029); the individual skills remain available ad hoc. A replacement discovery/planning/execution coordination model is under exploration, not adopted. Both guardrail layers (Git hooks and the Claude Code PreToolUse guard) are repo-local and opt-in, with no remaining Bindle-owned global guardrail configuration (docs/DECISIONS.md D032); `bindle init`/`bindle remove` drive both layers for the current repository, from a normally installed `bindle` package as well as `uv run`. `bindle init --projectmem` additionally ensures Projectmem is initialized for the repository through its own native `pjm init` CLI, and `bindle remove` never touches Projectmem's state (docs/DECISIONS.md D033) — the first slice to exercise a second, differently-shaped provider-lifecycle seam alongside guardrails. `bindle skills list|status|add|remove` (docs/DECISIONS.md D035) manages skill kits — `software-engineering` and `spec-kit` — through each harness's own native mechanism, with repository desired state in `bindle.toml`; this is the third, again differently-shaped provider-lifecycle seam, still no generic Component/Provider abstraction. `bindle status` reports read-only Git/Claude guardrail and Projectmem adoption state for the current repository. Every other lifecycle command remains a stub.

Next

1. Skill-kit lifecycle (docs/DECISIONS.md D035) is now established for `software-engineering` and `spec-kit`. No further skill-kit work is queued — revisit only on demonstrated need (a third kit, a real staleness/update pain point, richer status), per D035's own closing precedent, not speculatively.
2. Evaluate a provider-neutral implementation-work model, including a minimal repository-scoped local SQLite coordination ledger and selected Symphony-style scheduling semantics, before adopting a replacement workflow architecture. This is exploration, not adoption — no tool, framework, or schema from this evaluation is standing repository policy until a decision records it.
3. Implement the first evidence-block emission path — deterministic emission from git state, embedding into a provider-owned record, list/show of emitted blocks — as the first concrete piece of M1.
4. Begin the first vertical slice implementation once M1 emission lands.

Blocked

* Graphiti adoption waits on real session records and retrieval failures.
* Automated knowledge projection waits on a defined projection mechanism and preview quality (docs/SCOPE.md M3).
* Release automation waits on an installable product.

Later

* Session start, close, list, and show
* Resume-context assembly
* Promotion and supersession
* Obsidian projection
* Temporal-index comparison
* Toolchain bootstrap and drift repair (e.g., installing this repo's cog.toml git-hook pattern into other project repositories, so conventional-commit enforcement is consistent across repos without re-deriving it each time)

Recent decisions

See docs/DECISIONS.md.

plans/active/README.md

Active plans

This directory contains executable work packets for current outcomes.

Each plan should include:

* outcome
* why now
* scope
* evidence
* work
* verification
* decisions
* open questions
* showcase evidence

Completed plans move to ../archive/.

plans/archive/.gitkeep
