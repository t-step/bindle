# Obsidian Mind interoperability audit

Date: 2026-08-02. Status: **archived — trial closed without adoption, docs/DECISIONS.md D028.**
Findings below are preserved as historical evidence; the om MCP server is no longer registered or
used in this repository.

Original status: audit only — nothing installed, nothing deployed.

Question under audit: can obsidian-mind (github.com/breferrari/obsidian-mind, v8.3.1) serve as the
shared durable-notes and work-record layer across Claude Code and Codex without parallel stores,
provider-specific dead ends, or worktree ambiguity?

Verdict in one paragraph: **yes for Claude Code today; not yet symmetrically for Codex.** The vault,
templates, write behavior, and retrieval stack are genuinely provider-neutral and safe for shared
writes. The single hard interoperability failure is that Codex's MCP client does not send the MCP
`roots` capability, and om derives caller identity *exclusively* from the roots handshake — so every
Codex session is an anonymous caller: project-scoped recall is invisible, `record_work` falls to the
inbox, and project-scoped `remember` is refused. This is not fixable by configuration; it needs a
small adapter (a roots-injecting MCP proxy) or an upstream om change. Everything else in the
intended ownership model holds up, with a short list of conventions (`.om-project` committed,
`@AGENTS.md` import, evidence lines in records) closing the remaining gaps.

## Evidence sources

- obsidian-mind v8.3.1 source, cloned and read (HEAD `538522e`, tag v8.3.1, 2026-07-31); citations
  below are to files under its repo root.
- Claude Code official docs (code.claude.com/docs), plus local verification of
  `~/.claude/projects/` layout on this machine.
- Codex CLI 0.146.0: official docs (developers.openai.com/codex), openai/codex source
  (`protocol.rs`, `recorder.rs`, `rmcp_client.rs`, `runtime.rs`, `mcp_runtime.rs`), and read-only
  local inspection (`codex --version`, `codex features list`, `~/.codex/config.toml` with
  secret-pattern filtering, `state_5.sqlite` schema). Local install is fresh — zero recorded
  threads — so session-header claims are source-verified, not observed.
- Bindle repository docs: PHILOSOPHY.md, DATA-OWNERSHIP.md, WORKTREES.md, PRIVACY.md, DECISIONS.md.
- projectmem v0.2.0 behavior as already verified in docs/WORKTREES.md (2026-08-02).

Claims are marked **[V]** verified (source/docs/local observation) or **[A]** assumption/inference.
Unmarked statements in the deliverable tables inherit the marking of the finding they summarize.

## 1. Claude Code integration — established facts

- Hook events include SessionStart, SessionEnd, Stop, PreCompact, PreToolUse, PostToolUse,
  UserPromptSubmit, Notification. **[V]**
- Hook stdin JSON: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `permission_mode`
  (+ event-specific fields such as SessionStart `source` ∈ startup|resume|clear|compact). **[V]**
- No git fields reach hooks — branch/SHA/worktree must be derived from `cwd` by the hook script. **[V]**
- SessionStart fires on startup, resume, `/clear`, and after compaction; stdout / `additionalContext`
  is injected as context. **[V]** SessionEnd firing on hard kill is not guaranteed by docs. **[A]**
