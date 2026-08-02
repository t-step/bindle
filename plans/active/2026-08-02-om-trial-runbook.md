# Obsidian Mind trial — execution runbook

Date: 2026-08-02. Companion to the interoperability audit and the observation plan in this
directory. This document converts the settled design into a safe, observable experiment. It builds
nothing: no roots proxy, no evidence block, no hooks, no stores, no worktree sync, no retrieval
machinery.

Conventions in this file: `$OM_VAULT` is the private vault path the user chooses at setup;
`<repo>` is this repository's checkout. No personal absolute paths appear here by design.

---

## 1. Reconciliation applied to the trial documents

Changes made 2026-08-02 to the audit and observation plan (both in `plans/active/`):

1. **Five-session checkpoint added** to the observation plan's cadence (template in §5 below).
2. **Evidence lines demoted from mandatory to conditional.** The audit's deployment step 6
   previously required an evidence line in *every* record — that requirement would have counted
   routine omissions as evidence for the evidence-block feature, manufacturing demand. Now a line
   is warranted only when: a linked worktree is involved; dirty state materially matters; a
   rebase, squash, force-push, or branch abandonment is likely; or the user judges exact
   code-state recovery may matter later. The evidence-block build threshold was correspondingly
   tightened: an absent line counts as an omission only when one of those conditions applied.
3. **`.om-project` reclassified as a stable routing label**, not canonical repository identity,
   in both documents and in the marker file's own comment.
4. **Identity model reaffirmed unchanged** (D018): repository identity = git common directory +
   stable remote metadata; routing label = `.om-project`; execution identity = worktree path;
   code-state identity = commit SHA + dirty state; branch = mutable descriptive context only.
5. **Trusted-wrong-context measure added** to the rubric: records retrieved, *trusted*, and later
   found to describe another branch, abandoned work, superseded architecture, or the wrong
   project. Logged as `ret-wrong`/`failure`; treated as the most serious rubric signal.
6. **Unconsulted ≠ useless.** The synthesis now classifies never-consulted records three ways:
   not consulted during the trial window / judged unnecessary / plausibly useful over a longer
   horizon.

Contradictions found and resolved: the mandatory-evidence-line requirement (above) was the only
demand-manufacturing item. Stale item fixed outside the trial docs: CLAUDE.md's orientation said
"D001–D013"; the log now runs to D018. No other contradictions between audit and plan were found.

---

## 2. Deployment checklist

Every step lists its change class:
**[repo]** repository change suitable for commit · **[vault]** vault-local · **[machine]**
machine-local configuration · **[private]** private file, never committed anywhere public ·
**[disposable]** trial artifact, deletable after synthesis.

### Phase 0 — already applied in this pass (uncommitted repo changes + one machine change)

- **[repo]** `.om-project` created (routing label `bindle`, with a comment stating it is not
  canonical identity).
- **[repo]** `CLAUDE.md` now imports `@AGENTS.md` deterministically; AGENTS.md remains the single
  authoritative shared policy file, unmodified by this pass.
- **[repo]** `bin/check-private-info.sh` + `bin/test-check-private-info.sh` restored verbatim from
  the archived prototype (restore-not-rewrite per docs/PRIVACY.md). Self-test passes 20/20.
- **[machine]** dangling `~/.bindle` symlink removed (it pointed into a deleted vault path; any
  naive `~/.bindle` write would have re-materialized inside that tree). If it is ever needed
  again: `ln -s "<former vault path>" "$HOME/.bindle"` — the former target is recorded in the
  private trial log, not here.

### Phase 1 — machine-local preparation

Status 2026-08-02: **done on the primary machine** — the guard block was appended to the existing
projectmem pre-commit hook (below its comment fence), with the denylist path baked into the hook
so it works for commits from any environment; `~/.config/bindle/private-denylist.txt` exists but
is **empty — populate it** with private codenames, employer names, hostnames, and vault names.
Verified by staging a synthetic home-path leak: the hook blocked the commit (exit 1) and passes a
clean tree. The steps below remain the reference for other machines.

