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

**Superseded by D028.**

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

## D028: Obsidian Mind trial closed — om removed from Bindle

The Obsidian Mind (`om`) trial that D023 accepted and D025 demoted back to trial is closed. **Supersedes D025.**

This is a workflow-cost decision, not a finding that om failed technically. The interoperability audit and five-session checkpoint that motivated D023's original promotion are unchanged and remain valid historical evidence, preserved (not deleted) in `plans/archive/`. The reversal is: the incremental value om supplied did not justify the dependency, operational, and evaluation overhead of running the experiment itself. Measuring and maintaining the trial — checkpoints, the gap register, routing-quality tallies, working around the Codex anonymous-caller gap — was competing with, not supporting, actual project progression.

Replacement operating model, effective immediately:

* projectmem (D022) remains the accepted repository-local operational memory layer; nothing about it changes here. It already covers enough project-local memory for this workflow.
* No standing cross-project memory system replaces om. Cross-project synthesis — the role om's `remember`/`recall` played — is deliberate and human-driven, or can be performed by a narrow, purpose-built skill when a concrete cross-project need actually emerges, rather than by a continuously installed memory system.
* No standing durable-knowledge vault dependency is adopted in its place. Cross-project aggregation does not currently require a continuously installed extra memory system. If a concrete future need appears, it should be solved from that need, not by reviving om speculatively.

Removed from this repository by this decision:

* The "Obsidian Mind trial" section of `AGENTS.md`.
* om-specific documentation in `docs/TOOLCHAIN.md` and `docs/DATA-OWNERSHIP.md`.

`.om-project` (the routing-label marker om used for per-worktree identity) was never committed to this repository's `main` and is not recreated by, or as a consequence of, this decision.

`plans/archive/2026-08-02-obsidian-mind-interop-audit.md`, `2026-08-02-om-trial-observation-plan.md`, and `2026-08-02-om-trial-runbook.md` are promoted into this repository's `plans/archive/` by this decision, content otherwise unchanged, preserving the historical audit/observation/runbook record so the sequence (trial → promotion consideration → D025 demotion → D028 closure) stays reconstructable.

Not covered by this decision, and intentionally out of scope here (consistent with D023/D025's own precedent that Bindle does not modify sibling repositories): other repositories' own instructions may still carry Obsidian Mind capture sections propagated under D017. Those repositories need their own equivalent update, tracked separately in each repository.

Any `om` MCP server registration in user-level Claude Code or Codex configuration, and the underlying vault and its tooling at the user's private Obsidian path, are outside this decision's scope (D015) — global configuration and user-owned data are not modified by this repository decision.

D016 and D019 remain unchanged and continue to govern preservation and promotion generally. D022 (projectmem) is unaffected.

## D029: No canonical discovery/planning/review workflow — the slice sequence is no longer a default

AGENTS.md and docs/TOOLCHAIN.md previously named repo-orientation → brainstorming → slice-plan → implementation → slice-review → slice-retro → next-best-slice as the default flow for substantial product work. A session-history audit of this machine's retained Claude Code transcripts for this repository found the flow essentially unexercised: it had close to zero observed invocations in retained usage history. Availability and a documented recommendation had not translated into actual use.

This decision removes the sequence's canonical/default status. The individual skills are unaffected — they remain installed and may still be invoked ad hoc when one genuinely fits a task — but AGENTS.md and docs/TOOLCHAIN.md no longer describe them as the workflow this repository defaults to.

This does not adopt a replacement. Discovery, specification, technical planning, task decomposition, parallel-execution organization, and next-change selection are intentionally unassigned stages in this repository's workflow map, not gaps to be silently filled by whichever skill, framework, or tool happens to be available. A future default workflow, if any, requires its own deliberate decision under the same evidence bar D020/D021 already set for tool adoption: demonstrated use, not availability.

D002 (repository tooling precedence) and D008 (availability does not imply adoption) remain the governing general policy this decision applies to planning workflow specifically.

## D031: Local guardrail layer — protected main + hardened secrets, installed into user-owned configuration

Two already-adopted policies — `main` is the canonical clean integration branch that routine workflows must not mutate directly, and AGENTS.md's secret/credential-file policy (D012) — existed only as prose with no mechanical backing. This decision adopts a small, portable, user-owned enforcement layer for both, installed by `bin/install-guardrails.sh` and implemented in `bin/git-hook-dispatch.sh`, `bin/claude-protected-main-guard.sh`, and `bin/allow-main-write.sh`. Full design rationale and empirical evidence: `plans/archive/2026-08-23-local-guardrail-layer.md`.

Architecture-level decisions, not implementation trivia:

* **Guardrails install into user-owned global configuration (global `core.hooksPath`, user-level `~/.claude/settings.json`), not into every repository Bindle or the user touches.** A committed per-repository hook is only enforced in that one repository and only after someone remembers to install it; a user-owned global layer protects every repository on the machine uniformly, matching the "local development guardrail layer for my local tooling" framing this was scoped to. **Fully superseded by D032**: both the Git hook layer and the Claude Code PreToolUse layer moved to repo-local, opt-in scope — this bullet's "global layer" framing no longer describes either half.
* **Git is the portable, lower-level enforcement layer for protected main** — it is enforced beneath any individual harness (terminal, Claude Code, Codex, IDE Git integrations) rather than reimplemented per harness.
* **Ownership of a global `core.hooksPath` requires transparent composition with repository-local hooks, not just coverage of the hook names Bindle happens to have policy for.** Setting `core.hooksPath` globally redirects Git's hook lookup for every hook name, not only the protected-main-relevant ones — installing policy for only a few hook names would have silently disabled unrelated repository-owned hooks (Cocogitto's `commit-msg`, projectmem's `post-commit`/`post-merge`, any third-party repository's own hooks) purely because Bindle had no opinion about them. The installed mechanism is a single dispatcher implementation, present under every standard client-side Git hook name, that delegates to a repository's own hook of the same name whenever one exists — composition, not replacement.
* **Claude Code gets an earlier, harness-specific guard for tracked-file mutation, layered above the Git-level enforcement, not a duplicate reimplementation of it.** This is a UX tripwire that fails before an edit is made, while Git-level hooks remain the authoritative lower-level protection regardless of which harness (or no harness) is driving the mutation.
* **Non-shell Claude tool calls (`Edit`/`Write`/`MultiEdit`/`NotebookEdit`) require a distinct, scoped one-shot authorization capability, because they cannot receive a command-scoped environment variable the way a `Bash`-issued Git command can.** This capability is deliberately narrower and separate from the Git layer's `ALLOW_MAIN_WRITE=1` override — bound to repository/worktree identity, single-use, and TTL-backstopped — and must never become a standing "unlock main" switch. It is invoked only after explicit, in-conversation user authorization; authorization is never inferred from the task.
* **Sensitive-environment enforcement uses the harness's native permission mechanism (`permissions.deny` in Claude Code) where one exists, rather than a bespoke scanner or shell parser.** This hardens D012's existing policy; it does not introduce a new secret-scanning capability (`docs/SCOPE.md` does not list security scanning as something Bindle owns) — the harness's own permission engine, not Bindle, does the enforcing.

