# Repo-local guardrail Git hook layer

Date: 2026-08-24. Status: **implemented (including the follow-up round below) — `scripts/check.sh` passes; ready for review before merge.**

## Outcome

Move Bindle's Git-layer guardrail (protected-`main` + hook composition) from
machine-global `core.hooksPath` to repo-local, opt-in `core.hooksPath`,
installed by a reworked `bin/install-guardrails.sh` and wired into
`bindle init` / `bindle remove` as the first real lifecycle behavior. A
repository that has not run `bindle init` (or the installer directly) is
unaffected by Bindle's Git hooks. A repository that has opted in keeps the
exact protections it has today, including in linked worktrees.

The Claude Code PreToolUse layer (`bin/claude-protected-main-guard.sh`,
`bin/allow-main-write.sh`, `permissions.deny` hardening) is **out of scope**
and stays exactly as D031 left it: global, user-level, unaffected by which
repository opted in. This slice reworks the Git hook layer only.

## Why now

D031 deliberately chose a machine-global `core.hooksPath` so every
repository on the machine was protected uniformly, before Bindle had any
concept of per-repository opt-in. PR #13 (`origin/main`) has since
established `bindle init` as that opt-in boundary's command surface — but
as an interface-only stub with zero behavior. A machine-global Git hook
install contradicts the opt-in model PR #13 introduced: a repository that
never ran `bindle init` would still be silently affected. This is the first
slice to give `bindle init` real behavior, and the smallest correct one:
the Git layer is already a single, well-tested, portable installer: only
its *scope* needs to change, not its composition/override/dispatch design.

## Scope

**In scope:**
- `bin/install-guardrails.sh`'s Git-layer half: install repo-locally
  (`git config --local core.hooksPath`, hooks staged under the target
  repo's own Git common directory), not globally.
- A `--repo PATH` target flag and a `--git-only` flag (skip the Claude
  layer) on the installer, so `bindle init`/`bindle remove` can drive just
  the Git layer for the current repository.
- A `--remove-legacy-global` migration mode: proof-based removal of a
  pre-existing Bindle-owned *global* `core.hooksPath` from the old
  implementation, refusing anything it cannot positively identify as its
  own.
- Wiring `bin/install-guardrails.sh --apply --git-only --repo <worktree>`
  into `bindle init`, and `--uninstall --git-only --repo <worktree>` into
  `bindle remove` (`src/bindle/cli.py`).
- Updating `bin/test-git-hook-dispatch.sh` and `bin/test-install-guardrails.sh`
  for repo-scoped fixtures, plus `tests/test_cli.py` for the new init/remove
  behavior.
- Amending `docs/DECISIONS.md` (D031) with a new decision recording the
  scope change, and updating `PLAN.md`.

**Out of scope:**
- The Claude Code PreToolUse layer's design or scope (stays global, D031
  unchanged for that half).
- `bindle init`'s eventual full behavior (Projectmem, Symphony, skill
  packs, catalog/install-state tracking) — `init`/`remove` gain exactly one
  real behavior (the Git guardrail layer) and remain otherwise stubbed.
- Packaging `bin/*.sh` into an installable wheel for the "stable installed
  release." `bindle init`/`remove` locate the installer relative to their
  own source file, which only resolves when running from a Bindle source
  checkout (`uv run bindle`, per AGENTS.md's "CLI invocation"). Running the
  installed release's `bindle init` outside a checkout reports a clear
  error rather than silently doing nothing; solving that packaging gap is
  a separate concern.
- Any change to `bin/git-hook-dispatch.sh`'s policy logic (protected-branch
  check, override, composition-by-delegation) — it already resolves the
  delegation target via `--git-common-dir`, which is correct unchanged for
  repo-local scope.

## Evidence (current implementation, verified this session)

- `bin/install-guardrails.sh:246,394,256` — the only places that read,
  set, or unset `core.hooksPath`, always `--global`. Refuses to replace a
  pre-existing, *different* global value (`:248-251`) rather than
  composing with an unknown hook manager.
- `bin/git-hook-dispatch.sh:112` — `git rev-parse --path-format=absolute
  --git-common-dir` resolves the delegation target
  (`<common-dir>/hooks/<name>`) already correctly for linked worktrees;
  this is the existing coexistence mechanism (tested at
  `bin/test-git-hook-dispatch.sh:178-221`) and needs no change.