The privacy guard's default denylist home was `~/.bindle` (now gone). Repoint it:

```sh
mkdir -p "$HOME/.config/bindle"
touch "$HOME/.config/bindle/private-denylist.txt"        # [private] one term per line; never commit
# add to your shell profile:
export BINDLE_DENYLIST="$HOME/.config/bindle/private-denylist.txt"
```

Populate the denylist with: private project codenames, employer names, personal hostnames, vault
names. A guard run without it still checks patterns and *says so* (verdict disclosure) — but the
denylist is the half that protects your specific topology.

Install the pre-commit guard hook in this repository (machine-local; hooks are untracked; the
guard must **compose with** whatever already runs, never overwrite it). First check where hooks
actually live and whether a pre-commit hook already exists:

```sh
cd "<repo>"
hooks_dir=$(git config --get core.hooksPath || echo .git/hooks)
ls -la "$hooks_dir/pre-commit" 2>/dev/null   # if this exists, APPEND the guard call to it —
                                             # do not replace the file
```

If no pre-commit hook exists yet, create one (safe for filenames with spaces on macOS's
Bash 3.2 — NUL-delimited list, quoted array expansion):

```sh
cat > "$hooks_dir/pre-commit" <<'EOF'
#!/usr/bin/env bash
# privacy guard on staged files (docs/PRIVACY.md).
# Composition rule: if other pre-commit checks are added later, add them here —
# this file is the single pre-commit entry point, and the guard is one step in it.
export BINDLE_DENYLIST="${BINDLE_DENYLIST:-$HOME/.config/bindle/private-denylist.txt}"
files=()
while IFS= read -r -d '' f; do files+=("$f"); done \
  < <(git diff --cached --name-only --diff-filter=ACM -z)
[ "${#files[@]}" -eq 0 ] && exit 0
bin/check-private-info.sh "${files[@]}"
EOF
chmod +x "$hooks_dir/pre-commit"
```

If a pre-commit hook already exists, append the guard lines (the `files=()` block and the
`check-private-info.sh` call) after the existing content instead — never replace the file.
**In this repository that is the actual case**: projectmem's `pjm hooks install` already owns
`.git/hooks/pre-commit` (a `pjm precheck --level warn` safety net, marked with
`>>> projectmem auto-capture >>>` comment fences) — append the guard block below its closing
fence. Cocogitto owns `commit-msg`. The guard must never displace either.

### Phase 2 — vault creation (user-run) [vault][private]

```sh
export OM_VAULT="$HOME/<your-private-vault-location>/bindle-mind"   # choose; keep out of any public tree
git clone --branch v8.3.1 --depth 1 https://github.com/breferrari/obsidian-mind "$OM_VAULT"
cd "$OM_VAULT"
git rev-parse HEAD           # record this pinned commit in the trial log (expect the v8.3.1 tag commit, 538522e…)
git remote rename origin upstream   # upstream stays for updates; NEVER add a public push remote
git switch -c private-main          # local branch for your own vault commits
node --version                      # om requires Node 22+
```

The vault is separately version controlled (its own git repo) and private. **The user owns the
durable Markdown vault** — plain files, readable and portable with no tooling at all; Obsidian
Mind supplies the conventions, indexing, and integration machinery *around* that corpus, and can
be removed or replaced without touching its contents. Bindle owns none of it (D015); losing om
costs machinery, never the Markdown.

Create the trial log location and skeleton (§4):

```sh
mkdir -p "$OM_VAULT/thinking/trial"
$EDITOR "$OM_VAULT/thinking/trial/om-trial-log.md"   # paste skeleton from §4.1
```

[disposable] Everything under `thinking/trial/` may be deleted after synthesis.

Optional but recommended — semantic search (local models, no API keys), with the trial log
excluded from indexing **before** the index is first built:

