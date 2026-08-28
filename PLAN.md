# PLAN

Outcome

Define and validate the smallest useful Bindle vertical slice.

Current

Repository baseline integrity is promoted: `main` is protected via an active ruleset and changes land through PR review. `bash scripts/check.sh` is the canonical local repository verification gate, and GitHub Actions CI (`.github/workflows/ci.yml`) reruns it as a required check on each PR revision, not as the first execution of these checks. The Obsidian Mind (`om`) trial is closed (docs/DECISIONS.md D028); no standing cross-project memory system replaces it. The repo-orientation → brainstorming → slice-plan → implementation → slice-review → slice-retro → next-best-slice sequence is retired as this repository's canonical/default workflow (docs/DECISIONS.md D029); the individual skills remain available ad hoc. A replacement discovery/planning/execution coordination model is under exploration, not adopted. Both guardrail layers (Git hooks and the Claude Code PreToolUse guard) are repo-local and opt-in, with no remaining Bindle-owned global guardrail configuration (docs/DECISIONS.md D032); `bindle init`/`bindle remove` drive both layers for the current repository, from a normally installed `bindle` package as well as `uv run`. `bindle init --projectmem` additionally ensures Projectmem is initialized for the repository through its own native `pjm init` CLI, and `bindle remove` never touches Projectmem's state (docs/DECISIONS.md D033) — the first slice to exercise a second, differently-shaped provider-lifecycle seam alongside guardrails. `bindle skills list|status|add|remove` (docs/DECISIONS.md D035) manages skill kits — `software-engineering` and `spec-kit` — through each harness's own native mechanism, with repository desired state in `bindle.toml`; this is the third, again differently-shaped provider-lifecycle seam, still no generic Component/Provider abstraction. `bindle init --qmd` (docs/DECISIONS.md D036) additionally ensures a project-local QMD retrieval index exists over the repository's own durable Markdown, through QMD's own native CLI — a fourth provider-lifecycle seam, the first concrete instance of docs/SCOPE.md's M4 ("derived indexing experiment"), never touched by `bindle remove`. `bindle status` reports read-only Git/Claude guardrail, Projectmem, and QMD adoption state for the current repository. Every other lifecycle command remains a stub. Symphony is now recorded as a referenced (not vendored, not executed) external component for the coordination pillar below — a canonical fork and pinned revision live in docs/SYMPHONY.md (docs/DECISIONS.md D037). `specs/003-symphony-task-integration/` (docs/DECISIONS.md D039) now gives Bindle its first real path toward Symphony: `bindle work load-speckit` idempotently loads a settled Spec Kit tasks.md into the durable ledger as `type='task'` work items; `bindle work publish` regenerates a published, independently versioned, read-only SQLite export (`contracts/symphony-projection-v1.md`) distinct from the internal ledger schema, containing task-only rows with a direct status and a derived `dispatchable` fact; `bindle work claim`/`release`/`done` give an external caller the smallest supported write surface over the ledger's own atomic primitives. A Symphony-side Bindle Tracker adapter now exists and has been independently proven end-to-end — entirely in the Symphony repository, with no Bindle-side code or schema change (docs/DECISIONS.md D041): it reads the published projection, arbitrates claims through Bindle's existing `bindle work claim`/`release`/`done` write surface with no CLI mocking, correctly holds a claimed task through continuation via a runtime fix separating the admission gate from the continuation gate (no re-claim, no premature release on a merely-no-longer-dispatchable item), and drives startup crash-recovery reconciliation and downstream chain advancement (an agent-triggered `done` auto-followed by `publish` unblocking the next dependent task) — proven against a real, disposable Bindle repository (Bindle `main` @ `dace8f68`, Symphony `development` @ `f0029ef`). Milestone scheduling and Bindle itself installing, building, or supervising Symphony remain explicitly out of scope; no `bindle init`/status/launch surface for Symphony exists or is planned without further demonstrated need. `specs/004-milestone-review-surface/` (docs/DECISIONS.md D042) adds the human milestone-acceptance seam as a CLI presentation layer (`bindle milestone review|list|enter-review|claim|release|accept|decline`) over the review lifecycle `specs/002-milestone-task-work-items/` already implemented and tested: readiness is computed and shown, never persisted; child task status, blocking, and full evidence pointers are inspectable; accept/decline are explicit human transitions that may optionally record a rationale-locator evidence pointer as a second, separately committed write whose failure never invalidates an already-recorded decision. This surface and the task-facing `bindle work` surface remain structurally separate command groups, each exposing no mutation of the other's work-item type.

Next

1. Skill-kit lifecycle (docs/DECISIONS.md D035) is now established for `software-engineering` and `spec-kit`. No further skill-kit work is queued — revisit only on demonstrated need (a third kit, a real staleness/update pain point, richer status), per D035's own closing precedent, not speculatively.
2. QMD retrieval (docs/DECISIONS.md D036) is now established as a repository-scoped opt-in. No further QMD work is queued — a `bindle search` wrapper, embeddings orchestration, or agent-prompt retrieval wiring each wait on demonstrated need, not speculative build-out, mirroring D035's own closing precedent.
3. The durable work ledger is implemented, verified, and adopted as standing policy (docs/DECISIONS.md D038), extended by the Spec Kit loader, published Symphony-facing projection, and narrow claim/release/done write surface in `specs/003-symphony-task-integration/` (docs/DECISIONS.md D039), and by the milestone review surface (docs/DECISIONS.md D042). SQLite here belongs to Bindle, not Symphony — the published projection is a disposable, regenerated export, never a live view into Bindle's own internal ledger file. The Symphony-side Tracker adapter is built and a real end-to-end execution path (dispatch through Symphony, execute, claim/continue/release, reconcile the result back) is independently proven — entirely in the Symphony repository, no Bindle-side change (docs/DECISIONS.md D041). `plans/archive/2026-08-26-coordination-current-framing.md`'s open items are resolved by this except its own item 5, left as a deliberate open question, not adopted work: whether Bindle ever needs a CLI lifecycle surface (`init`/status/launch) for Symphony. No such surface exists or is planned without further demonstrated need.
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