- `bin/git-hook-dispatch.sh:36-98` — `PROTECTED_BRANCH="main"`,
  `check_protected_branch()`, the `ALLOW_MAIN_WRITE=1` override, and the
  unborn-branch exemption are the entire policy surface. Scope-independent
  of where `core.hooksPath` points; no change needed.
- `docs/WORKTREES.md:33` — the sharing table already documents "hooks
  unless `core.hooksPath` overrides them" as shared-through-the-common-dir
  state. A `--local` `core.hooksPath` lives in `<common-dir>/config`,
  which *is* that shared file — so a repo-local install is already
  worktree-correct by construction, provided the configured path is
  absolute (a relative `core.hooksPath` resolves per Git's own hook-running
  directory, which differs per linked worktree's private git-dir; an
  absolute path removes that ambiguity).
- `src/bindle/repo.py:48-78` (`get_repo_info`) — already resolves
  `worktree_root` via `git rev-parse --show-toplevel`; the natural argument
  to hand the installer's `--repo` flag (git itself then resolves that
  worktree's common dir).
- `docs/DECISIONS.md:355-368` (D031) — the decision that commits to global
  scope for both layers; the bullet "Guardrails install into user-owned
  global configuration ... not into every repository" needs amending for
  the Git half.
- No existing repo-local Bindle state directory convention exists
  (`docs/SCOPE.md`: "State under BINDLE_HOME is limited to configuration,
  disposable cache... explicit exports" — machine-scoped only). Nothing
  under the working tree is appropriate for untracked, disposable,
  regenerable hook state — `<git-common-dir>/bindle-hooks` (inside `.git`,
  never tracked, already the repository's own Git-owned directory) is the
  cleanest fit, named to avoid colliding with Git's own `.git/hooks`.
- `bin/test-check-private-info.sh:98-110`'s `scope_repo()` already pins
  each fixture's own **local** `core.hooksPath` to an empty directory, to
  isolate fixtures from a developer's real global Git hook configuration
  (any tool's, not just Bindle's). This stays unchanged — it remains a
  good isolation property independent of this rework (per direct
  instruction: do not delete it).
- `src/bindle/cli.py` (origin/main, PR #13) — `_LIFECYCLE_COMMANDS`,
  `_cmd_not_implemented`, and `main()`'s dispatch are the entire surface;
  `init`/`remove` currently both route to `_cmd_not_implemented`.

## Decisions

1. **Repo-local hook storage lives at `<git-common-dir>/bindle-hooks`,
   not a tracked directory.** It is Git-owned, untracked, disposable, and
   shared correctly across linked worktrees for free (D018's identity
   model), with no new tracked state and no collision with `.git/hooks`.
2. **`core.hooksPath` is always written as an absolute path.** A relative
   value's resolution base differs across linked worktrees (each has its
   own private git-dir); the repository identity that matters
   (`--git-common-dir`) is already resolved absolute everywhere else in
   this codebase.
3. **The installer keeps doing both layers by default (`--apply`/
   `--uninstall` with no `--git-only`), preserving today's single-command
   developer workflow for whoever runs it directly** — only the Git
   layer's *scope* changes (global → repo-local). `--git-only` is added
   so `bindle init`/`remove` can drive the Git layer alone, without
   silently also toggling the separately-scoped, still-global Claude
   layer on/off as a side effect of running `bindle init` in one
   repository.
4. **Legacy global migration is a separate, explicit, standalone mode
   (`--remove-legacy-global`)**, not folded into `--apply`/`--uninstall`,
   and it removes a global value only when the directory it points at
   positively matches what Bindle's installer would have produced
   (dispatcher present + every standard hook name symlinked to it) — the
   same predicate already used to refuse live-repairing a corrupted
   install, factored into one shared helper.
5. **`bindle init`/`remove` resolve the installer script relative to their
   own source file** (`Path(__file__).resolve().parents[2] / "bin" /
   "install-guardrails.sh"`), which only exists inside a Bindle source
   checkout. Running the not-yet-packaged installed release reports a
   clear "not found" error rather than crashing or silently no-op'ing.

## Work

### 1. `bin/install-guardrails.sh` — repo-local Git layer

- Add `hooks_dir_is_intact(dir)`: true iff `dir/.bindle-git-hook-dispatch`
  is executable and every `HOOK_NAMES` entry under `dir` is a symlink to
  it. Used by both the re-apply corruption check and legacy-removal proof.
- Replace single-arg mode parsing with a flag loop: `--apply`,
  `--uninstall`, `--remove-legacy-global`, `--git-only`, `--repo PATH`
  (default `$PWD`). Reject invalid combinations (`--remove-legacy-global`
  with any of the others) with a usage error.
- `--remove-legacy-global` runs before the `jq` presence check (it never
  touches Claude-layer config) and exits immediately after: reads global
  `core.hooksPath`; no-ops cleanly if unset; if `hooks_dir_is_intact`,
  unsets the global config and removes the directory; otherwise reports
  the mismatch via `problem()` (nonzero exit) and leaves it untouched.
- Git layer: resolve `git -C "$REPO_TARGET" rev-parse --is-inside-work-tree`;
  if not inside a work tree, skip with a clear message (or fail if
  `--git-only`). Otherwise resolve `repo_common_dir` via `--git-common-dir
  --path-format=absolute` and set `HOOKS_DIR="$repo_common_dir/bindle-hooks"`.
  Read/write/unset `core.hooksPath` with `--local` (not `--global`)
  against `$REPO_TARGET`. Keep the staged-then-atomic-rename install path,
  the atomic single-file dispatcher swap on re-apply, and the
  refuse-to-live-repair-corruption behavior, unchanged apart from the path
  source and using the new shared helper.
- Wrap the existing Claude-layer section (byte-identical logic) in
  `if [ "$GIT_ONLY" -eq 0 ]; then ... fi`.
- Update the file's header comment for the new scope/flags.

### 2. `bin/test-git-hook-dispatch.sh` — repo-scoped fixtures

- `new_fixture()` now also runs `"$INSTALLER" --apply --repo "$FIX"` after
  creating the fixture, instead of relying on a single global install at
  the top of the file.
- Add: a second fixture repo that never runs the installer (`Repo B`),
  asserting a commit directly on its `main` succeeds (not blocked).
- Add: a linked-worktree scenario — `git worktree add` a second worktree
  off the installed `$FIX`, and prove `main`-protection fires there too
  without a separate install.
- Retarget the "installer refuses to replace a pre-existing, different
  `core.hooksPath`" scenario to `--local` config on a fixture repo instead
  of global config.
- Update the final uninstall scenario to operate `--repo`-scoped and
  assert the repo-local config/directory are gone, without touching global
  config at all (drop the global-config assertions this test no longer
  exercises).

### 3. `bin/test-install-guardrails.sh` — split Git-layer scope

- Claude-layer scenarios (structural merge, deny-manifest content,
  idempotency, uninstall preservation, malformed-settings/-owned-file
  safety, write-failure reporting) are unaffected in substance; they
  already never depended on a real repository. Leave them as-is.
- The Git-layer scenarios currently at lines 279-416 (incomplete install
  never activates, re-apply preserves the same directory, re-apply detects
  corruption) move to real fixture repos (`git init`) and assert
  `--local` config / `<common-dir>/bindle-hooks`, using `--repo` and
  `--git-only` so they don't also churn the Claude layer.
- Add: `--remove-legacy-global` scenarios — no-op when unset, positive
  removal when the global value matches a genuine prior install, and
  refusal (untouched, nonzero exit) when it points at something else
  (e.g. `/some/other/hook/manager`).
- Add: a plain `--apply` (no `--repo`, no `--git-only`) scenario proving
  it still does both layers against `$PWD`, for the direct-invocation
  workflow.

### 4. `src/bindle/cli.py` — wire `init`/`remove`

- Add `_installer_path()` and a small `_run_guardrail_installer(mode)`
  helper: resolves `get_repo_info()` (reusing the existing
  `NotAGitRepositoryError` handling), resolves the installer path relative
  to `__file__`, reports a clear error if either fails, otherwise runs
  `subprocess.run(["bash", str(installer), mode, "--git-only", "--repo",
  info.worktree_root])` and returns its exit code.
- `_cmd_init`/`_cmd_remove` call it with `"--apply"` / `"--uninstall"`.
- Route `init`/`remove` to these in `main()` instead of
  `_cmd_not_implemented`.

### 5. `tests/test_cli.py` — cover the new behavior, fix the stub tests

- `TestUnimplementedLifecycleCommands` must exclude `init`/`remove`
  (they're implemented now) — iterate over
  `[n for n in _LIFECYCLE_COMMANDS if n not in ("init", "remove")]`.
- Add a test class covering: `init` inside a real fixture repo actually
  invokes the installer with the expected args (mock `subprocess.run`,
  assert the command list); `init`/`remove` outside a Git repository fail
  clearly without shelling out; the installer-not-found path (patch
  `_installer_path` to a nonexistent file) reports a clear error and
  returns 1.

### 6. Docs & decisions

- `docs/DECISIONS.md`: add a new decision amending D031's Git-layer
  bullet — record that the Git hook layer moved to repo-local, opt-in via
  `bindle init`, while the Claude Code PreToolUse layer remains global and
  unchanged, and why (opt-in model introduced by PR #13's lifecycle
  surface).
- `PLAN.md`: note `bindle init`/`remove` now have one real behavior (the
  Git guardrail layer).
- No `docs/WORKTREES.md` change needed — its sharing-table language
  already correctly describes a `core.hooksPath` override at the common
  directory; verify this holds during review rather than editing
  speculatively.

## Verification

- `bash scripts/check.sh` (full gate).
- `bash bin/test-install-guardrails.sh`, `bash bin/test-git-hook-dispatch.sh`,
  `bash bin/test-check-private-info.sh` individually.
- `python3 -m unittest discover -s tests -t .`
- `git diff --check`.
- Manual: three disposable repos — Repo A (`bindle init` via `uv run
  bindle`, confirm protected + worktree-correct), Repo B (untouched,
  confirm unaffected), and confirm global `core.hooksPath` is never set by
  any of this.

## Open questions

- None blocking; the packaging gap for the installed (non-checkout)
  release is named explicitly above as deliberately out of scope.

## Showcase evidence

- Before/after: global vs. repo-local `git config --get core.hooksPath`
  in two disposable repos.
- Final `scripts/check.sh` output.

---

## Follow-up: closing three ownership gaps

The first round above left three real ownership gaps in the "repository is
the unit of management" model: a recognized legacy global Git install could
still defeat `bindle remove`; the Claude Code PreToolUse layer stayed
global regardless of opt-in; and `bindle init`/`remove` only worked from a
Bindle source checkout. This round closes all three.

### Outcome

- **Legacy fallback closed**: every `--apply`/`--uninstall` now
  opportunistically migrates away a *recognized* pre-rework global
  install (Git `core.hooksPath` and/or the Claude PreToolUse entry),
  proof-gated the same way `--remove-legacy-global` always was; an
  unrelated global value is never touched and never even reported during
  a normal repo-scoped run.
- **Claude layer reconciled**: the PreToolUse guard and permissions.deny
  hardening are now repo-local too, installed into the target
  repository's own `.claude/settings.local.json` (a real, documented,
  gitignored-by-convention Claude Code mechanism — confirmed against
  current docs, not assumed) instead of `~/.claude/settings.json`. There
  is no remaining Bindle-owned global guardrail configuration of any
  kind.
- **Packaging resolved**: `git-hook-dispatch.sh`, `claude-protected-main-guard.sh`,
  `allow-main-write.sh`, and `install-guardrails.sh` moved from `bin/` to
  `src/bindle/_bin/` (package-owned, single source of truth) and are
  resolved at runtime via `importlib.resources.files("bindle")`. Verified
  by building the wheel through `uv build` and installing it into an
  isolated venv outside this checkout (`bin/test-packaged-install.sh`).

### Amendment 1 (merge-readiness review, pre-merge)

A merge-readiness review of PR #14 found the "legacy fallback closed"
bullet above was still wrong in one respect: "opportunistically migrates"
meant a repo-scoped `bindle init`/`bindle remove` in one repository could
silently mutate machine-global state with consequences for every other
repository on the machine — itself a violation of the opt-in model this
plan otherwise establishes. Fixed before merge, current behavior (see
`docs/DECISIONS.md` D032, updated in the same commit):

- A normal `--apply`/`--uninstall` only *detects* recognized legacy global
  state and, on a match, refuses to run at all with an actionable error —
  it never migrates or removes anything global as a side effect. Only
  `install-guardrails.sh --remove-legacy-global` (now also exposed as
  `bindle migrate-legacy-global`) performs that migration, and only when
  invoked directly.
- `bindle init`/`bindle remove` requesting both layers is now all-or-
  nothing per invocation: a preflight pass validates both layers before
  either mutates, and a mutation-time-only Claude-layer failure after the
  Git layer already succeeded rolls the Git layer back to its
  pre-invocation state, rather than leaving it newly adopted/removed
  without the other.

### Scope

**In scope:** all three gaps above, `docs/DECISIONS.md` D032 rewritten to
describe the actual final boundary, new automated coverage for the
cross-layer opt-in/opt-out contract and the packaged-install path.

**Out of scope (unchanged):** Projectmem, Symphony, skill packs,
telemetry, general component/catalog management, `bindle status` (still a
stub), fleet-wide upgrade behavior.

### Key design decisions

1. **Both layers are now repo-scoped by the same `repo_common_dir`
   resolution**, computed once and shared, rather than each layer
   independently deciding whether it applies. `bindle init`/`remove` drop
   `--git-only` from their own CLI wiring entirely (`install-guardrails.sh
   --apply|--uninstall --repo <worktree>`, both layers) — that flag only
   existed to avoid toggling a *separately-scoped global* Claude layer,
   which no longer exists.
2. **The Claude guard/helper scripts live at `<git-common-dir>/bindle-claude`,
   a directory kept separate from the Git layer's `bindle-hooks`**, so the
   two layers' installers stay fully independent under `--git-only`/
   `--claude-only` — verified by a real bug this design caught: an
   earlier draft nested the deny-ownership record inside that same
   directory, which broke the pre-existing "permissions.deny hardening is
   never gated on guard-file install success" guarantee. The record now
   lives as a sibling file, `<git-common-dir>/bindle-claude-deny-owned.json`.
3. **Claude settings resolve to the repository's main checkout, not
   necessarily `$REPO_TARGET`'s own worktree** — Claude Code's own
   documentation states project settings are "resolved through worktrees
   to the main checkout." `install-guardrails.sh` derives the same
   main-checkout path from `--git-common-dir` (reusing D018's identity
   model, mirroring `src/bindle/repo.py`'s `repo_root` logic) rather than
   writing into a linked worktree's own, never-consulted `.claude/`.
4. **Legacy migration is proof-gated identically in both the automatic and
   standalone paths, but differs in verbosity/failure behavior by
   design**: the automatic path (inside a normal `--apply`/`--uninstall`)
   is silent about an absent or unrelated global value — it's none of
   Bindle's business during an otherwise repo-scoped operation — while
   the standalone `--remove-legacy-global` command reports and fails on
   anything it can't positively migrate, since the user explicitly asked
   it to. A real bug surfaced while wiring this up: `--remove-legacy-global`
   is required (by its own usage validation) to leave `$MODE` at its
   `"preview"` default even though invoking it IS the action — an earlier
   draft read `$MODE` directly inside the shared migration functions,
   which meant the standalone command silently never mutated anything. A
   separate `dry_run` parameter, passed explicitly by each call site,
   fixed this without reintroducing the same confusion.
5. **The runtime assets move to `src/bindle/_bin/` (package-owned) rather
   than staying in `bin/` with a build-time copy** — one source of truth,
   automatically included in the wheel because hatchling already packages
   everything under `src/bindle/`, and resolvable identically in editable
   and installed modes via `importlib.resources`. `install-guardrails.sh`'s
   own sibling-script resolution simplified from a `bin/`-relative
   `REPO_ROOT` to a plain `SCRIPT_DIR` (`dirname "${BASH_SOURCE[0]}"`), so
   it no longer assumes anything about being inside a directory literally
   named `bin/`.

### Files changed (this round)

- `src/bindle/_bin/install-guardrails.sh` (moved from `bin/`, substantially
  reworked): shared repo-context resolution for both layers; repo-local
  Claude layer (`.claude/settings.local.json`, `bindle-claude` dir,
  sibling deny-ownership file); `migrate_legacy_global_git`/
  `migrate_legacy_global_claude` with `report_foreign`/`dry_run`
  parameters, called automatically from each layer and explicitly from
  `--remove-legacy-global`; `SCRIPT_DIR` sibling-path resolution.
- `src/bindle/_bin/git-hook-dispatch.sh`, `claude-protected-main-guard.sh`,
  `allow-main-write.sh` (moved from `bin/`, content unchanged).
- `src/bindle/cli.py`: `_installer_path()` now uses
  `importlib.resources`; `_run_guardrail_installer` drops `--git-only`.
- `bin/test-install-guardrails.sh`: every Claude-layer scenario retargeted
  to real fixture repos and `.claude/settings.local.json`; new legacy
  Claude-migration and combined-legacy scenarios.
- `bin/test-git-hook-dispatch.sh`, `bin/test-claude-protected-main-guard.sh`:
  installer/script paths updated for the `src/bindle/_bin/` move.
- `bin/test-guardrail-ownership.sh` (new): the cross-layer opt-in/opt-out
  contract end-to-end — uninitialized repo untouched, Repo A/Repo B
  isolation for both layers, remove genuinely unprotects, legacy
  Git+Claude migration survives a full init→remove cycle, linked-worktree
  Claude-settings resolution.
- `bin/test-packaged-install.sh` (new): `uv build` → isolated venv install
  → `bindle init`/`remove` from the installed artifact.
- `scripts/check.sh`: runs both new test files.
- `tests/test_cli.py`: updated expected installer invocation (no
  `--git-only`).
- `docs/DECISIONS.md`: D032 rewritten to describe the actual final
  boundary (both layers repo-local, package-owned assets); `PLAN.md`
  updated.

### Verification (this round)

- `bash scripts/check.sh` — all checks pass, including both new test
  files (`bin/test-guardrail-ownership.sh` 21/21,
  `bin/test-packaged-install.sh` 17/17) and the full existing suite
  (`bin/test-install-guardrails.sh` 85/85, `bin/test-git-hook-dispatch.sh`
  29/29, `bin/test-claude-protected-main-guard.sh` 26/26,
  `bin/test-check-private-info.sh` 57/57, Python unit tests 22/22).
- `python3 -m unittest discover -s tests -t .` — pass.
- `git diff --check` — clean.
- `uv build` — produces a wheel containing all four `_bin/*.sh` assets
  (verified by inspecting the archive, not assumed).
- Manual: installed the built wheel into an isolated venv (outside this
  checkout) and exercised `bindle init`/`bindle remove` against disposable
  repos from an arbitrary cwd — protection, isolation, genuine removal,
  and the outside-a-repo error path all verified directly.

### Open questions (as of the pre-merge amendment above)

- None blocking. Whether `bindle init` should also manage `.gitignore`
  for `.claude/settings.local.json` (Claude Code's own convention already
  gitignores entries it saves there) was considered and deliberately left
  alone — out of scope for this ownership-boundary fix. **Resolved in the
  merge-readiness amendment below**: left alone no longer holds once
  `bindle init` is the operation actually creating the file in an
  arbitrary target repository.

### Amendment 2 (merge-readiness review, pre-merge): jq elimination and settings.local.json Git hygiene

A second merge-readiness review of PR #14 found two remaining gaps before
merge, both fixed in this amendment (same commit):

- **`jq` was an undeclared onboarding dependency.** `bindle init` is now
  real, installed-package behavior, but the Claude-layer settings merge
  required an external `jq` executable with no declared prerequisite or
  tested failure path — a normal Bindle installation could succeed while
  its primary adoption command later failed for lack of a system utility
  nothing had asked the user to install. Fixed by replacing every jq
  invocation in `install-guardrails.sh` with calls to a new package-owned
  Python helper, `src/bindle/_bin/settings_json.py` (stdlib only, no
  dependency on the `bindle` package itself), run under `BINDLE_PYTHON` —
  the exact interpreter already running `bindle` (`sys.executable`, set by
  `cli.py`'s `_installer_env()`), falling back to `python3` on PATH for
  direct/test invocation of the installer. `bindle init`/`bindle remove`/
  `bindle migrate-legacy-global` now need nothing beyond git, bash, and
  the Python already required to run Bindle at all. Verified by building
  the wheel and exercising `bindle init`/`remove`/`migrate-legacy-global`
  from it with `jq` genuinely absent from `PATH` (a flattened,
  jq-excluded `PATH` shim; see `bin/test-packaged-install.sh`'s "no jq on
  PATH" section) and by a direct unit-test suite for every verb
  (`tests/test_settings_json.py`).
- **A target repository's own Git hygiene around
  `.claude/settings.local.json` was unhandled.** `bindle init` creates
  this file, but had no policy for a target repository that doesn't
  already ignore it (risking a new accidentally-committable untracked
  file) or — more seriously — already tracks it as shared, tracked
  configuration. Fixed: a tracked `.claude/settings.local.json` now blocks
  `bindle init`/`bindle remove` at preflight, before any mutation, with an
  actionable error; an untracked-and-unignored one gets a machine-local
  ignore rule recorded in the repository's own
  `<git-common-dir>/info/exclude` (shared across linked worktrees exactly
  like `core.hooksPath`, D018 — confirmed empirically, not assumed — and
  never touching the repository's own tracked `.gitignore`). An
  already-ignored repository (via its own `.gitignore` or a prior run) is
  left alone. Covered by three new scenarios in
  `bin/test-install-guardrails.sh` ("Git hygiene — not ignored yet /
  already ignored / already tracked").

Files touched by this amendment: `src/bindle/_bin/settings_json.py`
(new), `src/bindle/_bin/install-guardrails.sh` (jq calls replaced;
tracked-file preflight check; `ensure_repo_settings_ignored`),
`src/bindle/cli.py` (`_installer_env()` sets `BINDLE_PYTHON`),
`tests/test_settings_json.py` (new), `tests/test_cli.py` (BINDLE_PYTHON
propagation coverage), `bin/test-install-guardrails.sh` (Git hygiene
scenarios), `bin/test-packaged-install.sh` (no-jq scenario; wheel-asset
check includes `settings_json.py`), `docs/DECISIONS.md` (D032 amended:
the stale "packaging not addressed" paragraph — already contradicted by
the packaged-assets bullet above it — replaced with these two bullets),
`README.md` (CLI section brought current), and this plan.

Verification: `bash scripts/check.sh` (all suites pass, including the new
scenarios above), `python3 -m unittest discover -s tests -t .`,
`git diff --check`, `uv build`.

### Amendment 3 (merge-readiness review, pre-merge): info/exclude ownership and removal

A third merge-readiness review of PR #14 found the previous amendment's
`.claude/settings.local.json` Git-hygiene fix was still incomplete:
`ensure_repo_settings_ignored` could add a machine-local `info/exclude`
entry on `bindle init`, but `bindle remove` never cleaned it up — Bindle
had no way to distinguish an entry it added itself from one that predated
it (or came from `.gitignore`), so it could not safely remove anything.
Fixed in this amendment:

- **Ownership.** A tiny marker file, `<git-common-dir>/bindle-claude-exclude-owned`
  (the same sibling-file convention as the existing deny-ownership record),
  is written only on the genuine first-append path inside
  `ensure_repo_settings_ignored` — never when `check-ignore` already
  reports the path ignored via some other source. Its absence is
  permanent proof Bindle never claimed that entry.
- **Safety.** A new `settings_json.py` verb, `doc-is-empty`, recursively
  treats a document as empty iff it holds nothing but empty
  containers/`null` (any surviving list entry or scalar — including a
  falsy one — counts as real content). `bindle remove` only asks this
  question once both the PreToolUse entry and Bindle's own
  `permissions.deny` entries have been cleanly detached from
  `settings.local.json`; a partially-detached file is never judged empty.
- **Cleanup.** `settings.local.json` is deleted only when it is
  effectively empty after detachment, and the Bindle-owned `info/exclude`
  line is removed only when both the marker proves ownership AND the
  settings file is now gone. Unrelated content surviving detachment keeps
  both the file and its ignore rule untouched — never made accidentally
  committable merely to achieve byte-for-byte cleanup. A pre-existing
  `info/exclude` entry, or one supplied via `.gitignore`, is never a
  candidate for removal in any case, since no marker was ever written for
  it.

Files touched: `src/bindle/_bin/settings_json.py` (`doc-is-empty` verb),
`src/bindle/_bin/install-guardrails.sh` (`CLAUDE_EXCLUDE_OWNED_FILE`
tracking in `ensure_repo_settings_ignored`; `remove_owned_exclude_entry`;
settings-file-emptiness check and cleanup wired into `--uninstall`),
`tests/test_settings_json.py` (`doc-is-empty` coverage),
`bin/test-install-guardrails.sh` (new scenarios: Bindle-owned entry
removed on remove, idempotent repeated init/remove, a pre-existing
info/exclude rule survives remove, `.gitignore`-provided ignore survives
remove, unrelated settings content keeps both the file and its ignore
rule in place), `docs/DECISIONS.md` (D032 amended), and this plan.

Verification: `bash scripts/check.sh`,
`python3 -m unittest discover -s tests -t .`, `git diff --check`,
`uv build`.