```sh
npm i -g @tobilu/qmd
# In Obsidian: Settings → Files & Links → Excluded files → add "thinking/trial/"
#   (qmd's bootstrap syncs its ignore list from .obsidian/app.json userIgnoreFilters),
# or edit "$OM_VAULT/.obsidian/app.json" and add "thinking/trial/" to userIgnoreFilters.
node --experimental-strip-types "$OM_VAULT/.scripts/qmd-bootstrap.ts"
# first search triggers local model downloads; verify offline afterwards if desired
```

If you skip qmd, om's `search` degrades to lexical — acceptable baseline; note it in the log.

### Phase 3 — MCP registration (user-run) [machine]

Shown, not executed by this pass (these modify live harness configuration):

```sh
# Claude Code (user scope; writes to your user-level MCP config):
claude mcp add --scope user om -- node "$OM_VAULT/.claude/scripts/om-mcp.mjs"

# Codex (writes [mcp_servers.om] into ~/.codex/config.toml):
codex mcp add om -- node "$OM_VAULT/.claude/scripts/om-mcp.mjs"
```

**Codex hooks stay disabled for the baseline.** Do not add any `[[hooks.*]]` blocks for the trial.
Note: `~/.codex/config.toml` currently contains a leftover experimental SessionStart echo hook,
installed twice (found during the audit). It is unrelated to om; removing the duplicate block is
recommended for a clean baseline, but is your call — if kept, remember it fires on every session.

### Phase 4 — repository trial snippet [repo, proposed — apply before first trial session]

om's docs require an instruction snippet in the consuming repo. Per D017 the shared copy belongs
in AGENTS.md (Claude receives it via the `@AGENTS.md` import; Codex reads it natively). Proposed
addition — a new short section at the end of AGENTS.md, removed at trial end:

```markdown
## Obsidian Mind trial (temporary)

An `om` MCP server may be registered during the current trial.

* Route session narratives worth keeping to `om record_work`; cross-project lessons to
  `om remember`. The routing table in docs/DATA-OWNERSHIP.md governs; accepted decisions still go
  to docs/DECISIONS.md, never only to the vault.
* Durable capture requires a reason (D016). Do not record to satisfy tooling.
* Codex sessions: om currently sees an anonymous caller. Prefer `om search` over `recall`, and
  expect writes to land in the vault inbox. Do not work around this silently — it is under
  observation.
* `.om-project` is a routing label only; repository identity remains the git common directory (D018).
* Evidence lines in records are conditional; see plans/active/2026-08-02-om-trial-runbook.md.
```

### Phase 5 — run the four gates (§3), then begin real work.

---

## 3. Startup gates

Record every gate outcome as a trial-log line (transition `probe`, or the matching code) plus the
pasted key output. Gates 2–4 use *genuine* work products, not synthetic text.

### Gate 1 — Claude identity

- **Action**: from `<repo>` (primary checkout), in a Claude Code session: call the `om` MCP tool
  `health`. No shell commands involved.
- **Pass iff**: caller is not anonymous; identity source is the `.om-project` marker; project
  resolves to `bindle`; the reported vault path is `$OM_VAULT`.
- **Failure interpretation**: anonymous ⇒ Claude did not deliver MCP roots (would contradict om's
  design assumption — a genuinely new finding; recheck registration first). Wrong project ⇒ marker
  malformed or a different root won the handshake. Wrong vault ⇒ stale registration or
  `OM_VAULT_PATH` interference.
- **Blocks trial?** **Yes.** Nothing downstream is meaningful without Claude-side identity.
- **Log**: identity, identity source, vault path (redact the absolute path to `$OM_VAULT` if the
  log line will ever leave the vault).

### Gate 2 — Claude writes, Codex reads

- **Action**: in a Claude session, `record_work` one genuine record of real work (e.g. this
  preparation pass). Verify in the vault where it landed (`projects/bindle/notes/` expected) and
  read its routing footer. Then in a Codex session from the same directory: (a) call `om health`
  (expect anonymous — paste exact output), (b) attempt project-scoped `recall`, (c) attempt
  `search` with a task-shaped query about the record's content.