Verified empirically rather than assumed, and material enough to belong here rather than only in the plan: a single `pre-commit` hook does not cover Git's actual mutation surface for `main` — `git rebase` replay and `git cherry-pick` do not fire `pre-commit`/`commit-msg` at all, and `git commit --no-verify` skips both regardless. `prepare-commit-msg` is the interception point that actually covers commit, merge, rebase-replay, and cherry-pick, and is not skipped by `--no-verify`; `git am` requires a separate hook (`pre-applypatch`) entirely, since it never invokes the ordinary commit-creation hooks. Known, permanently out of reach for any client-side Git hook: `git reset`, direct ref manipulation, a hook-unaware client, and a repository whose local `core.hooksPath` is owned by another hook manager the installer therefore refuses to replace (see D032).

## D032: Both guardrail layers moved to repo-local, opt-in scope; installer assets are package-owned

D031 installed both halves of the guardrail layer into machine-global configuration, on the premise that a global layer "protects every repository on the machine uniformly." PR #13 (`feat/cli-lifecycle-skeleton`) then established `bindle init` as this repository's explicit per-repository opt-in boundary for Bindle management — but a machine-global install is unconditional: it protects (or, if it broke, silently fails to protect) every repository on the machine regardless of whether that repository ever ran `bindle init`, and a machine-global `core.hooksPath`/Claude settings entry surviving a repository's `bindle remove` would silently re-protect it. Both contradict the opt-in model PR #13 introduced. This decision supersedes D031's global-configuration bullet in full: the repository is the unit of guardrail management, full stop; the machine only hosts the Bindle CLI and (for migration purposes only) knowledge of what was installed before this decision.

