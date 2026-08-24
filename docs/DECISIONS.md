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

Full design and verification: `plans/active/2026-08-24-repo-local-guardrails.md`.