- **Expected**: recall withholds or misses the record (G1); search may or may not surface it —
  this distinguishes "Codex degraded" from "Codex read-mostly workable" (audit experiment 8).
- **Failure interpretation**: recall miss = predicted provider limitation (`prov`), not a trial
  failure — it is the observation. Search *also* failing = Codex read path unusable ⇒ Codex
  participates via repo files (`plans/` handoffs) only. Codex health non-anonymous = the audit's
  central claim is wrong ⇒ re-audit before trusting any G1-based threshold.
- **Blocks trial?** No. Any outcome is data. Claude-first posture already assumes degradation.
- **Log**: what succeeded / failed / was withheld, verbatim withheld counts if shown, minutes spent.

### Gate 3 — Codex writes, Claude reads

- **Action**: in a Codex session, `record_work` one genuine record. Then: (a) find where it landed
  (`inbox/` expected) — `ls` the vault; (b) confirm the file is complete and well-formed (atomic
  write: no partial/temp files left behind; frontmatter intact); (c) in a Claude session, retrieve
  it via `search`/`recall` and judge whether Claude understands it without explanation; (d) move or
  re-file the record to the project folder if desired, timing the manual routing cost.
- **Pass iff**: the write landed intact somewhere findable, and Claude can retrieve and understand it.
- **Failure interpretation**: corrupted/partial file ⇒ serious (contradicts verified atomic-write
  source) ⇒ stop and re-audit. Inbox landing ⇒ expected (`prov`, G1); the interesting measurement
  is (d), the manual cost.
- **Blocks trial?** Only on write corruption. Inbox routing never blocks.
- **Log**: landing path, intactness, retrieval outcome, manual re-routing minutes.

### Gate 4 — linked worktrees

- **Action** (shell, from `<repo>`):

  ```sh
  git worktree add ../bindle-wt-gate4 -b trial/gate4
  cat ../bindle-wt-gate4/.om-project        # marker must be present (tracked file)
  ```

  Then: a Claude session in `../bindle-wt-gate4` calls `om health`; do a small real task; check
  provider state from either terminal:

  ```sh
  ls ~/.claude/projects/ | grep -i bindle   # expect a NEW munged dir for the worktree (transcripts split)
  # memory scoping: note which memory directory the worktree session reports/uses —
  # docs say auto-memory is git-repo-keyed (shared). Record what actually happens.
  ```

  If any durable record is written from the worktree, add an evidence line intentionally (this is
  a worktree — the conditional policy applies) via `omev` (§6).
  Cleanup: `git worktree remove ../bindle-wt-gate4 && git branch -D trial/gate4`.
- **Pass iff**: `om health` in the worktree reports project `bindle` via the marker (same routing
  label); Claude transcripts appear under a new worktree-specific directory; auto-memory behaves
  as documented (shared) — record the observation either way; no durable record confuses the two
  checkouts (the evidence line disambiguates).
- **Failure interpretation**: identity forks despite the marker ⇒ contradicts verified om source ⇒
  re-audit; do multi-worktree work without om records until resolved. Memory NOT shared ⇒ docs
  drift — update docs/WORKTREES.md's provider-behavior section; not blocking.
- **Blocks trial?** Identity fork blocks *worktree use in the trial*, not the trial itself.
- **Log**: health output from both checkouts, the `ls` evidence, memory observation, the evidence
  line used.

---

## 4. Observation apparatus

### 4.1 Trial log skeleton [private][disposable] — `$OM_VAULT/thinking/trial/om-trial-log.md`

