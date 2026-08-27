# PLAN

Outcome

Define and validate the smallest useful Bindle vertical slice.

Current

Repository baseline integrity is promoted: `main` is protected via an active ruleset and changes land through PR review. `bash scripts/check.sh` is the canonical local repository verification gate, and GitHub Actions CI (`.github/workflows/ci.yml`) reruns it as a required check on each PR revision, not as the first execution of these checks. The Obsidian Mind (`om`) trial is closed (docs/DECISIONS.md D028); no standing cross-project memory system replaces it. The repo-orientation → brainstorming → slice-plan → implementation → slice-review → slice-retro → next-best-slice sequence is retired as this repository's canonical/default workflow (docs/DECISIONS.md D029); the individual skills remain available ad hoc. A replacement discovery/planning/execution coordination model is under exploration, not adopted. Both guardrail layers (Git hooks and the Claude Code PreToolUse guard) are repo-local and opt-in, with no remaining Bindle-owned global guardrail configuration (docs/DECISIONS.md D032); `bindle init`/`bindle remove` drive both layers for the current repository, from a normally installed `bindle` package as well as `uv run`. `bindle init --projectmem` additionally ensures Projectmem is initialized for the repository through its own native `pjm init` CLI, and `bindle remove` never touches Projectmem's state (docs/DECISIONS.md D033) — the first slice to exercise a second, differently-shaped provider-lifecycle seam alongside guardrails. `bindle skills list|status|add|remove` (docs/DECISIONS.md D035) manages skill kits — `software-engineering` and `spec-kit` — through each harness's own native mechanism, with repository desired state in `bindle.toml`; this is the third, again differently-shaped provider-lifecycle seam, still no generic Component/Provider abstraction. `bindle init --qmd` (docs/DECISIONS.md D036) additionally ensures a project-local QMD retrieval index exists over the repository's own durable Markdown, through QMD's own native CLI — a fourth provider-lifecycle seam, the first concrete instance of docs/SCOPE.md's M4 ("derived indexing experiment"), never touched by `bindle remove`. `bindle status` reports read-only Git/Claude guardrail, Projectmem, and QMD adoption state for the current repository. Every other lifecycle command remains a stub. Symphony is now recorded as a referenced (not vendored, not executed) external component for the coordination pillar below — a canonical fork and pinned revision live in docs/SYMPHONY.md (docs/DECISIONS.md D037); `bindle` has no command, config, or code touching Symphony yet.

Next

1. Skill-kit lifecycle (docs/DECISIONS.md D035) is now established for `software-engineering` and `spec-kit`. No further skill-kit work is queued — revisit only on demonstrated need (a third kit, a real staleness/update pain point, richer status), per D035's own closing precedent, not speculatively.
2. QMD retrieval (docs/DECISIONS.md D036) is now established as a repository-scoped opt-in. No further QMD work is queued — a `bindle search` wrapper, embeddings orchestration, or agent-prompt retrieval wiring each wait on demonstrated need, not speculative build-out, mirroring D035's own closing precedent.
3. A durable implementation-work model is now specified, not yet adopted: `specs/001-durable-work-ledger/` (spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md, tasks.md) proposes a Bindle-owned coordination ledger (orthogonal status/blocking/claim/evidence facts, backed by a single small SQLite database, untracked at the Git common directory — mirroring Projectmem/QMD's own storage location, though not their plain-file storage shape) that a future, disposable projection materializes for Symphony. (2026-08-26: the storage-format decision was revised from an earlier, now-superseded plain-per-item-TOML-file design to SQLite — see `specs/001-durable-work-ledger/research.md`'s "Decision: storage format" for the full rationale and the preserved original decision.) `plans/active/2026-08-24-symphony-coordination-exploration.md`'s 2026-08-26 addendum records the corrected build sequence: adopt this model → build the ledger → define the Symphony projection → only then implement Symphony execution integration (tracker-adapter/worker-harness patch, `bindle init` wiring) — reversing this line's own prior, now-superseded assumption that "work items are loaded... manually" could precede a durable model. This remains specification, not adoption: no tool, schema, or storage engine here is standing repository policy until a `docs/DECISIONS.md` entry adopts it, expected only once a first implementation slice is built and observed working (the same bar D033/D035/D036 each met before their own decision entries). (2026-08-26: task generation, originally deferred for this feature — see `specs/001-durable-work-ledger/plan.md`'s "task-generation scope correction" — is now lifted; `tasks.md` exists and a task-composition/orchestration analysis has been run over the resulting task graph. The resulting S1–S7 delivery-slice composition, the resolved T022 fixture-construction ambiguity, and the recommended execution waves are persisted in `plans/active/2026-08-26-work-ledger-task-composition-handoff.md` for resumption by a fresh session. No implementation task has been dispatched or started from it.)
4. Implement the first evidence-block emission path — deterministic emission from git state, embedding into a provider-owned record, list/show of emitted blocks — as the first concrete piece of M1.
5. Begin the first vertical slice implementation once M1 emission lands.

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
