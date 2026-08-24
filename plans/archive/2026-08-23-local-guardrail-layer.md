# Local development guardrail layer: protected main + hardened secrets policy

Date: 2026-08-23. Status: **complete — merged to `main` via PR #10, 2026-08-24.**

## Outcome

A small, portable, user-owned enforcement layer for two already-adopted policies that today are
instruction-only:

1. `main` is the canonical clean integration branch. Routine agent/tooling workflows may inspect,
   fetch, fast-forward-sync, and branch from `main`, but must not commit, merge, rebase, cherry-pick,
   or otherwise mutate it directly — with a narrow, explicit, non-persisting escape hatch for rare
   intentional writes.
2. AGENTS.md's existing secret/credential-file policy (D012) gets Claude-native permission
   enforcement instead of remaining prose-only.

This is a guardrail slice, not a hook-management subsystem, branch manager, or security product —
see "Explicitly out of scope" below.

## Why now

Nothing currently enforces either policy mechanically. `docs/PRIVACY.md`'s own personal-disclosure
guard is documented but "not currently active" in a fresh checkout by design (hooks aren't tracked by
Git) — the same gap exists for protected-main and for D012's secret-file policy, which today is prose
in AGENTS.md with zero mechanical backing. The user asked for the smallest guardrail that closes both
gaps, worked out interactively (see Decisions below) after a research pass grounded the design in this
repository's actual current state rather than assumptions.

## Scope