```markdown
# om trial log — private, disposable after synthesis
vault pinned at: obsidian-mind v8.3.1 (<full SHA from git rev-parse HEAD>)
trial start: YYYY-MM-DD · repos: bindle (second repo added: ____)
format: ts | repo | harness | worktree | TRANSITION | outcome | TAX | Nm | free text
taxonomy: cfg prov ident life ret-miss ret-wrong route wtree auth priv cerem seam
transitions: CC CX XC WT+ WT- S>R R>S E>PM D>DOC TMP>0 L>GH OUT probe

## Gates
(4 gate outcomes here, with pasted key output)

## Log
2026-08-0? 00:00 | bindle | claude | main | probe | smooth | - | 0m | example line

## EOD entries
(template: observation plan §7)

## Five-session checkpoint
(template: runbook §5)
```

### 4.2 End-of-day review — unchanged, observation plan §7 (four questions + one tally line).

### 4.3 Five-session checkpoint template (run after 5 meaningful sessions; ≤ 10 minutes)

```markdown
## Checkpoint — session 5 — YYYY-MM-DD
1. Useful enough to continue? (did om save real time/context at least once — cite a log line)
2. Is Codex's anonymous identity causing real obstruction? (count `prov`/G1 lines + minutes so far)
3. Is the observation process tolerable? (skipped days? simplify per the built-in rule?)
4. Any authority, privacy, or incorrect-context problem? (`auth` / `priv` / `ret-wrong` lines — quote them)
5. Verdict: continue unchanged / simplify observation / stop trial.
NO feature decisions here — unless a serious privacy, correctness, or data-loss failure forces stop.
```

### 4.4 End-of-trial synthesis — observation plan §8 (now includes the three-way never-consulted
classification and the trusted-wrong-context count).

---

## 5. (reserved — checkpoint covered in §4.3)

## 6. Temporary evidence helper — experimental apparatus, NOT a Bindle feature

Paste into your shell profile for the trial (or a scratch rc file you source); delete at trial end.
Not added to the Bindle repo's tooling; it graduates only if the evidence-block threshold in the
observation plan is met.

```sh
# omev — print a portable evidence line for pasting into a work record (trial apparatus).
# No absolute paths: worktree is identified by basename only.
omev() {
  git rev-parse --git-dir >/dev/null 2>&1 || { echo "omev: not in a git repo" >&2; return 1; }
  local label sha branch tracked untracked wt
  label=$(grep -m1 -Ev '^[[:space:]]*(#|$)' .om-project 2>/dev/null | tr -d '[:space:]')
  [ -n "$label" ] || label=$(basename "$(git rev-parse --show-toplevel)")
  sha=$(git rev-parse --short=12 HEAD 2>/dev/null || echo "no-commit")
  branch=$(git symbolic-ref --quiet --short HEAD || echo "detached")
  tracked=$(git status --porcelain 2>/dev/null | grep -c -v '^??')
  untracked=$(git status --porcelain 2>/dev/null | grep -c '^??')
  wt=$(basename "$(git rev-parse --show-toplevel)")
  printf 'evidence: project=%s sha=%s branch=%s dirty=%s+%su worktree=%s\n' \
    "$label" "$sha" "$branch" "$tracked" "$untracked" "$wt"
}
```

Example output: `evidence: project=bindle sha=4656722a9b1c branch=trial/gate4 dirty=2+1u worktree=bindle-wt-gate4`

Use it only when the conditional policy applies (§1 item 2).

---

## 7. Files changed or proposed

| File | State | Class |
| --- | --- | --- |
| `.om-project` | created, uncommitted | [repo] commit candidate |
| `CLAUDE.md` | edited (`@AGENTS.md` import; D-range fix), uncommitted | [repo] commit candidate |
| `bin/check-private-info.sh`, `bin/test-check-private-info.sh` | restored from archive, uncommitted | [repo] commit candidate |
| `plans/active/2026-08-02-obsidian-mind-interop-audit.md` | reconciled + sanitized, untracked | [repo] commit candidate after guard passes |
| `plans/active/2026-08-02-om-trial-observation-plan.md` | reconciled + sanitized, untracked | [repo] commit candidate after guard passes |
| `plans/active/2026-08-02-om-trial-runbook.md` | this file, untracked | [repo] commit candidate after guard passes |
| AGENTS.md trial section | **proposed only** (§2 Phase 4) — apply before first trial session | [repo] |
| `.git/hooks/pre-commit` | proposed command (§2 Phase 1) | [machine] |
| `~/.bindle` symlink | removed (was dangling) | [machine] |
| `$HOME/.config/bindle/private-denylist.txt` + `BINDLE_DENYLIST` | proposed (§2 Phase 1) | [private] |
| `$OM_VAULT` (vault clone, trial log, qmd index) | proposed (§2 Phase 2) | [vault]/[private]/[disposable] |
| Claude user-scope MCP entry; `~/.codex/config.toml` `[mcp_servers.om]` | proposed commands (§2 Phase 3) | [machine] |