- PreCompact exists (om's shipped hook consumes `{transcript_path, trigger}`) but is thinly
  documented upstream — schema/blocking behavior unconfirmed. **[V that it fires / A on guarantees]**
- Transcripts: `~/.claude/projects/<munged-cwd>/<session-id>.jsonl`, 30-day default retention
  (`cleanupPeriodDays`); `transcript_path` is handed to hooks; session_id = filename and is stable
  across resume/compaction. **[V, confirmed locally]**
- Auto-memory: `~/.claude/projects/<project>/memory/`, and per current docs the `<project>` key is
  **derived from the git repository, so all linked worktrees share one auto-memory directory**,
  while transcripts stay split per worktree cwd. **[V — this resolves the "re-verify" note in
  docs/WORKTREES.md]**
- CLAUDE.md is read natively; **AGENTS.md is not**. The documented bridge is an `@AGENTS.md` import
  inside CLAUDE.md. Bindle's CLAUDE.md currently uses a prose instruction ("Read and follow
  AGENTS.md in full"), which makes AGENTS.md loading model-compliance rather than deterministic
  file inclusion. **[V]** Finding: switch to the `@AGENTS.md` import.
- Tracked instruction files differ per branch/worktree checkout; that is git working correctly
  (docs/WORKTREES.md) — merge policy changes to main promptly.
- Hooks are configurable in `~/.claude/settings.json`, repo `.claude/settings.json` (checked in,
  shareable), and `.claude/settings.local.json`; whether project hooks run without a per-user trust
  approval is not explicitly documented. **[A — assume a trust gate]**
- Whether Claude Code sends MCP roots is not explicitly documented, but om's identity design depends
  on it and om is built primarily against Claude Code; `om health` reports the identity source, so
  the trial verifies this on day one. **[A, trivially checkable]**

## 2. Codex integration — established facts

- Codex 0.146.0 (installed = latest stable) **has a full hooks system**, stable and enabled:
  SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse, PermissionRequest,
  PreCompact, PostCompact, SubagentStart, SubagentStop, Stop. TOML `[[hooks.X]]` in config.toml or
  JSON `hooks.json`; layers: `~/.codex/hooks.json`, `~/.codex/config.toml`, `<repo>/.codex/hooks.json`,
  `<repo>/.codex/config.toml` (repo layer only for trusted projects). **[V]**
- Hook stdin: `session_id`, `transcript_path`, `cwd`, `model`, `turn_id`, `hook_event_name`,
  event-specific fields; SessionStart `source` ∈ startup|resume|clear|compact; stdout /
  `additionalContext` injection equivalent to Claude Code (~2500-token default limit). **[V]**
- This substantially updates D001's assumption that Codex lacks a hook mechanism.
- **MCP roots are NOT sent**: `initialize` declares only default capabilities + elicitation; no
  `roots` implementation exists in the client. **[V — openai/codex `rmcp_client.rs`]** A server can
  learn cwd only via spawn cwd, explicit `mcp_servers.<id>.cwd` config, or the
  `codex/sandbox-state-meta` capability — om uses none of these for identity. **[V]**
- AGENTS.md discovery: global `~/.codex/AGENTS.md`, then project root ("typically the Git root")
  walking down to cwd, root-first concatenation, 32 KiB default cap; CLAUDE.md readable only via
  `project_doc_fallback_filenames = ["CLAUDE.md"]`. **[V]**
- Worktrees: a `.git` entry (file or dir) is a hard project-root boundary, so a linked worktree is
  its own project root — AGENTS.md is found at the worktree root (it's a tracked file, so it's
  present there), and Codex never walks to the common dir. Two worktrees are unrelated cwds to
  Codex. **[V for the boundary; A for the extrapolation]**
- Sessions: `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<thread-uuid>.jsonl`; header records cwd and
  `git: {commit_hash, branch, repository_url}` — **no dirty state**. Threads also indexed in
  `state_5.sqlite` with `cwd, git_sha, git_branch, git_origin_url, ...`. Thread id is user-visible
  (filename, `codex resume <id>`, notify payload). Resume picker is cwd-scoped by default. **[V]**
- Memories: native feature, **off by default**, **global scope per `$CODEX_HOME`** (per-project
  scoping is an open feature request), explicitly advisory ("helpful recall layer"), with
  `disable_on_external_context` skipping memory generation for MCP-heavy sessions. This matches the
  "provider-native memory = soft recall only" model with zero configuration. **[V]**
- No mechanism on either harness guarantees a model-issued MCP tool call before exit. Codex's
  SessionEnd hook (and Claude's Stop/SessionEnd hooks) run commands deterministically, but a hook is
  an out-of-band process, not an in-conversation `record_work` call. **[V]**
- Retrieval vs lifecycle separation: MCP connects fine (stdio, config.toml), but **retrieval
  interoperability is degraded by the roots gap** (below), and lifecycle interoperability is
  *newly possible* via Codex hooks but unproven against om's shipped configs.

## 3. obsidian-mind — established facts

- `om` MCP server (stdio, Node 22+, zero runtime deps): `search`, `expand`, `recall`,
  `record_work`, `remember`, `reason`, `health`. **[V]**
- Caller identity = first MCP root URI → `.om-project` first non-comment line (regex `^[\w.-]+$`)
  else folder basename, lowercased. No roots ⇒ anonymous ⇒ only `general`-scope memories visible,
  `record_work` ⇒ `inbox/` fallback, project-scope `remember` with no caller ⇒ refused. **No git
  consultation anywhere** — no common dir, remote, branch, SHA. **[V — `mcp-caller.ts`]**
- Writes: temp file + `COPYFILE_EXCL` atomic exclusive create; collision ⇒ suffix (`… (2).md` /
  `…-2.md`); no locks; the only in-place edit ever is adding `superseded_by:` to server-written
  memories. Human notes never modified. **[V — `atomic-write.ts`]**
- Records are provider-anonymous: `source: mcp-capture`, `source_repo: <project name>`; no harness
  field, no transcript path, no session id (the `session:` frontmatter key is a write timestamp).
  A Codex-written record would be byte-structurally identical to a Claude-written one. **[V]**
- Zero VCS state in any record, memory, or audit line. Two branches of one repo are
  indistinguishable in om's records — om's own ARCHITECTURE.md acknowledges this and warns against
  building a parallel session-record store; the deterministic git half belongs at the seam. **[V]**
- Lifecycle hooks ship **wired only inside the vault repo** (`.claude/settings.json` in the vault:
  SessionStart context, UserPromptSubmit classify, PostToolUse validate, PreCompact transcript
  backup, Stop checklist). **Consuming repos get no hooks** — cross-repo capture is model-invoked
  `record_work` driven by a CLAUDE.md snippet. `.codex/hooks.json` ships in Claude schema
  (SessionStart/UserPromptSubmit/PostToolUse/Stop — no PreCompact, no SessionEnd) with nothing
  installing it; given Codex's newly confirmed `<repo>/.codex/hooks.json` layer it is *plausible*
  it now works in the vault repo, but schema compatibility is unverified. **[V for contents; A for
  whether Codex accepts the schema]**
- Retrieval: `recall` is caller-scoped (declared-reach memories, supersession-aware); `search` is
  qmd-backed semantic+lexical over the whole vault filtered by **exposure policy** (folder-level),
  not caller scope — so an anonymous caller may still find project *notes* via `search` even when
  `recall` hides project *memories*. **[V for mechanics; A for the anonymous-search consequence —
  experiment 8]**
- Fully local: qmd runs three local models, no API keys, zero network calls or telemetry in shipped
  scripts; the only indirect network path is the `reason` tool spawning the user's own `claude`
  CLI. **[V]**
- Privacy: records carry repo *names*, never absolute paths; error text sanitizes local paths;
  audit log (query strings) is gitignored in the vault; `health` does return the vault's absolute
  path into session context; the vault-repo PreCompact hook copies raw transcripts (absolute paths,
  session ids) into gitignored `thinking/session-logs/`. **[V]**
- Maturity: v8.3.1, 29 tagged releases in 5 months, MIT, effectively single-maintainer **[A —
  strongly inferred]**, real test suite including concurrency tests. Single-maintainer velocity is
  a dependency risk to note, and also means an upstream roots/identity patch is plausible to land.

## 4. Shared write behavior — conclusion

Safe. Both harnesses writing to the same vault directories (work records, memories, project notes,
inbox) cannot destroy each other's writes: every write path is atomic-exclusive-create with
deterministic suffixing on collision, verified down to a concurrency test suite. There is no
provider metadata in shared prose; templates and server-rendered records are provider-neutral;
either provider can read and continue the other's records (continuation = new record + optional
`supersedes`, never editing). Residual risks are benign duplication (two same-day records with
suffixed names — a human/hygiene dedupe concern, not data loss) and the absence of any code-state
stamp distinguishing what each record described (G3 below). A provider-neutral schema already
exists — it is om's own record format; the only needed addition is an evidence convention.

## 5. Cross-harness handoff — what survives the journey

Journey: Claude records work → Codex retrieves → Codex continues and records → Claude resumes.

| Field | Survives today? | Carrier | Missing piece |
| --- | --- | --- | --- |
| Objective / completed / unresolved / decisions / verification | yes (prose) | record_work fields `summary, changes[], decisions[], verification, open[]` | none — schema is adequate |
| "completed, do not redo" | yes (prose) | `changes[]` vs `open[]` | template guidance only |
| Repository identity | partially | `source_repo:` = project *name* via `.om-project` | routing convention (commit `.om-project`) |
| Worktree path | **lost** | — | evidence line (convention now, Bindle block later) |
| Branch | **lost** | — | evidence line |
| HEAD SHA | **lost** (Codex has it in its own thread record; not in the vault record) | — | evidence line |
| Dirty state | **lost** (no harness records it either) | — | evidence line; only Bindle-style capture can supply it |
| Transcript / thread pointer | **lost** in records | Claude hooks get `transcript_path`; Codex rollout path + thread id exist locally | template field fed by hook or pasted manually |
| Step 2 (Codex retrieves) | **degraded** | `recall` project scope invisible to anonymous Codex; `search` may still surface notes (exp. 8) | **adapter or upstream fix (G1)** |
| Step 3 (Codex records) | **degraded** | lands in `inbox/`, not `projects/<name>/` | same |

Classification of fixes: `.om-project` = routing convention. Evidence fields = template convention
now, Bindle evidence block (new code) when the friction is proven. Transcript/thread pointer =
template change + hook config. Codex identity = the only item needing **actual new code** (thin
roots-injecting MCP proxy, ~trivial, or upstream om change to accept identity from env/config/_meta).

## 6. Worktree interoperability

Setup analyzed: `<dev>/<repo-2>` (main) + `<dev>/worktrees/<repo-2>-123` (linked), where
`<repo-2>` is the second private repository in the trial.

- Without `.om-project`: om sees `<repo-2>` and `<repo-2>-123` — **two disjoint projects** (the exact
  basename-keying failure that produced 11 orphan folders in the archived prototype). With a
  committed `.om-project` containing `<repo-2>`: one project from every worktree and branch, because
  the tracked marker is present in each checkout. **Recommendation: track and commit `.om-project`
  as a routing label.**
- Simultaneous worktrees: om cannot distinguish them at all (no worktree path, branch, or SHA in
  records); records do not collide (suffixing) but are indistinguishable in origin — evidence lines
  are the fix, not a blocker for the trial.
- Claude in worktree A / Codex in worktree B: same vault, same project (with the marker), same
  retrievable knowledge (modulo G1 for Codex). Which branch/code-state a note describes is
  unrecoverable unless stamped in the record.
- projectmem: single-checkout by design here (`.projectmem/` fully gitignored ⇒ absent in linked
  worktrees; auto-capture silently no-ops; `pjm hooks install` fails where `.git` is a file).
  Accepted trial limitation — record worktree decisions from the primary checkout after merge.
- Hooks when `.git` is a file: git hooks live in the common directory and fire in every worktree
  (cwd = that worktree) — this is how Cocogitto and the future privacy guard behave. Harness hooks
  are not git hooks: Claude's come from settings files (tracked ⇒ present per checkout), Codex's
  from `~/.codex` or the trusted repo layer (per checkout). projectmem is the only tool that breaks
  on the `.git`-file case.
- Provider state location: Claude transcripts follow **cwd** (split per worktree); Claude
  auto-memory follows **the git repository** (shared across worktrees); Codex threads/resume follow
  **cwd** (split), while its recorded `git_origin_url`/`git_sha` come from git and resolve through
  the common dir correctly; om follows **the first MCP root's name** (unified only via marker).
- Identity-model hypothesis (common dir + remote = repository identity; worktree path = execution
  identity; SHA + dirty = code state; branch = descriptive only): **confirmed as the right model,
  and notably it is exactly the model Claude's auto-memory already implements** — but om implements
  none of it. `.om-project` is a stable **routing label** that keeps om's per-name folders unified —
  it is not, and must not be treated as, canonical repository identity, which remains the git
  common directory plus stable remote metadata (D018); the rest of the identity model exists only
  if stamped into records. No party keys anything on branch, confirming "branch never primary."

## 7. Failure and degradation modes

| Scenario | Still works | Lost | Recovery | Visible? | Bindle diagnose? |
| --- | --- | --- | --- | --- | --- |
| All three available (Claude + Codex + om) | everything modulo G1/G2 | — | — | — | baseline check |
| om vault/MCP server unavailable | both harnesses fully; repo files, projectmem | vault retrieval + capture that session | write dated handoff under `plans/`, backfill later | Claude: MCP failure surfaced; model may silently skip `record_work` | **yes — doctor: om reachable + health identity** |
| Claude available, Codex not (or vice versa) | the other harness fully; vault intact | nothing durable (records are provider-neutral) | resume from vault records | yes | trivially |
| MCP server stopped mid-session | session continues | capture at session end | restart server; backfill | tool-call error if attempted; silent if never attempted | yes |
| Vault unavailable (disk/sync) | harnesses | all vault ops | restore vault (it's a git repo) | server errors | yes |
| Vault repo merge conflicts | om reads/writes still function on working tree | clean history until resolved | normal git resolution; new-file-only writes rarely conflict — plausible conflict surface is `superseded_by` frontmatter edits **[A]** | only if user looks | doctor could flag dirty/conflicted vault |
| Two harnesses write simultaneously | both writes land | nothing (suffix dedupe) | merge duplicates manually | suffixed filenames visible | low value |
| Detached-HEAD worktree | everything | branch context in evidence (record `detached: true`) | n/a | n/a | evidence block handles it |
| Branch rebased after record | record prose + name survive | old SHA reachability (eventually GC), branch name accuracy | PR number as durable secondary pointer | no | evidence blocks are immutable observations — document, don't repair |
| Branch deleted | record survives | branch name meaning | SHA + repo identity still identify work | no | same |
| Session ends without record_work | transcript (30d Claude / rollout Codex), projectmem events | the durable narrative | reconstruct from transcript within retention; else lost by design (D016 tolerates this) | **no — the top silent-loss path** | Stop/SessionEnd nudge hook is the mitigation |
| Compaction / unexpected termination | Claude: PreCompact hook can preserve (vault repo only today); Codex: PreCompact/PostCompact exist, unwired | in-context nuance | transcript survives compaction on disk | partial | out of scope for Bindle |
| Codex memories off / suppressed by `disable_on_external_context` | everything durable | only soft recall | none needed — by design, memory is never authority | n/a | no |

## Deliverable A — compatibility matrix

Legend: native / MCP (supported through MCP) / hooks (supported through hooks) / manual (manual but
workable) / degraded / unsupported / unknown (pending experiment).

| Capability | Claude Code | Codex |
| --- | --- | --- |
| Session-start context injection | hooks (native SessionStart + additionalContext; om ships it in the vault repo only — consuming repos need a hook or rely on MCP instructions) | hooks (0.146.0, equivalent design) — **unknown** against om's shipped `.codex/hooks.json` (exp. C) |
| Session-end work record | manual (model-invoked `record_work` via CLAUDE.md snippet); deterministic nudge possible via Stop/SessionEnd hook | manual (same, via AGENTS.md); SessionEnd hook exists for out-of-band capture — unknown reliability (exp. 6/7) |
| Pre-compaction preservation | hooks (PreCompact fires; om's transcript backup wired in vault repo only; upstream docs thin) | hooks (PreCompact/PostCompact exist; om's `.codex/hooks.json` omits PreCompact) — degraded |
| Vault retrieval (`recall`, project-scoped) | MCP (full, roots-based identity — confirm via `om health`, exp. 1) | **degraded** (anonymous ⇒ general-scope only) until adapter/upstream fix |
| Vault retrieval (`search`, semantic) | MCP | MCP — possibly full even anonymous (exposure-policy filtered, not caller-scoped) — unknown (exp. 8) |
| Vault writing (`record_work` to project folder) | MCP (native routing to `projects/<name>/`) | **degraded** (inbox fallback) |
| Cross-project memory (`remember`/`recall`) | MCP (declared reach, supersession) | degraded (general scope only; project scope refused) |
| Shared handoff (A records, B resumes) | works | asymmetric until G1 fixed; repo-file handoff (`plans/`) is the fallback |
| Transcript pointer | hooks (`transcript_path` on stdin; not stored in records — template gap) | hooks (same) + rollout path in local state; same template gap |
| Thread/session identifier | native (session_id = transcript filename, stable across resume) | native (thread uuid in filename, `codex resume <id>`, notify payload) |
| Git SHA in session context | manual (hook must derive from cwd) | native (thread header + state DB) — but not in vault records either way |
| Branch | manual (derive) | native (thread header) — same caveat |
| Dirty state | unsupported (derive in hook) | unsupported (no field) — only an evidence-block capture supplies it |
| Worktree identity | mixed native (transcripts split per worktree; auto-memory shared per repo) | cwd-keyed only; no linkage concept |
| Concurrent writes to vault | native-safe (atomic excl. create + suffix) | native-safe (same server code path) |
| Offline operation (vault + search) | native (om + qmd fully local; harness itself needs network) | native (same) |
| Project instructions (AGENTS.md) | via CLAUDE.md `@AGENTS.md` import (currently prose-only in Bindle — fix) | native discovery, root→cwd, 32 KiB cap |
| Provider-native memory as soft recall | native (auto-memory, git-repo-scoped) | native (Memories: off by default, global, advisory) |

## Deliverable B — gap register

| # | Gap | User-visible consequence | Freq | Sev | Workaround | Config fixes? | Bindle adapter? | Blocks adoption? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G1 | Codex sends no MCP roots → om anonymous caller | Codex can't see project memories, records land in inbox, project `remember` refused | every Codex session | **critical** | treat Codex as retrieval-degraded; repo-file handoffs | **no** (om ignores cwd/env for identity) | **yes — thin roots-injecting MCP proxy; or upstream om patch** | blocks the *symmetric* model, not a Claude-first trial |
| G2 | No lifecycle automation in consuming repos (both harnesses) — `record_work` is model-compliance | sessions end without records, silently | common | high | instruction snippet + habit; Stop/SessionEnd nudge hook | partially (hook config) | yes (Bindle ships the hook pair) | no — matches D016 (capture requires a reason) |
| G3 | Zero VCS state in om records | can't tell which branch/SHA/worktree a record describes; rebases silently invalidate context | every record | high | manual evidence line in `verification`/body | no | **yes — this is exactly the Bindle evidence block** | no; it is the adoption *rationale* |
| G4 | Worktree identity forks on folder basename | duplicate project trees per worktree | every worktree | high | — | **yes — commit `.om-project`** | n/a | no |
| G5 | om's `.codex/hooks.json` (Claude schema) unverified against Codex hooks | vault-repo lifecycle may silently not run under Codex | vault sessions | med | run Codex hooks via `~/.codex/config.toml` TOML instead | yes (rewrite in Codex TOML) | trivial | no |
| G6 | Bindle CLAUDE.md loads AGENTS.md by prose, not `@AGENTS.md` import | AGENTS.md inclusion is probabilistic for Claude | every Claude session | med | — | **yes — one-line edit** | n/a | no |
| G7 | No transcript/thread pointer lands in vault records | handoffs can't link back to the source session | every record | med | paste pointer manually | partially | yes (hook feeds pointer into an evidence line) | no |
| G8 | No dirty-state capture anywhere (om, Claude, Codex) | "was the work committed?" unanswerable later | every record | med | manual `git status` note | no | yes (evidence block) | no |
| G9 | Claude PreCompact thinly documented; SessionEnd-on-kill unguaranteed | preservation hooks may not fire in edge exits | rare | low | rely on transcript retention (30 d) | no | no | no |
| G10 | `om health` returns vault absolute path into session context; vault-repo PreCompact copies raw transcripts into vault | private topology can leak into pasted output / vault contents | occasional | med | never paste health output into public repos; session-logs stay gitignored | partially | privacy guard at repo boundary | no |
| G11 | Single-maintainer upstream, 8 majors in 5 months | breaking changes; abandonment risk | ongoing | med | pin a tag; vault data is plain Markdown (exit is cheap — D014 pointer-loss-not-breakage holds) | n/a | n/a | no |

## Deliverable C — minimum safe deployment plan

Smallest trial that does not hide the gaps — deliberately Claude-first, with Codex included *in its
degraded state* so the asymmetry stays visible instead of papered over:

1. **Vault**: fresh clone of obsidian-mind at pinned tag v8.3.1 as the dedicated engineering vault
   (D003; personal vault untouched). Do not resurrect the archived vault; do not create `~/.bindle`
   (it is a dangling symlink into the old Obsidian path — leave it or delete the symlink, decision
   for the user). Vault stays a private git repo.
2. **Repositories**: `bindle` itself first (low stakes); add the second repository after the first week only if
   experiments 1–3 pass.
3. **Claude setup**: `claude mcp add --scope user om node <vault>/.claude/scripts/om-mcp.mjs`; add
   the om CLAUDE.md snippet to consuming repos; change Bindle's CLAUDE.md to import `@AGENTS.md`
   (G6). No other global config changes.
4. **Codex setup**: register om under `[mcp_servers.om]` in `~/.codex/config.toml`. Expect and
   *record* the anonymous-caller behavior — that is data, not failure. No hooks yet.
5. **`.om-project`**: committed and tracked in every consuming repo, one lowercase name matching
   the primary folder (e.g. `bindle`).
6. **Worktree policy**: allowed, with the marker committed. Evidence lines are **conditional, not
   mandatory** (reconciled 2026-08-02): add one — via the `omev` helper in the trial runbook — only
   when a linked worktree is involved, dirty state materially matters, a rebase/squash/force-push
   or branch abandonment is likely, or exact code-state recovery seems plausibly needed later.
   Format: `evidence: project=<label> sha=<12-char> branch=<name|detached> dirty=<n>+<n>u worktree=<basename>`
   (no absolute paths in durable records by default).
7. **Templates**: use om's server-rendered records unmodified (provider-neutral already); the
   evidence line above is the only convention added.
8. **Routing**: exactly the DATA-OWNERSHIP.md routing table — decisions to `docs/DECISIONS.md`,
   working reasoning to projectmem, session narratives to `om record_work`, cross-project lessons
   to `om remember`, preferences to provider memory. No new stores.
9. **Privacy guard**: restore the archived `check-private-info.sh` as a pre-commit hook in the
   public bindle repo *before* any vault-related examples/configs are committed there (per
   PRIVACY.md: restore, don't rewrite). The vault repo itself is private and out of scope.
10. **Manual fallback**: when om is unreachable or capture was missed, write a dated handoff file
    under `plans/` (existing routing rule) and backfill `record_work` later. If a Codex session
    must hand off before G1 is fixed, the `plans/` handoff *is* the mechanism.

## Deliverable D — no-go conditions

- **Abandon entirely** only if: shared writes are shown to lose data (contradicting verified source
  + concurrency tests — would indicate deeper unreliability), or any non-local network path is
  found in the retrieval stack (contradicting verified source).
- **Limit to Claude Code (retrieval-only for Codex)** — the *default posture at trial start* — for
  as long as G1 stands. Escalate to "limit indefinitely" if both the proxy adapter and an upstream
  identity patch prove unworkable (e.g. om hard-rejects non-roots identity and the proxy can't
  satisfy its 2-second roots gate).
- **Delay adoption** if experiment 1 shows Claude Code itself does not deliver roots to om (would
  contradict om's design assumption and gut identity on both sides).
- **Avoid worktrees temporarily** only if the committed `.om-project` fails to unify identity in
  experiment 4 (would contradict verified code — re-audit if so). Otherwise worktrees are fine with
  the evidence-line convention.
- **Use retrieval-only (both harnesses)** if the record/memory contract in practice pressures
  toward vault-as-canonical-store (the archived prototype's failure). Signal: writing records
  without a D016 reason, or treating vault summaries as project authority over `docs/DECISIONS.md`.

## Deliverable E — experiments to resolve unknowns

Run in order; each is manual and cheap. Record outcomes in this file.

1. **Claude writes, Codex reads.** In `bindle` (marker committed), Claude session: call `om health`
   (capture identity + source — verifies Claude sends roots), then `record_work` a real summary.
   Codex session, same cwd: `om health` (expect anonymous — confirms G1), then `recall` and
   `search` for the record. Pass = Claude identity correct; expected partial = Codex sees it via
   `search` but not project-scoped `recall`.
2. **Codex writes, Claude reads.** Codex: `record_work` (expect `inbox/` landing — inspect vault),
   `remember` with `scope: general` (expect success) and `scope: project` (expect refusal). Claude:
   `recall`/`search` for both. Pass = Claude finds the inbox record via search; refusal messages
   match source-predicted behavior.
3. **Both write, one project, same day, same title.** Trigger deliberately colliding
   `record_work` titles from both harnesses. Expect two files, second suffixed `-2`, no loss.
4. **Different worktrees.** `git worktree add ../bindle-wt-gate4 -b trial/gate4`; confirm `.om-project`
   present there; Claude in main checkout + Codex in worktree (and a second Claude session in the
   worktree): `om health` from each — expect identical project identity from Claude sessions in
   both checkouts. Also confirm: transcripts split per worktree, auto-memory dir shared (verifies
   the docs claim locally), projectmem silent no-op in the worktree.
5. **Rebase after record.** Record work on a worktree branch with the evidence line, then rebase
   the branch. Confirm the recorded SHA no longer matches any ref, the PR-number/prose context
   still identifies the work, and nothing in om breaks or warns (expected: silence — documenting
   the silence is the point).
6. **MCP unavailable at session end.** Kill the om server mid-session; ask the harness to
   `record_work`. Observe the failure surface (Claude tool error vs silent skip), then execute the
   manual fallback (dated `plans/` handoff) and time it.
7. **Session ends without capture.** End a real session with no `record_work`. Next day, attempt
   reconstruction from the Claude transcript (`~/.claude/projects/...jsonl` within 30-day retention)
   or Codex rollout. Measure what D016 actually tolerates losing.
8. **Provider-neutral retrieval.** From the harness that did *not* write a given note, retrieve it
   using only project context (no title): `search` with a task-shaped query. Separately resolves
   whether `search` exposure filtering (folder-level) lets anonymous Codex read project notes —
   the difference between "Codex degraded" and "Codex read-mostly workable."
9. **(C from matrix) Codex hooks schema.** In the vault repo, trusted, check whether
   `.codex/hooks.json` (Claude schema) fires under Codex 0.146.0; if not, port one hook to
   `[[hooks.SessionStart]]` TOML and confirm that fires. Determines G5.

No new Bindle features are proposed beyond what the audit grounds in concrete failures: the
roots-injecting proxy (G1), the evidence block (G3/G7/G8), and the Stop/SessionEnd nudge hooks (G2)
— each contingent on the experiments above confirming the friction in practice.