**In scope:** a global Git hook composition layer (protects `main` locally, across every repo on the
machine, without disabling any repository's own hooks); a user-level Claude Code `PreToolUse` guard
mirroring the same policy for `Edit`/`Write`/`MultiEdit`/`NotebookEdit`; a one-shot authorization
capability for the Claude layer (env-var scoping isn't available to non-shell tool calls);
`permissions.deny`/`allow` rules hardening the existing secret-file policy; a preview-first installer;
focused regression tests.

**Out of scope (explicitly deferred, not silently dropped):** automatic branch/worktree creation,
branch naming policy, a generalized hook registry/DSL, arbitrary command interception, destructive-
command confirmation unrelated to protected main, test/lint/format orchestration, evidence capture,
telemetry, session-start context injection, stale-worktree cleanup, generalized security scanning
(D012 hardening ≠ a new security capability — see `docs/SCOPE.md`'s "Bindle does not own: security
scanning" alongside its "Bindle owns: hooks at tool seams"), any new dependency.

## Evidence

Everything below was empirically observed in this repository/session, not assumed, per the user's
explicit instruction to verify rather than guess.

**Repository architecture (research pass, before design):**
- No `core.hooksPath` set anywhere (local or global) — clean slate for the git-layer install.
- Only `commit-msg` (Cocogitto, via `cog.toml`'s `[git_hooks.commit-msg]`) and `post-commit`/
  `post-merge` (projectmem, `pjm hooks install`) are actually installed today. `docs/PRIVACY.md`'s
  `pre-commit` guard is documented but dormant in this checkout.
- `docs/WORKTREES.md`: git-common-dir is shared repository identity across linked worktrees; "a shared
  hook implementation is fine and expected." Branch name is "descriptive context, never primary
  identity" *except* that this feature's entire job is checking the branch name.
- `~/.claude/settings.json` already has a proven, non-brittle precedent for exactly this kind of guard:
  `subagent-limit-guard` reads stdin JSON (`session_id`, `agent_id`), never parses command strings, and
  returns `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", ...}}`.
  No existing `PreToolUse` matcher covers `Edit|Write|MultiEdit`; no `permissions.deny` block exists.
- PLAN.md: `main` already carries a GitHub server-side ruleset. This slice is specifically the *local*
  layer; `pre-push` is therefore out of scope (remote is already covered).
- `scripts/doctor.sh` is deliberately read-only workstation-readiness diagnostics, not repository
  working-state policy — confirmed out of scope for a dirty-main check (see Decisions).

**Git hook-firing behavior (fixture repos, this session, git 2.55.0) — this directly overturned the
initial assumption that `pre-commit` alone would cover "commit, merge, rebase, cherry-pick":**

| Operation | Hooks that fired (relevant subset) |
|---|---|
| plain `git commit` | `pre-commit` → `prepare-commit-msg` → `commit-msg` → `post-commit` |
| non-fast-forward `git merge --no-ff` | `pre-merge-commit` → `prepare-commit-msg` → `commit-msg` → `post-merge` |
| fast-forward `git merge --ff-only` | `post-merge` only — **no `pre-commit`, no `pre-merge-commit`** |
| `git rebase` (replaying commits) | `pre-rebase` → `post-checkout` → `prepare-commit-msg` → `post-commit` → `post-rewrite` — **`pre-commit` and `commit-msg` do NOT fire for replayed commits** |
| `git cherry-pick` | `prepare-commit-msg` → `post-commit` — **`pre-commit` and `commit-msg` do NOT fire** |
| `git am` | `applypatch-msg` → `pre-applypatch` → `post-applypatch` — **an entirely separate hook family; none of `pre-commit`/`prepare-commit-msg` fire** |
| `git commit --no-verify` | `prepare-commit-msg` still fires and can still block the commit — `--no-verify` only skips `pre-commit` and `commit-msg` |

Conclusion: `pre-commit` alone does not cover rebase-replay, cherry-pick, or `--no-verify`.
`prepare-commit-msg` is the broadest single interception point observed (covers commit, merge,
rebase-replay, and cherry-pick, and survives `--no-verify`), but does not cover `git am` at all — that
requires `pre-applypatch` separately. Fast-forward sync fires neither hook Bindle has policy for, so
it needs no special-casing to remain unaffected.

**Known, honestly-documented gap:** `git reset`, direct ref manipulation (`update-ref`, hand-editing
`.git/refs`), a hook-unaware Git client, or a repository with its own local `core.hooksPath` override
are not coverable by client-side hooks — no standard Git hook fires for any of them. No mechanism in
this slice claims otherwise.

**Claude Code mechanics (grounded via claude-code-guide, official docs):**
- `PreToolUse` stdin JSON includes `session_id`, `cwd`, `tool_name`, `tool_input.file_path` (for
  Edit/Write) — stable for the session's lifetime.
- Decision output: exit `2` (reason on stderr) to deny; or exit `0` with
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"|"allow"|"ask",
  "permissionDecisionReason": "..."}}` on stdout. Allow is exit `0` with no output.
- `permissions.deny` always overrides a matching `permissions.allow` — an allow rule cannot carve an
  exception out of a broader deny. Read/Edit rules use gitignore-style globs; a bare filename pattern
  like `Read(.env)` matches only the literal name `.env`, not `.env.example` (different glob), so
  precision in the deny pattern — not a competing allow rule — is what keeps example files readable.
- No `settings.d`-style include mechanism exists; list-valued keys (`hooks.PreToolUse`,
  `permissions.deny`) merge across files at different precedence *levels*, but two writers appending to
  the *same* file's array must do a real structural JSON merge (`jq`) to avoid clobbering each other.
- **Checked and dropped, not shipped:** `CLAUDE_CODE_SESSION_ID` is present in the `Bash` tool's
  subprocess environment on this machine, and `PreToolUse` stdin JSON separately carries its own
  `session_id` field — but a documentation review (2026-08-23, after the initial implementation) found
  no citable source, official or otherwise, establishing that these two identifiers carry the same
  value. Binding the one-shot capability to an unverified identifier would be a best-effort security
  property presented as a guaranteed one, so the capability does not attempt session binding at all —
  see Decisions #2, revised.

## Decisions

Recorded here first; a durable architecture-level entry goes to `docs/DECISIONS.md` (D031) once
implementation confirms nothing material changed.

1. **Git-layer composition: one generic dispatcher, symlinked under every standard client-side hook
   name, not three separate scripts.** Setting `core.hooksPath` globally redirects Git's hook lookup
   for *every* hook name, not just the ones Bindle has policy for — three dispatchers would silently
   disable `commit-msg`, `post-commit`, `post-merge`, `pre-push`, and everything else a repo (Cocogitto,
   projectmem, any third-party repo) already relies on. Instead: one implementation file, installed
   once, symlinked under every standard client-side hook name Git ships (from `githooks(5)`, excluding
   server/bare-repo-only hooks and `p4-*`). The dispatcher inspects `$(basename "$0")` to know which
   hook it's running as. For the five hooks where Bindle has policy (`pre-commit`, `pre-merge-commit`,
   `prepare-commit-msg`, `pre-rebase`, `pre-applypatch` — chosen from the evidence table above, not the
   original three-hook guess), it evaluates the branch/override check first; for every hook name, after
   any policy check passes (or there is none), it transparently execs the repository's own hook at
   `$(git rev-parse --path-format=absolute --git-common-dir)/hooks/<name>` if one exists there, else
   exits 0. This path is resolved directly against the filesystem, not through another `core.hooksPath`
   lookup, so there is no recursion risk. If a different `core.hooksPath` is already configured globally,
   the installer refuses to replace it and reports the conflict rather than attempting arbitrary
   composition with an unknown existing hook manager.

2. **Claude-layer one-shot capability, not a session-wide override — repo + worktree + TTL +
   single-use, no session binding.** `Edit`/`Write`/`MultiEdit`/`NotebookEdit` are tool calls, not
   shell invocations — they cannot receive a command-scoped `ALLOW_MAIN_WRITE=1` prefix the way a
   `Bash`-issued `git commit` can. The user resolved this explicitly: a helper
   (`bin/allow-main-write.sh`, run only after the user explicitly authorizes a one-off edit in the
   current conversation — never inferred from the task) mints a token bound to repository identity,
   exact worktree, and a 300-second TTL as a stale-token backstop, single use. A session-bound variant
   was implemented and tested first, then removed on release review (2026-08-23) once a documentation
   check found no citable source establishing that the session identifier a `Bash` subprocess can
   observe (`CLAUDE_CODE_SESSION_ID`) is the same identifier `PreToolUse` hooks receive on stdin
   (`session_id`) — shipping an unverified binding would present a best-effort property as a guaranteed
   one. The guard atomically claims the token (a `mv`-based rename, the smallest portable
   exclusive-claim mechanism — fails cleanly under a concurrent race) and consumes it on first attempted
   use whether or not it validates, so a stale or mismatched token cannot linger for reuse. This is
   deliberately a *different* mechanism from the git-layer's `ALLOW_MAIN_WRITE=1`, not a replacement
   for it — Git/shell writes keep using the
   command-scoped env var.

3. **`main` is a hardcoded literal, not a configurable/discovered default branch.** Matches Bindle's
   own stated opinion and the explicit instruction not to generalize default-branch discovery for this
   slice. A repository whose integration branch is `master` or something else is simply not covered —
   named as a limitation, not solved speculatively.

4. **`scripts/doctor.sh` is untouched.** It is workstation/toolchain readiness diagnostics, not
   repository working-state policy, per explicit correction — dirty-main surfacing instead lives in the
   git-layer guard's own block message (useful error at the point of an actually-attempted mutation),
   not a new standing check.

5. **Secret-file deny patterns are precise, not blanket.** `*.pem` is not blanket-denied — PEM is
   commonly a *public* certificate format (`cert.pem`, `fullchain.pem`), and a blanket deny would train
   false confidence. Deny patterns target actual private-key/credential shapes
   (`.env`, `.env.local`, `.env.*.local`, `id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `id_dsa*`, `*.pfx`,
   `*.p12`, `privkey.pem`, `*-key.pem`, `*_key.pem`, `secrets/**`), matching AGENTS.md's own named list
   plus the narrowest reasonable extension for conventionally-named private keys. `.env.example` and
   `.env.template` are readable by construction (the deny patterns don't match those filenames — no
   competing allow rule is needed or would work, since deny always wins over allow). The honest gap —
   a private key saved under an unrecognized filename, or content-based detection (Grep matching
   secret content inside a directory scan) — is documented, not glossed over.

6. **No CLI changes.** Everything ships as `bin/*.sh`, matching the existing `bin/check-private-info.sh`
   convention, rather than extending the (currently minimal) `bindle` CLI. This keeps the hook payload
   dependency-free and portable to *any* repo on the machine, including ones with no relationship to a
   Python/uv environment — a hook firing in an arbitrary third-party repo cannot assume `bindle` is on
   PATH or that `uv` is available, but POSIX `sh` + `git` always are.

7. **`permissions.deny` uninstall ownership is tracked as a delta, not re-derived from the generated
   manifest (PR #10 review).** The original `--uninstall` computed "what to remove" as the same
   `DENY_MANIFEST` `--apply` generates, using a plain array-difference — which would delete a
   user-added (or otherwise pre-existing) entry that happened to be byte-identical to one of Bindle's
   own rules, since a flat string array has no per-entry provenance. Fixed with the smallest mechanism
   that resolves it: `OWNED_DENY_FILE` (`$GUARD_HOME/claude-deny-owned.json`) records only the entries
   that were genuinely NEW at the moment of each `--apply` (computed by diffing against `.permissions.deny`
   *before* merging); `--uninstall` removes only what's recorded there, never the full manifest, and
   clears the record afterward. A regression fixture (`bin/test-install-guardrails.sh`) seeds a
   settings.json with `Read(.env)` already present, installs, uninstalls, and asserts it survives.

8. **One-shot token write is atomic; consumption is fail-closed against any malformed shape (PR #10
   review).** `bin/allow-main-write.sh` now writes to a same-directory temp file and `mv`s it into
   place, so the guard can never observe a partially-written token. `bin/claude-protected-main-guard.sh`
   validates the claimed token's structure (object, non-empty `common_dir`/`worktree` strings, a whole-
   number `expires_at`) before extracting any field, and reads via `cat` (suppressible) rather than a
   file redirection (which prints an uncatchable shell-level error on an unreadable file regardless of
   the script's own stderr handling). A first pass introduced a *second* instance of the same underlying
   bug — `claim_content="$(cat ... 2>/dev/null)"` still aborts the script under `set -e` when `cat`
   itself fails, since a plain assignment isn't a `set -e`-exempt context — caught by testing the actual
   exit code (`guard_denies_cleanly`), not just the printed decision, against a chmod-000 token; fixed
   with `|| claim_content=""`. Verified empirically against six malformed shapes (empty, truncated,
   wrong top-level type, non-numeric/fractional `expires_at`, missing field) plus an unreadable file —
   all now deny cleanly (exit 0, valid deny JSON), never crash.

9. **Single-consumer claim verified under genuine concurrency, not just sequential reuse (PR #10
   review).** The `mv`-based atomic claim was already covered by a "same token, second sequential
   use is denied" test; a new regression backgrounds two real OS processes racing the same token and
   asserts exactly one is allowed and the other denied (not silently dropped) — stable across repeated
   runs, since the guarantee comes from the `rename(2)` syscall's atomicity, not from test timing.

10. **Installer failure handling: never claim success after a failed settings.json/ownership-record
    read or write (PR #10 review).** Every mutating `jq` call in `bin/install-guardrails.sh` was
    a bare `jq ... >tmp && mv tmp DEST` followed by an *unconditional* `did "..."` — a failure (malformed
    input, a failed temp-file write, a failed rename) silently printed a success marker and left `fail`
    at 0. Fixed with a shared `jq_atomic_write` helper (same-directory temp file, same atomicity property
    as `bin/allow-main-write.sh`'s token write) whose callers now branch on its return code — `did` only
    on confirmed success, `problem` (which sets `fail=1`) otherwise. An existing `settings.json` is now
    validated as parseable JSON before either `--apply` or `--uninstall` touches it; malformed content is
    refused, not silently propagated or overwritten. The `permissions.deny` merge/removal reorders around
    the ownership record: the record is written to `OWNED_DENY_FILE` *before* `settings.json` is touched,
    so a failure recording ownership can never leave the installer claiming success while settings.json
    holds entries the record doesn't know about — the only possible drift runs the harmless direction
    (record lists an entry not yet actually present in settings.json, which a later apply/uninstall's set
    operations treat as a no-op). `read_owned_deny_json` no longer collapses "file exists but is corrupt"
    into the same "[]" result as "file legitimately absent" — a present-but-broken `claude-deny-owned.json`
    now blocks the deny-removal step outright and is left on disk, never deleted, so the evidence of what
    still needs removing survives for a retry.

11. **Installer activation gating: never activate a layer whose required artifacts didn't fully install
    (PR #10 review).** Decision #10 above closed the settings.json/ownership-record gap but
    explicitly left the `mkdir`/`install`/`ln`/`rm`/`git config` calls that place the guard/helper
    *scripts* and set `core.hooksPath` unchecked — a failed `mkdir -p` there could be followed by a
    doomed `install`/`ln` that still printed `did "installed ..."`, and nothing stopped `core.hooksPath`
    from being pointed at a directory whose dispatcher or symlinks never actually landed. Fixed by
    gating each layer's activation on its own prerequisite artifacts, checking every mutating call
    (`git_layer_ready` gates whether `core.hooksPath` is ever touched — checked via a `git config --get`
    readback, not just the setter's own exit code; `claude_files_ready` gates whether the PreToolUse
    entry is registered, but deliberately does NOT gate the independent `permissions.deny` hardening,
    which needs neither script file to exist). No `set -e`: every command is checked explicitly, keeping
    the installer's existing controlled `did`/`problem` reporting model rather than converting the whole
    script to fail-fast. 10 new regression checks, including two isolated failure simulations (a plain
    file occupying the exact path a directory needs to go, so only that one layer's install fails without
    cascading into the other) proving `--apply` exits nonzero, `core.hooksPath` is never activated on a
    broken Git layer, and the PreToolUse entry is never registered on a broken Claude layer — plus that
    each failure stays isolated to its own layer. Fixing the tests surfaced a real test-isolation bug
    (unrelated to the installer itself): `core.hooksPath` is real global git config shared across every
    scenario within one test-file run, so an earlier scenario's successful `--apply` left it pointing at
    that scenario's own sandbox; fixed by resetting it explicitly around the new tests that check its
    value.

12. **Claude-layer uninstall detaches config before removing the files it references (PR #10
    review).** `--uninstall` previously removed `bindle-protected-main-guard` and
    `allow-main-write.sh` *before* attempting to remove the `settings.json` `PreToolUse` entry naming
    them — if that removal then failed, or `settings.json` turned out to be malformed (refused outright
    per Decision #10), the registration stayed active while the files it pointed at were already gone.
    Reordered: the `PreToolUse` entry is removed first, and the guard/helper files are only removed once
    that's confirmed successful (`pretooluse_detached`); a missing `settings.json` (nothing to detach)
    still allows normal removal. `permissions.deny`/ownership cleanup remains independently handled,
    unaffected by this reordering — a different config surface entirely. One test's assertion inverted
    to match (uninstall against malformed settings.json now proves the files are *preserved*, not
    removed), plus a new check that the helper script is preserved too.

13. **Git-layer first install stages off to the side before going live; re-apply mutates only the
    dispatcher FILE, never the directory (PR #10 review, revised in a later pass of the same
    review).** `--apply` used to
    run `mkdir -p`/`install`/`ln` straight into `$HOOKS_DIR` for both first install and re-apply. For a
    first install this is safe (`core.hooksPath` isn't set until afterward, so nothing is watching the
    path yet); for a re-apply, Git reads `core.hooksPath`'s target live for the entire duration, so a
    failure partway through could leave it observing a half-updated dispatcher/symlink set.
    **First install:** the complete dispatcher + full symlink set is built in a sibling `mktemp -d`
    staging directory under `$GUARD_HOME`, verified (dispatcher executable, every symlink present), and
    only then moved into place with a single atomic `mv` — `core.hooksPath` is set only after that
    succeeds.
    **Re-apply (revised):** the first version of this fix swapped the ENTIRE `$HOOKS_DIR` directory via
    two same-filesystem renames (move the live one aside, move a full replacement into its place). That
    pair is not atomic *as a pair* — between the two renames, `core.hooksPath` names a path that
    genuinely does not exist, so a concurrent Git operation in that window would silently find no hooks
    at all and skip Bindle's guardrail layer entirely. Corrected to never replace the directory on
    re-apply: verify the existing installation is exactly what Bindle would have installed (dispatcher
    present and executable, every one of the 19 symlinks present and pointing at the literal filename
    `.bindle-git-hook-dispatch`), then replace ONLY that one file — staged as a same-directory temp file,
    verified, and swapped in with a single atomic rename over the original name. Every symlink already
    points at that literal filename and is never touched, so Git always resolves either the complete old
    dispatcher or the complete new one; the directory itself keeps the same inode the entire time (proved
    directly in the regression, not just inferred). If the existing installation is anything other than
    exactly correct (a missing symlink, a symlink pointing somewhere else, a missing/non-executable
    dispatcher), `--apply` fails safely and reports the problem rather than attempting a live repair —
    the different corruption shapes don't share one equally-atomic repair primitive, and building logic
    to reason about which ones do would itself be the kind of generalized mechanism this fix is
    explicitly not.
    Found and fixed a real regression along the way: `mktemp -d`, unlike the `mkdir -p` it replaced, does
    not create missing parent directories — a genuinely fresh install (`$GUARD_HOME` not yet existing at
    all, the actual first-ever-run case) started failing until an explicit `mkdir -p "$GUARD_HOME"` was
    added before staging.
    Checked the analogous Claude-layer file (`--apply` overwriting `bindle-protected-main-guard`/
    `allow-main-write.sh` directly) for the same class of problem: only the guard script needed staged
    treatment (a same-directory temp file + atomic rename), since it's the exact path an
    already-registered `PreToolUse` entry's `command` names. The helper script does not — the guard only
    ever references its path as a *string* in a deny message (verified by reading
    `bin/claude-protected-main-guard.sh`; it never executes it), so a corrupted helper only breaks a
    later, separate, explicitly-invoked command, never the hook's own resolution. Note: this Claude-layer
    reasoning is unaffected by the git-layer's directory-vs-file correction above, since it was already a
    single-file swap, never a directory swap.
    9 regression checks for the re-apply path (up from the original 6, after the mechanism correction):
    a successful re-apply proves the directory's inode is unchanged while the dispatcher's inode does
    change (atomic replacement, not in-place edit) and all 19 symlinks remain valid; a staging failure
    proves the directory inode, dispatcher content, and every symlink are all untouched; a corrupted
    existing installation (one symlink deleted) proves `--apply` fails safely and does not silently
    recreate the missing symlink.

14. **`bin/test-install-guardrails.sh` used `stat -f %i` (BSD/macOS-only) to prove inode identity for
    the Decision #13 regressions — first CI failure on GitHub Actions' `ubuntu-24.04` runner (PR #10
    review).** A test-only portability bug, not an installer defect: GNU `stat` (Linux) uses `-c`,
    not `-f`, and the failure mode was silent rather than loud — both the "before" and "after" `stat`
    calls failed identically, so equality checks comparing two empty strings passed by accident, and only
    the one inequality check ("the dispatcher's inode DID change") caught it. Fixed with a small
    `inode_of()` helper (tries GNU syntax, falls back to BSD) instead of inline `stat -f`. Reproduced
    locally without needing CI: aliased Homebrew's `gstat` (GNU coreutils) as `stat` on `$PATH` and
    re-ran the suite under genuine GNU semantics, not just inferred portability. No change to
    `bin/install-guardrails.sh` — the actual atomic-swap mechanism was correct; only the test's
    verification method wasn't portable.
## Work

- [x] `bin/git-hook-dispatch.sh` — the single shared implementation: resolves current branch (or
      rebased-branch arg for `pre-rebase`), checks against the hardcoded `main` literal and
      `ALLOW_MAIN_WRITE`, blocks with an actionable message on violation, otherwise delegates to the
      repo-local hook of the same name if present. Also exempts an unborn branch (no commit yet) —
      found empirically: a brand-new repository's first commit was being blocked, which is not the
      intended invariant.
- [x] `bin/install-guardrails.sh` — preview-by-default installer/uninstaller for both the git layer
      (global `core.hooksPath` + symlink farm under `~/.local/share/bindle/git-hooks/`) and the Claude
      layer (structural `jq` merge into `~/.claude/settings.json`'s `hooks.PreToolUse` and
      `permissions.deny`). `--apply` writes; `--uninstall` removes only the `permissions.deny` entries
      recorded as genuinely Bindle-added in `OWNED_DENY_FILE` (an ownership delta, not the full
      generated manifest — see Decision #7), so a pre-existing user rule that happens to be
      byte-identical to one of Bindle's own survives. Idempotent either direction. Refuses to overwrite
      a pre-existing, different global `core.hooksPath`.
- [x] `bin/claude-protected-main-guard.sh` template (checked in, copied not symlinked at install time)
      — `PreToolUse` handler for `Edit|Write|MultiEdit|NotebookEdit`, mirroring
      `subagent-limit-guard`'s stdin-JSON / structured-decision shape.
- [x] `bin/allow-main-write.sh` — one-shot token minting helper (repo/worktree/TTL-bound).
- [x] `permissions.deny` rule set for the secret-file/env policy, plus `Bash` deny entries for literal
      `env`, `printenv`, and macOS `security find-*-password`/`dump-keychain` invocations.
- [x] `bin/test-git-hook-dispatch.sh`, `bin/test-claude-protected-main-guard.sh`, and
      `bin/test-install-guardrails.sh` (synthetic stdin JSON, no live Claude session needed) — see
      Verification.
- [x] Wired all three new test scripts into `scripts/check.sh`.
- [x] `docs/DECISIONS.md` D031 — architecture-level record only (composition model, why Claude needs a
      distinct one-shot mechanism, why doctor.sh is untouched), not implementation trivia.

## Verification

Boundary list (from the user's requirements plus the composition/mutation-path corrections):

Git layer: commit on `main` blocked; commit on a feature branch allowed; `ALLOW_MAIN_WRITE=1` permits
the git operation; the override does not persist to a subsequent command; branch creation from `main`
allowed; fetch/read operations allowed; fast-forward sync allowed; a fixture repo's own `commit-msg`,
`post-commit`/`post-merge`, and `pre-commit` hooks still fire through Bindle's global layer with
original args/exit-code behavior preserved (proves non-naive composition, not just the original three
hooks).

Claude layer: edit on `main` blocked; edit after branching allowed; one-shot capability works exactly
once; second use fails; expired capability fails; a capability minted in one worktree cannot authorize
another. No session-binding claim or test — deliberately removed, see Decisions #2.

Secrets: synthetic secret-bearing fixture denied; `.env.example`/`.env.template` allowed; normal
unrelated Claude/shell behavior unaffected. Synthetic fixtures only, never real secrets.

Full local gate before calling this done:
```
bash scripts/check.sh
git diff --check
cog check
```
Plus install/uninstall round-trip tests proving neither operation damages pre-existing hook
configuration or unrelated `~/.claude/settings.json` content.

## Open questions

None. The one live ambiguity (Claude-layer override mechanism) was resolved by the user during design.
A second ambiguity — whether `CLAUDE_CODE_SESSION_ID` is the same identifier as `PreToolUse`'s
`session_id` — was checked against official documentation on release review (2026-08-23) and found
undocumented either way; rather than leave it open, the capability was simplified to drop session
binding entirely, so the supported invariant (repo + worktree + TTL + single-use) does not depend on
the answer.

## Showcase evidence

Merged via PR #10, `feat(guardrails): local protected-main + secrets enforcement`, merge commit
`d6b8adf9af46ad7c44486a529785e31f89f708f3` (2026-08-24). Files added/changed:

- `bin/git-hook-dispatch.sh` (new)
- `bin/install-guardrails.sh` (new)
- `bin/claude-protected-main-guard.sh` (new)
- `bin/allow-main-write.sh` (new)
- `bin/test-git-hook-dispatch.sh`, `bin/test-claude-protected-main-guard.sh`,
  `bin/test-install-guardrails.sh` (new)
- `scripts/check.sh` (modified — wires the three new test suites in)
- `docs/DECISIONS.md` (modified — adds D031)

Full local gate, re-run on `main` at `d6b8adf` as part of this housekeeping pass:

```
bash scripts/check.sh   → all checks passed, including:
  git-hook-dispatch:            22/22 checks passed
  claude-protected-main-guard:  26/26 checks passed
  install-guardrails:           67/67 checks passed
  decision-reference consistency: all D-number citations resolve
  python3 -m unittest (bindle CLI): 9 passed
git diff --check        → clean (exit 0)
cog check                → No errored commits (exit 0)
```

User-level installation targets (per the design, not exercised live against this machine's real
`~/.claude/settings.json` or global `core.hooksPath` — verified only against isolated sandboxes in the
test suites above): a global Git hook dispatcher symlinked under every standard client-side hook name
via `core.hooksPath`, plus a `PreToolUse` guard and `permissions.deny` hardening merged into
`~/.claude/settings.json`, both installed only through `bin/install-guardrails.sh --apply` on explicit
user action.