* **The Git hook layer** (`install-guardrails.sh`'s Git half, `git-hook-dispatch.sh`) is repo-local and opt-in, installed via `git config --local core.hooksPath` scoped to one repository at a time. The dispatcher and its standard-hook-name symlink set live at `<git-common-dir>/bindle-hooks` — inside `.git`, never tracked, and shared correctly across every linked worktree for free, because `--local` Git config and hooks are both stored in the repository's common directory (D018; `docs/WORKTREES.md`'s sharing table already documented this). `core.hooksPath` is always written as an absolute path: a relative value's resolution base differs per linked worktree's own private git-dir, while the common directory itself is already resolved absolute everywhere else in this codebase.
* **The Claude Code PreToolUse layer is now ALSO repo-local**, reversing D031's global framing entirely. It installs into the target repository's own `.claude/settings.local.json` — Claude Code's native, per-repository, gitignored-by-convention personal-settings file (confirmed against current Claude Code documentation, not assumed) — never into any user-level `~/.claude/settings.json`. The guard and helper scripts live at `<git-common-dir>/bindle-claude`, a directory kept deliberately separate from `bindle-hooks` so the two layers' installers stay fully independent (one can be applied/removed via `--git-only`/`--claude-only` without disturbing the other's staging state), and the deny-ownership record lives as a sibling file (`<git-common-dir>/bindle-claude-deny-owned.json`) so that permissions.deny hardening is never gated on guard-script install success. Claude Code documents that project settings for a linked worktree resolve "through worktrees to the main checkout," so the installer resolves the same main-checkout path (reusing D018's identity model) rather than writing into a linked worktree's own, never-consulted `.claude/` directory. There is no remaining Bindle-owned global Claude Code configuration of any kind — `bindle init`/`bindle remove` are the only way either guardrail layer is installed or removed anywhere.
* **`bindle init`/`bindle remove` drive both layers together** via `install-guardrails.sh --apply|--uninstall --repo <worktree root>` — the first real behavior either lifecycle command has. `--git-only`/`--claude-only` still exist on the installer for direct/test use, but the CLI no longer needs them: with both layers repo-scoped, there is no separately-scoped global layer left to accidentally toggle.
* **The installer's refuse-to-replace-a-foreign-value behavior (D031) is preserved for the Git layer, re-scoped from `--global` to `--local`**: it still refuses to overwrite a pre-existing `core.hooksPath` it did not set — now checked at repository scope, so another repo-local hook manager (pre-commit, husky, lefthook) is never silently overwritten. permissions.deny hardening remains additive by construction (only entries Bindle itself added are ever removed, tracked by the ownership record) so it composes safely with the repository's own settings.local.json content regardless of scope.
* **A recognized legacy global install (from before this decision) cannot silently defeat the opt-in model — but a repo-scoped `bindle init`/`bindle remove` must never be the thing that migrates or removes it, either.** A repository-targeted command mutating machine-global state as a side effect has consequences for every other repository on the machine, which is itself a violation of the opt-in model this decision establishes. So a normal `--apply`/`--uninstall` only ever *detects* a recognized pre-rework global `core.hooksPath` and/or global Claude PreToolUse guard entry (the same dispatcher-plus-full-symlink-set structural check the installer already used to refuse live-repairing a corrupted install, and an exact command-string match for the Claude entry) — on a positive match, it refuses to run at all, with an actionable error pointing at the explicit migration command, and leaves the legacy state, the target repository, and everything else completely untouched. Only `install-guardrails.sh --remove-legacy-global` — invoked directly, never as a side effect — performs the actual migration, and only for state it can positively prove is Bindle's own; it also reports explicitly (and fails) when it finds global state it cannot positively identify as Bindle's own, so the migration is never a silent no-op when someone asks for it directly. `bindle migrate-legacy-global` exposes this same command through the installed CLI (global/machine-level, no `--repo`) — the smallest surface over an already-packaged runtime asset, rather than requiring an installed-package user to locate and invoke the script directly. An unrelated global value is never reported, blocked on, or touched by any of this.
* **`bindle init`/`bindle remove` requesting both guardrail layers is all-or-nothing per invocation.** Before either layer mutates anything, a preflight pass validates every knowable precondition for both requested layers together (legacy-global recognition, a foreign local `core.hooksPath`, invalid/unreadable existing state) — on any problem, the whole invocation fails with nothing mutated for either layer. This closes the specific gap a preflight can't: if the Git layer completes and the Claude layer then fails for a reason only mutation itself could reveal (a filesystem error, not a precondition), the Git layer's change from *this invocation* is rolled back via the same idempotent apply/uninstall path, rather than left behind half-adopted. Preflight-before-mutation, not a generic transaction framework: within a single layer, D031/D032's existing atomicity design (staged-then-atomic-rename installs, ownership-record-before-settings-write ordering) is unchanged and is what preflight and rollback both build on rather than duplicate.
* **The guardrail installer and its runtime templates (`git-hook-dispatch.sh`, `claude-protected-main-guard.sh`, `allow-main-write.sh`) are package-owned assets** at `src/bindle/_bin/`, resolved at runtime via `importlib.resources.files("bindle")` rather than a path relative to `bindle`'s own source file or the caller's cwd. This works identically for `uv run bindle` (editable/dev) and a normally installed `bindle` release, and is verified by building the wheel through the repository's own `uv build` path and installing it into an isolated virtualenv outside this checkout (`bin/test-packaged-install.sh`). `bindle init`/`bindle remove` report a clear error, rather than crashing or silently doing nothing, if the runtime asset is ever missing from an installation.

* **The Claude-layer JSON merge needs no external tool.** `settings_json.py` — a package-owned runtime asset alongside the shell scripts above, resolved and invoked the same way — performs the same structural `settings.local.json` merge/remove operations jq previously did, run under whichever interpreter is already running Bindle (`BINDLE_PYTHON`, set by `bindle init`/`bindle remove`/`bindle migrate-legacy-global` to `sys.executable`; direct/test invocation of the installer falls back to `python3` on PATH). This closes the one onboarding dependency `bindle init` had beyond Python itself: a normal Bindle installation could previously succeed while its primary adoption command later failed for lack of an undeclared system `jq` binary. The canonical secret/deny-policy manifest stays declared once, in `install-guardrails.sh`; `settings_json.py` only ever receives it as an already-expanded JSON array argument — no duplicated policy.
* **A target repository's own Git hygiene around `.claude/settings.local.json` is respected, not assumed.** `bindle init` refuses to run (a preflight failure, before any mutation) if the target repository already tracks `.claude/settings.local.json` in Git — team-shared tracked configuration is never silently rewritten. If the file isn't tracked but also isn't already ignored (no matching `.gitignore` entry), `bindle init` records a machine-local ignore rule in the repository's own `<git-common-dir>/info/exclude` — shared across every linked worktree exactly like `core.hooksPath` (D018), never committed, and never touching the repository's own tracked `.gitignore`. A repository that already ignores the file (its own `.gitignore`, or a prior run of this) is left alone.
* **That `info/exclude` entry is ownership-tracked, and only ever removed when it's both Bindle's own and safe.** A tiny marker file (`<git-common-dir>/bindle-claude-exclude-owned`), the same sibling-file convention as the deny-ownership record, is written only on the genuine first append — never when the path was already ignored by some other source, so Bindle can never mistake an entry it didn't add for one it did. `bindle remove` only ever removes that single line when the marker proves Bindle added it *and* `settings.local.json` has become empty once Bindle's own PreToolUse/deny content is detached from it (`settings_json.py`'s `doc-is-empty`, which treats any surviving non-empty value — including a falsy scalar — as content worth keeping). If unrelated content remains in the file after detachment, both the file and its ignore rule are left completely alone, rather than leaving what was previously hidden repository configuration accidentally committable merely to achieve byte-for-byte cleanup. A pre-existing `info/exclude` entry, or one supplied via `.gitignore`, survives `bindle remove` untouched in every case, since no marker is ever written for it.

Full design and verification: `plans/archive/2026-08-24-repo-local-guardrails.md` (work complete, moved from `plans/active/` once merged).

## D033: Projectmem gains an explicit `bindle init --projectmem` seam; guardrails and Projectmem remain two differently-shaped integrations, not one generic Component abstraction

D022 accepted Projectmem as this repository's own trial repository-local memory tool, and `detect_projectmem()` (added alongside `bindle status`) gave Bindle a read-only view of a repository's Projectmem adoption state. Neither gave Bindle any way to actually initialize Projectmem for a repository — that stayed entirely manual (`pjm init`, run by hand). This decision adds that one missing seam, deliberately narrow, and records what building it revealed about whether guardrails and Projectmem should share a lifecycle abstraction.

* **`bindle init --projectmem` initializes Projectmem's core repository-local working-memory state, while suppressing every native `pjm init` convenience that reaches outside that scope.** It uses Projectmem's own native CLI — `pjm init --no-hooks --no-global --no-watch --no-backfill --no-claude-md --no-mcp-config --no-structure --no-stack-detect` — invoked with `cwd` set to the repository's resolved worktree root (the `pjm` CLI has no `--root`/`--repo`-equivalent flag to target a path itself; confirmed against the installed Projectmem 0.2.0 CLI). Bindle does not accept every provider default blindly: it deliberately opts out of cross-project memory inheritance, the background watcher, git-history backfill, Projectmem's own Claude-specific `CLAUDE.md` bridge block (Bindle is provider-neutral), MCP client-config output, and repository structure/stack analysis — none of those are part of "set up Projectmem's storage for this repository." Bindle does not construct `.projectmem/` state itself under any circumstance, and does not re-implement any of this suppression by hand — every one of the flags above is Projectmem's own native, documented `pjm init` option.
* **Projectmem's Git hooks remain enabled, but are installed as a separate step, against the repository's shared Git common directory, not folded into `pjm init` above.** Bindle suppresses Projectmem's init-time hook installation (`--no-hooks`, above) and invokes Projectmem's native `pjm hooks install` separately, with `cwd` set to `RepoInfo.repo_root` (the main checkout), not `worktree_root`. This corrects an initial version of this decision that left hook installation at `pjm init`'s native default: Projectmem's hook installer (both at `pjm init` time and via `pjm hooks install`) resolves `<cwd>/.git/hooks` directly — in a linked Git worktree, `.git` is a *file* (a gitdir pointer), not a directory, so hook installation silently no-ops there, verified empirically against a real `git worktree add` fixture. `repo_root` is the one path guaranteed to have a real `.git/` directory regardless of which linked worktree `bindle init --projectmem` was actually run from, and it's exactly where Git looks for hooks anyway (hooks are shared repository-level state through the common directory, like `core.hooksPath` — D018). Composition with Bindle's own `core.hooksPath` dispatcher was verified empirically, not assumed, in both an ordinary checkout and a linked worktree: the dispatcher transparently delegates to `.git/hooks/{pre-commit,post-commit,post-merge}`, so Projectmem's own auto-capture and precheck hooks fire correctly on non-protected branches (storage stays worktree-local even though the hooks that write to it are shared), and Bindle's protected-`main` guard still blocks before ever delegating to them on `main`. Bindle never constructs or edits Projectmem's hook files itself — `pjm hooks install` is Projectmem's own supported CLI surface for this, used exactly as-is.
* **This guarantees correct hook placement only when Bindle itself initializes Projectmem — it does not audit or repair a pre-existing installation.** When `detect_projectmem()` already reports `installed`, `bindle init --projectmem` remains a no-op success and never calls `pjm` at all (see below), including never calling `pjm hooks install` to check whether an existing install's hooks are actually present or worktree-correct. A Projectmem install set up by hand, or by an earlier version of this integration, could still have hooks silently missing if it was ever initialized from a linked worktree. Extending `init --projectmem` into a general repair/reconciliation mechanism for that case is explicitly out of scope for this slice — it would turn an idempotent opt-in seam into an audit tool with its own precondition and safety surface. If this gap proves to matter in practice, it is a future slice's decision to make, with its own evidence, not a silent expansion of this one.
* **One native behavior is not suppressible by any flag, and this decision leaves it as-is.** Projectmem 0.2.0's `initialize()` unconditionally registers the repository's absolute path in a cross-project registry (`~/.projectmem/projects.json` by default, or `$PROJECTMEM_HOME/projects.json`) so `pjm dashboard` can enumerate it later — this call is not gated by `--no-global` or any other flag. This is a lightweight path index, not memory content, and being listed is arguably consistent with genuine adoption rather than contradicting it, so Bindle does not attempt to work around it (e.g. by forcing `PROJECTMEM_HOME` for the real invocation, which would be a larger, unrequested change to Projectmem's own environment resolution). Noted here so it isn't mistaken for an oversight.
* **Known Projectmem preconditions are checked before guardrails mutate anything, not after.** `bindle init --projectmem` resolves the repository, then runs `detect_projectmem()`'s read-only check before touching guardrails at all: `partial` and `conflict` both refuse immediately, and `not-installed` additionally requires a `pjm` executable to be resolvable — any of these three refusals leaves guardrails completely untouched. Only once that precondition check passes do guardrails install/reconcile (unchanged bare-`init` behavior), and only after guardrails succeed does Projectmem itself get initialized (skipped entirely, as a no-op success, when detection already said `installed` — no `pjm` executable is required in that case at all). This ordering exists because native `pjm init` has no concept of refusing on ambiguous state: verified empirically that a real run against a `partial` `.projectmem/` (a directory without `config.toml`) silently *completes* it, and a real run against a `conflict` (a file occupying `.projectmem`) crashes with an unhandled Python traceback — Bindle's own precondition check, run first, is what makes Bindle refuse cleanly instead of either outcome.
* **`bindle init --projectmem` composes as a sequence of independently-ordered operations, not a transaction: guardrails, then `pjm init`, then `pjm hooks install`.** Precondition checking is read-only and gates entry; actual mutation is still sequential and non-transactional beyond that gate. `pjm hooks install` is only ever attempted after `pjm init` succeeds — a failed `pjm init` reports its own failure and stops there, hooks are never attempted against a repository whose storage setup didn't complete. If `pjm init` succeeds but `pjm hooks install` then fails, that failure is reported as-is; nothing already completed is rolled back — Projectmem storage and guardrails both remain exactly as they are. A provider-owned knowledge directory is never deleted or "cleaned up" to simulate all-or-nothing completion; partial completion at any point in this sequence is reported clearly and left as-is.
* **`bindle remove` never touches `.projectmem/`, in every case.** Unlike the guardrail layer (which `remove` fully uninstalls), Bindle holds no ownership record proving it may destroy Projectmem's working memory, so removal is asymmetric by design: guardrails are removed, Projectmem is always preserved. `bindle remove` prints a one-line note when Projectmem was observed installed, so the asymmetry is visible rather than silent. Confirmed as intentional, reachable state — not a gap — that `bindle status` can legitimately show guardrails `not-installed` alongside Projectmem `installed` after `init --projectmem` followed by `remove`.
* **Two real implementation seams now exist, and their shapes still diverge too much to unify.** Guardrails: a Bindle-owned installer script, symmetric `--apply`/`--uninstall`, package-owned runtime assets, full removal on `bindle remove`. Projectmem: an external native CLI Bindle only ever invokes (never parses or reimplements), filesystem-native read-only detection, provider-owned data, and permanent preservation rather than removal. Both now participate in `init` and `status`, but one is symmetric and Bindle-owned end-to-end while the other is asymmetric and provider-owned end-to-end — a generic Component/provider-registry abstraction over "the things `bindle init`/`remove`/`status` touch" would have to paper over that asymmetry rather than express it, for a benefit not yet demonstrated with only two data points. No such abstraction is introduced. If a third differently-shaped provider-lifecycle integration is added later and the divergence pattern repeats, that is the point to revisit this with real evidence (AGENTS.md's "Repository tooling precedence": extend before replacing, replace only with demonstrated need) — not before.

Scope deliberately excluded from this decision (unchanged, and not reconsidered here): Projectmem removal/repair/watcher management, cross-project Projectmem memory, Projectmem MCP registration or Claude/Codex MCP configuration, any generic component/provider registry, profiles, `.bindle/` state, or Bindle-owned ownership bookkeeping recording that Bindle initialized Projectmem.

## D034: Drop the dead `Write(glob)` deny rule from the Claude-layer secret-file policy

D031/D032's Claude-layer secret-file policy (`install-guardrails.sh`'s `FILE_DENY_TOOLS`) generated four deny rules per sensitive-file glob — `Read`, `Edit`, `Write`, `Grep` — on the assumption that each names a distinct tool Claude Code's permission engine matches against. Claude Code's own startup diagnostics on a live installed `settings.local.json` (observed directly, not assumed) reported every `Write(glob)` entry as "not matched by file permission checks — only `Edit(path)` rules are," since a single `Edit(path)` rule already covers every file-editing tool call (Edit, Write, MultiEdit, NotebookEdit — the exact same tool set `PRETOOLUSE_MATCHER` already gates on). The `Write(glob)` entries were never providing protection `Edit(glob)` didn't already provide — dead weight, not a security gap: nothing was ever unprotected, since `Edit` already covered Write.

`FILE_DENY_TOOLS` is corrected to `(Read Edit Grep)`, dropping `Write`. Effect: 13 fewer entries per repository's deny manifest (13 secret-file globs × 1 fewer tool each), from 61 down to 48 for a fresh install; the resulting manifest still denies every documented secret-file shape for every tool that actually matches. `bin/test-install-guardrails.sh`'s "secret-file deny manifest content" scenario now asserts `Write(.env)`'s *absence* rather than its presence.

This is additive-merge, not retroactive reconciliation: `bindle init`'s existing `--apply` behavior only ever adds manifest entries not yet present in a target repository's `settings.local.json` — it does not prune entries a prior installer version added that are no longer in the current manifest (that remains D031/D032's existing, unchanged reconcile model; building automatic stale-entry pruning is a separate concern, not part of this fix). A repository whose guardrails were installed before this decision keeps its stale `Write(glob)` entries (still harmless, just noisy) until an explicit `bindle remove` followed by `bindle init` re-creates its Claude-layer configuration from the corrected manifest.

## D035: Skill kits — the third provider-lifecycle seam, deliberately narrower than a package manager

Guardrails (D031/D032) and Projectmem (D033) established two differently-shaped provider-lifecycle integrations. This decision adds a third: **skill kits**, a named collection of agent-facing skills/capabilities Bindle makes available to Claude Code and Codex through each harness's own native mechanism. Initial kits: `software-engineering` (source `t-step/skills`) and `spec-kit` (source `github/spec-kit`), surfaced as `bindle skills list|status|add|remove`.

Every native mechanism cited below was verified this session against the actually-installed tooling (Claude Code 2.1.243, Codex CLI 0.146.0, specify-cli 1.0.1) and the live `t-step/skills` repository — not assumed from memory, since all three are fast-moving.

* **A skill kit is a catalog entry pairing a kit ID with a Python module implementing `status()`/`add()`/`remove()` against that kit's own provider(s)** (`src/bindle/skills/catalog.py`, `software_engineering.py`, `spec_kit.py`). This is a skill-kit-specific abstraction — not a generic Bindle Component/Provider framework. Two kits were enough to reveal real structural differences (see below) without inventing symmetry that doesn't exist; a third, differently-shaped kit is the point at which to revisit whether more shared structure is justified, mirroring D033's closing precedent.
* **Desired state is one new piece of tracked, repository-owned configuration: `bindle.toml`'s `[skills].kits` array**, read/written by `src/bindle/skills/config.py`. This is desired state only — never history, ownership bookkeeping, a lockfile, or a provider datastore. Writes are a targeted line-level patch of exactly the `kits` line (via `tomllib` for reads, no TOML-writing dependency added — this project has none), so unrelated file content and formatting survive untouched. `bindle.toml` is an ordinary tracked file read/written at the current worktree's root, so it follows the checked-out branch like AGENTS.md (docs/WORKTREES.md) — no special worktree handling needed.
* **Availability is not adoption, and desired is not installed.** `bindle skills status` reports three independent facts per kit: whether the repository desires it (`bindle.toml`), and whether each harness (Claude, Codex) currently has it installed — computed via each harness's own read-only interface, never by checking whether the machine merely has the capability to install it.
* **`software-engineering` installs for Claude entirely through Claude's own marketplace/plugin CLI**: `claude plugin marketplace add t-step/skills` (only if not already registered — checked first via `claude plugin marketplace list --json`) followed by `claude plugin install software-engineering@t-step-skills --scope project -y`. Project scope was chosen deliberately: it writes to the repository's own tracked `.claude/settings.json` (`enabledPlugins`), matching `bindle.toml`'s own repo-scoped, shareable-if-committed model — verified this session that Claude Code's project scope is genuinely tied to the repository root, distinct from `local` (gitignored-by-convention, personal) and `user` (machine-global) scope. Status is read directly from that same `enabledPlugins` key — a documented, project-owned interface, not private-store parsing (D014).
* **Marketplace registration is Claude's own machine-global concept with no per-repository equivalent — `remove()` never unregisters it**, mirroring D032/D033's precedent that a repository-scoped command must never mutate machine-global state as a side effect (another repository on the machine may depend on the same marketplace). `bindle skills remove software-engineering` only ever runs `claude plugin uninstall software-engineering@t-step-skills --scope project -y`.
* **Codex has no package manager or CLI lifecycle for skills at all** (confirmed this session: `codex plugin` is a distinct, broader mechanism — marketplace-distributed bundles of skills+hooks+MCP+apps — not the plain-skill install path). The native mechanism is a repository-local `.agents/skills/<name>/SKILL.md` directory Codex discovers by convention (a cross-vendor convention, not Codex-specific — Spec Kit's own Codex integration uses the identical path). Since no CLI exists to wrap, Bindle materializes: `add()` shallow-clones `t-step/skills` at `add()` time, discovers the published skill directories dynamically (never a hardcoded snapshot — this repository's own `t-step/skills` is never vendored into Bindle, matching D014), and copies each into `.agents/skills/<name>/` verbatim. This is a point-in-time snapshot, not a live sync — no auto-update, consistent with this slice's explicit non-goals (no `bindle update`/`upgrade` reconciliation for skill kits).
* **Codex ownership is genuinely worktree-scoped, not machine- or repository-scoped.** Materialized files live at `<worktree>/.agents/skills/<name>/` — worktree-local per docs/WORKTREES.md — so the ownership marker recording what Bindle materialized lives at `repo_info.git_dir`, not `git_common_dir`: `<git-dir>/bindle-skills/software-engineering.codex.json`. For an ordinary checkout these are the same path; for a linked worktree `git_dir` is Git's own per-worktree administrative directory, which Git itself removes when the worktree is removed. Two linked worktrees that both materialize the kit get independent ownership evidence — one worktree's `remove()` can never delete or corrupt another worktree's marker, corrected from an earlier version of this slice that used the shared `git_common_dir`, which let a linked worktree's `remove()` delete the *only* ownership record for materialized files a completely different worktree still had on disk.
* **`info/exclude`, unlike the marker, genuinely is shared Git state — so it is reconciled, not owned by any single worktree.** `add()`/`remove()` recompute the full required set of ignore lines from the union of every currently-live worktree's marker (found by walking `<git-common-dir>/worktrees/*`, which Git prunes on its own alongside a removed worktree) and rewrite exactly one clearly-delimited, mechanically-owned block in `info/exclude` to match — every other line, including a pre-existing identical entry from the repository's own tooling, is left untouched and never duplicated into the block. One worktree removing the kit therefore only ever removes the ignore lines no remaining worktree still needs; a broad `.agents/skills/` ignore rule was deliberately rejected as unsafe, since spec-kit's own Codex integration writes into the identical directory.
* **Ownership at removal time requires proof of unmodified content, not merely a remembered directory name.** Each marker entry pairs a skill name with a deterministic content digest (relative path + content hash of every file, sha256 over the sorted manifest) computed at materialization time. `remove()` only deletes a directory whose current digest still matches; anything modified, replaced, or foreign since materialization is preserved byte-for-byte and reported as a conflict, with its ownership evidence retained in the marker so a future `remove()` — after the user resolves it by hand — can still act on it safely. `status()` uses the same digest check: a materialized path present but digest-mismatched is `conflict`, an objective, narrowly-scoped predicate distinct from `partial` (recognizably owned but incomplete) or `not-installed` (nothing there). `add()` refuses outright when status is already `conflict`, rather than materializing alongside content it can't safely reconcile.
* **`spec-kit` is a Spec Kit integration, not a folder of skill files, and installs through Spec Kit's own `specify` CLI end-to-end** — never reimplemented. Verified this session that Spec Kit's own skills are not self-contained (their `SKILL.md` files declare `compatibility: "Requires spec-kit project structure with .specify/ directory"` and shell out to `.specify/scripts/...`), so a kit shipping bare skill files would silently not work. `add()` bootstraps `.specify/` via `specify init --here --force --non-interactive --integration claude --script sh` only when `.specify/` doesn't exist yet (verified empirically, against a realistic pre-populated repository snapshot with its own tracked `.gitignore`/`AGENTS.md`/etc., that `--force` here only skips the "directory not empty" confirmation prompt — every pre-existing tracked file was confirmed byte-identical afterward via sha1, and the only new paths were untracked `.claude/` and `.specify/`), then `specify integration install codex`; when `.specify/` already exists, only the missing harness integration is installed via `specify integration install <key>` (idempotent-safe on an already-installed key, confirmed empirically).
* **Status for spec-kit is a two-tier read**: a `.specify/` directory existence check (an objective filesystem fact, resolvable with zero `specify` binary calls — matching detect_projectmem.py's own filesystem-first convention) short-circuits to `not-installed` for both harnesses; once `.specify/` exists, `specify integration status --json`'s `installed_integrations` list is the source of truth (verified this session to be stable and reliably parseable), shelled out to exactly like guardrails.py shells out to install-guardrails.sh's own `--status` mode rather than reimplementing its predicates. A `.specify/` directory present but no `specify` binary resolvable reports `unavailable` for both harnesses — a real, distinct state from `not-installed`, since state genuinely cannot be determined, not merely absent.
* **`remove()` for spec-kit only ever runs `specify integration uninstall claude`/`codex`** — verified empirically (via realistic pre-populated fixture, not an empty scratch directory) that this removes exactly that integration's own tracked files, leaves the other integration and every unrelated repository file byte-for-byte untouched, and never prompts. `.specify/` itself is never deleted — no such command exists, and other integrations or the repository's own direct use of Spec Kit may still depend on it; removing this repository's desired kit must never mean uninstalling `specify` from the machine or destroying shared project scaffolding it didn't exclusively own.
* **Spec Kit's own scaffolding (`.specify/`, `.claude/skills/speckit-*`, `.agents/skills/speckit-*`) is created untracked by `specify init`/`specify integration install`, by Spec Kit's own choice, not Bindle's** — verified empirically this session, including from a linked worktree, that this makes spec-kit's adoption worktree-local exactly like the Codex materialization above, unless the repository itself chooses to commit these paths. Bindle does not force that choice either way.
* **`specify bundle` was evaluated as a possible reusable distribution mechanism for arbitrary skill kits, and rejected.** Its own `--help` text and a real installed community bundle's `info --json` output confirm it composes Spec Kit's own primitive types (extensions, presets, steps, workflows) — Spec-Kit-specific composition machinery that happens to use "bundle" terminology, not a generic package manager arbitrary content could ride on. No role adopted for this slice.
* **Two harness-facing outcomes remain honestly asymmetric rather than faked into symmetry.** Claude's marketplace registration step is machine-global with no per-repo undo (documented above, not worked around). Codex materialization for `software-engineering` needs Bindle-owned ownership bookkeeping that neither other integration in this slice needs. No command pretends these are uniform; `bindle skills status`'s per-harness, per-kit reporting exists specifically so the real shape is visible rather than collapsed into one aggregate state.
* **Explicitly out of scope, unchanged from the originating plan**: arbitrary third-party kit URLs, a remote catalog service, a semver solver, a lockfile, transitive/nested/composite kits, automatic updates, `bindle update`/`upgrade` reconciliation for skill kits, `bindle init`/`bindle remove` skill reconciliation, fleet-wide management, and any generic Component/Provider abstraction beyond the skill-kit-specific one described above.

Full design detail, investigation findings, and verification evidence: `plans/archive/2026-08-24-skill-kit-lifecycle.md`.