Silent-divergence check: the only configurations that could make the harnesses diverge silently
are (a) instructions duplicated outside AGENTS.md — avoided: the trial snippet has one copy, in
AGENTS.md; (b) Codex hooks running while Claude's don't or vice versa — avoided: no hooks in the
baseline; (c) per-harness MCP registrations pointing at different vaults — mitigated: both
registrations use the same `$OM_VAULT` literal; Gate 1/2 `health` calls verify.

## 8. Privacy review result

See the review appended at the bottom of this pass's summary; procedure and findings:

- `bin/check-private-info.sh --self-test`: 20/20 fixtures pass (patterns verified working).
- Guard run over all changed/new files: performed this pass, with no denylist loaded yet (verdict
  disclosure applies — pattern rules only until Phase 1 creates the denylist).
- Manual sanitization already applied: the second private repository's name and personal
  `~/Developer/...` topology were removed from both trial documents (replaced with `<repo-2>` /
  `<dev>` placeholders); a personal first-name reference replaced with "the user".
- Remaining rule for the trial: gate outputs pasted into the trial log may contain `$OM_VAULT`'s
  absolute path — the trial log lives in the private vault and is never committed to a public
  repository; nothing pasted from `om health` may enter this repo.

## 9. Rollback — remove om integration without losing repository work

All real work lives in git, repository docs, and projectmem; om holds only records and pointers,
so removal costs pointers, never work (D014/D015).

```sh
# 1. Deregister MCP (machine-local):
claude mcp remove --scope user om
codex mcp remove om        # or delete the [mcp_servers.om] block in ~/.codex/config.toml

# 2. Repository (if trial changes were committed, revert; if not, discard selectively):
git rm .om-project                       # only if om is abandoned entirely
#   remove the "Obsidian Mind trial (temporary)" section from AGENTS.md
#   CLAUDE.md @AGENTS.md import: KEEP — it is correct independent of om
#   bin/check-private-info.sh: KEEP — independent value, per docs/PRIVACY.md

# 3. Vault: archive rather than delete if any records matter (plain Markdown, greppable forever):
mv "$OM_VAULT" "$HOME/<archive-location>/bindle-mind-trial"
# or delete outright if synthesis says nothing is worth keeping

# 4. Optional cleanup:
npm rm -g @tobilu/qmd     # and remove ~/.config/qmd/<index>.yml + its index store
rm -rf "$OM_VAULT/thinking/trial"   # trial log, after synthesis
unset -f omev              # remove helper from shell profile
```

## 10. Intentionally unbuilt (unchanged by this pass)

MCP roots proxy · Git evidence block · lifecycle/capture hooks (both harnesses) · any session
store · any memory store · worktree synchronization · new retrieval machinery · worktree
diagnostics. Each stays unbuilt until its threshold in the observation plan §6 is met by trial
evidence. The `omev` function and the trial log are disposable apparatus, not features.

## 11. Begin

Single next command (starts Phase 2; Phases 0 partial-done, 1 are local prep you can do in any
order before the gates):

```sh
export OM_VAULT="$HOME/<your-private-vault-location>/bindle-mind" && \
  git clone --branch v8.3.1 --depth 1 https://github.com/breferrari/obsidian-mind "$OM_VAULT"
```
