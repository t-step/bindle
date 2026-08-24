#!/usr/bin/env bash
#
# install-guardrails.sh — preview-first installer for Bindle's guardrail
# layer. Both halves are repo-local and opt-in, scoped to one repository at
# a time (`--repo`, default: $PWD). A repository that never runs this
# (directly, or via `bindle init`) is unaffected by either half:
#
#   * Git layer: a hook-composition dispatcher (protects 'main', without
#     disabling the target repository's own hooks) installed via
#     `git config --local core.hooksPath`.
#   * Claude layer: a matching PreToolUse guard plus permissions.deny
#     hardening for AGENTS.md's secret-file policy (D012), installed into
#     the target repository's own `.claude/settings.local.json` (Claude
#     Code's native per-repository, gitignored-by-convention settings
#     file) — not into any global, user-level Claude configuration.
#
# See plans/archive/2026-08-23-local-guardrail-layer.md for the original
# (machine-global) design and plans/active/2026-08-24-repo-local-guardrails.md
# for the repo-local rework, including why both halves ended up repo-scoped.
#
# Usage:
#   install-guardrails.sh                      # preview both layers for $PWD
#   install-guardrails.sh --apply              # install both layers
#   install-guardrails.sh --uninstall          # remove both layers
#   install-guardrails.sh --apply --repo PATH  # target a specific repository
#   install-guardrails.sh --apply --git-only      # Git layer only
#   install-guardrails.sh --apply --claude-only   # Claude layer only
#   install-guardrails.sh --status             # read-only: report each
#                                               # layer's state (installed /
#                                               # not-installed / partial /
#                                               # conflict / invalid) for
#                                               # `bindle status` to parse.
#                                               # Never mutates, never
#                                               # gates/reports on legacy-
#                                               # global state.
#   install-guardrails.sh --remove-legacy-global
#                                               # remove a pre-rework GLOBAL
#                                               # Bindle install (Git and/or
#                                               # Claude), only for state
#                                               # this installer can
#                                               # positively prove is its own
#
# Idempotent in both directions. Refuses to replace a pre-existing,
# DIFFERENT repo-local core.hooksPath (another hook manager: pre-commit,
# husky, lefthook, ...) rather than attempting arbitrary composition with
# it. Never replaces an existing settings.local.json wholesale — merges
# into it structurally via settings_json.py (a package-owned Python
# helper, run under whichever interpreter is already running Bindle —
# see BINDLE_PYTHON below), touching only the specific array entries this
# installer owns. No external JSON tool (e.g. jq) is required.
#
# Never writes a target repository's own tracked .gitignore. If
# .claude/settings.local.json isn't already ignored there, the Claude
# layer instead adds a machine-local entry to the repository's own
# <git-common-dir>/info/exclude (shared across every linked worktree,
# like core.hooksPath — never committed, never visible to teammates). If
# the file is already tracked in Git, the Claude layer refuses to touch
# it at all, rather than silently rewriting team-shared configuration.
#
# That info/exclude entry is only ever removed by --uninstall when BOTH of
# these hold: (1) Bindle can positively prove it added the entry itself —
# an already-ignored repository (its own .gitignore, or a pre-existing
# info/exclude line) never has an entry added in the first place, so there
# is nothing for --uninstall to claim or remove there — and (2) removing it
# is actually safe, i.e. settings.local.json no longer holds anything once
# Bindle's own content is detached from it. A settings.local.json that
# still holds unrelated user content after --uninstall keeps both the file
# and its ignore rule untouched, rather than leaving it accidentally
# committable.
#
# Every --apply/--uninstall is repository-scoped only: it never mutates
# machine-global Bindle state as a side effect. If a RECOGNIZED pre-rework
# global Bindle install (Git core.hooksPath and/or Claude PreToolUse guard)
# is still present, --apply/--uninstall refuses to run at all — failing
# clearly and pointing at the explicit, repo-independent migration surface
# below (--remove-legacy-global) — rather than either silently migrating it
# (a machine-wide side effect from what looks like a repo-scoped command) or
# producing a repo-local result that would be misleading while stale global
# state might still apply elsewhere. An unrelated/foreign global value is
# never reported or touched by anything in this file.
#
# BINDLE_GUARD_HOME / BINDLE_CLAUDE_HOME below are used ONLY to locate a
# pre-rework global install for migration purposes — they no longer
# influence where anything NEW gets installed (that's always repo-local).
# Overridable for testing (never touch live locations from a dev/test run —
# AGENTS.md "Runtime isolation"):
#   BINDLE_GUARD_HOME     default: $HOME/.local/share/bindle
#   BINDLE_CLAUDE_HOME    default: $HOME/.claude
#   BINDLE_PYTHON         interpreter used for the Claude-layer JSON
#                         helper (settings_json.py). `bindle init`/`bindle
#                         remove`/`bindle migrate-legacy-global` set this
#                         to the exact interpreter already running
#                         Bindle. Direct/test invocation of this script
#                         falls back to `python3` on PATH.
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Standard client-side Git hooks (githooks(5)), excluding server/bare-repo-
# only hooks (pre-receive, update, proc-receive, post-receive, post-update)
# and Perforce-bridge hooks (p4-*), which don't apply to a developer's own
# checkout. Every name here gets a passthrough symlink regardless of whether
# Bindle has policy for it (git-hook-dispatch.sh decides that itself) — this
# is what keeps repository-owned hooks from being silently disabled.
HOOK_NAMES=(
  applypatch-msg pre-applypatch post-applypatch
  pre-commit pre-merge-commit prepare-commit-msg commit-msg post-commit
  pre-rebase post-checkout post-merge pre-push
  reference-transaction push-to-checkout pre-auto-gc post-rewrite
  sendemail-validate fsmonitor-watchman post-index-change
)

# --- canonical secret/credential policy (plan Decisions #5) -----------------
#
# This is the ONE place the policy is declared. Everything below this block
# is deterministic expansion into Claude's required per-tool permission-rule
# strings (test-install-guardrails.sh proves the expansion is exact) —
# adding a newly-recognized secret filename means adding one line to
# FILE_DENY_GLOBS, not four separate Read/Edit/Write/Grep rules.

# Precise private-key and env-file path shapes, not a blanket *.pem (PEM is
# also a public-certificate format) and not id_*.pub (the public half of an
# SSH keypair).
FILE_DENY_GLOBS=(
  ".env" ".env.local" ".env.*.local"
  "id_rsa" "id_ed25519" "id_ecdsa" "id_dsa"
  "*.pfx" "*.p12"
  "privkey.pem" "*-key.pem" "*_key.pem"
  "secrets/**"
)

# Every tool that must deny each pattern in FILE_DENY_GLOBS identically.
# Grep is included because AGENTS.md's policy covers "search," but a
# directory-wide Grep that merely CONTAINS one of these paths as a subpath
# is a documented, un-closed gap (Claude's permission globs are
# path-anchored, not content-scoped).
FILE_DENY_TOOLS=(Read Edit Write Grep)

# Bash commands that dump the whole environment — denied both bare (no
# arguments) and with any argument list, since the two are distinct
# invocation shapes under Claude's Bash rule syntax.
ENV_DUMP_COMMANDS=(env printenv)

# Exact files whose contents must not be read directly via a shell `cat`.
CAT_DENY_FILES=(".env" ".env.local")

# macOS Keychain credential-dump commands — these always take arguments, so
# only the wildcard form is needed.
KEYCHAIN_DUMP_COMMANDS=(
  "security find-generic-password"
  "security find-internet-password"
  "security dump-keychain"
)

PRETOOLUSE_MATCHER="Edit|Write|MultiEdit|NotebookEdit"

MODE="preview"
GIT_ONLY=0
CLAUDE_ONLY=0
LEGACY_REMOVE=0
REPO_TARGET="$PWD"

usage() {
  echo "usage: $0 [--apply|--uninstall|--status] [--git-only|--claude-only] [--repo PATH]" >&2
  echo "       $0 --remove-legacy-global" >&2
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
  --apply) MODE="apply" ;;
  --uninstall) MODE="uninstall" ;;
  --status) MODE="status" ;;
  --remove-legacy-global) LEGACY_REMOVE=1 ;;
  --git-only) GIT_ONLY=1 ;;
  --claude-only) CLAUDE_ONLY=1 ;;
  --repo)
    [ $# -ge 2 ] || usage
    REPO_TARGET="$2"
    shift
    ;;
  *) usage ;;
  esac
  shift
done

if [ "$GIT_ONLY" -eq 1 ] && [ "$CLAUDE_ONLY" -eq 1 ]; then
  usage
fi
if [ "$LEGACY_REMOVE" -eq 1 ] && { [ "$MODE" != "preview" ] || [ "$GIT_ONLY" -eq 1 ] || [ "$CLAUDE_ONLY" -eq 1 ]; }; then
  usage
fi

fail=0
say() { printf '%s\n' "$1"; }
would() { printf '  [preview] %s\n' "$1"; }
did() { printf '  ✓ %s\n' "$1"; }
problem() {
  printf '  ✗ %s\n' "$1"
  fail=1
}

# hooks_dir_is_intact DIR — true iff DIR contains exactly the dispatcher
# plus a full, correctly-targeted set of HOOK_NAMES symlinks Bindle's own
# installer would have produced. Used both to refuse live-repairing a
# corrupted active install (never trust a partial match enough to patch it)
# and to positively prove a pre-existing global core.hooksPath is actually
# Bindle's own before removing it.
hooks_dir_is_intact() {
  local dir="$1"
  [ -x "$dir/.bindle-git-hook-dispatch" ] || return 1
  local name
  for name in "${HOOK_NAMES[@]}"; do
    [ -L "$dir/$name" ] || return 1
    [ "$(readlink "$dir/$name")" = ".bindle-git-hook-dispatch" ] || return 1
  done
  return 0
}

# json_op VERB ARGS... — runs settings_json.py (this directory's
# package-owned, jq-free JSON helper) under $BINDLE_PY. Every mutating
# verb it exposes writes atomically (temp file in the destination's own
# directory, then an atomic rename) and, on ANY failure, leaves the
# destination completely untouched, cleans up its temp file, and returns
# nonzero with nothing printed — the same contract the old jq-based
# jq_atomic_write helper had.
json_op() {
  "$BINDLE_PY" "$SCRIPT_DIR/settings_json.py" "$@"
}

# read_owned_json FILE — echoes the persisted "deny entries Bindle actually
# added" set for FILE and returns 0. An ABSENT file is a normal, expected
# state (nothing tracked yet) and echoes "[]". A PRESENT-but-broken file
# (unreadable, or not a JSON array) returns nonzero and echoes nothing —
# callers must treat that as a hard stop, never silently substitute "[]",
# since doing so both under-tracks ownership and would let the caller go on
# to delete the only evidence of what should have been removed.
read_owned_json() {
  local file="$1"
  json_op read-array "$file"
}

# pretooluse_entry_present SETTINGS_FILE COMMAND — true iff SETTINGS_FILE
# has a PreToolUse entry for PRETOOLUSE_MATCHER whose command is COMMAND.
pretooluse_entry_present() {
  local settings="$1" cmd="$2"
  json_op pretooluse-present "$settings" "$PRETOOLUSE_MATCHER" "$cmd"
}

if ! command -v git >/dev/null 2>&1; then
  problem "git not found on PATH"
  exit 1
fi

# BINDLE_PY is required whenever the Claude layer might run: the
# repo-local Claude logic below, AND legacy-Claude migration/detection
# (which --git-only never reaches, but --remove-legacy-global and a normal
# --apply/--uninstall's legacy-gating check always do). `bindle init`/
# `bindle remove`/`bindle migrate-legacy-global` always set BINDLE_PYTHON
# to the interpreter already running Bindle, so this can only fail for a
# direct/test invocation of this script without python3 on PATH.
BINDLE_PY="${BINDLE_PYTHON:-python3}"
PY_NEEDED=1
if [ "$GIT_ONLY" -eq 1 ]; then
  PY_NEEDED=0
fi
if [ "$PY_NEEDED" -eq 1 ] && ! command -v "$BINDLE_PY" >/dev/null 2>&1; then
  problem "$BINDLE_PY not found on PATH — required for the Claude-layer settings merge (set BINDLE_PYTHON, or ensure python3 is on PATH)"
  if [ "$MODE" != "preview" ] || [ "$LEGACY_REMOVE" -eq 1 ]; then
    exit 1
  fi
fi

# --- legacy (pre-rework) global-install detection and migration -------------
#
# Before the repo-local rework, both layers installed into machine-global
# state: Git via global core.hooksPath, Claude via a PreToolUse entry in
# ~/.claude/settings.json. A repository that opts OUT under the new model
# must not silently fall back into either — but a normal, repository-scoped
# `bindle init`/`bindle remove` is also not the place to perform a
# machine-wide mutation with consequences for every other repository on the
# machine. The two concerns below are kept deliberately separate:
#
#   * legacy_global_*_recognized — READ-ONLY detection. Used to gate a
#     normal --apply/--uninstall (which must refuse to run, not silently
#     migrate or silently proceed) and for preview-mode advisories.
#   * migrate_legacy_global_* — the actual migration. Only ever invoked by
#     the explicit, repo-independent --remove-legacy-global command, where
#     invoking it in the first place makes the machine-wide side effect
#     intentional.
#
# Both only ever act on state they can positively prove is Bindle's own
# (see hooks_dir_is_intact / pretooluse_entry_present below) — an
# unrelated/foreign global value is never reported, gated on, or touched.

# legacy_global_git_recognized — true iff a global core.hooksPath is set and
# its contents are positively provable as Bindle's own pre-rework install.
# Read-only. On a true result, sets LEGACY_GIT_PATH.
legacy_global_git_recognized() {
  LEGACY_GIT_PATH="$(git config --global --get core.hooksPath 2>/dev/null || true)"
  [ -n "$LEGACY_GIT_PATH" ] && hooks_dir_is_intact "$LEGACY_GIT_PATH"
}

# _legacy_claude_locate — computes the global Claude settings path and the
# exact PreToolUse command string the pre-rework installer would have
# written for the current BINDLE_CLAUDE_HOME/BINDLE_GUARD_HOME (or their
# defaults), into LEGACY_CLAUDE_SETTINGS / LEGACY_CLAUDE_COMMAND. Shared by
# legacy_global_claude_recognized and migrate_legacy_global_claude so the
# two can never disagree about what "recognized" means.
_legacy_claude_locate() {
  local legacy_claude_home legacy_guard_home
  local legacy_guard_ref legacy_helper_ref

  legacy_claude_home="${BINDLE_CLAUDE_HOME:-$HOME/.claude}"
  legacy_guard_home="${BINDLE_GUARD_HOME:-$HOME/.local/share/bindle}"
  LEGACY_CLAUDE_SETTINGS="$legacy_claude_home/settings.json"

  # The literal '~/...' form is deliberate (shellcheck disable=SC2088
  # below): it matches what the pre-rework installer actually wrote into
  # settings.json for Claude Code's own shell to expand at run time, not a
  # tilde this script's shell should expand.
  if [ "$legacy_claude_home" = "$HOME/.claude" ]; then
    # shellcheck disable=SC2088
    legacy_guard_ref='~/.claude/hooks/bindle-protected-main-guard'
  else
    legacy_guard_ref="$legacy_claude_home/hooks/bindle-protected-main-guard"
  fi
  if [ "$legacy_guard_home" = "$HOME/.local/share/bindle" ]; then
    # shellcheck disable=SC2088
    legacy_helper_ref='~/.local/share/bindle/bin/allow-main-write.sh'
  else
    legacy_helper_ref="$legacy_guard_home/bin/allow-main-write.sh"
  fi
  LEGACY_CLAUDE_COMMAND="$legacy_guard_ref $legacy_helper_ref"
}

# legacy_global_claude_recognized — true iff the global Claude settings file
# holds a PreToolUse entry positively matching what the pre-rework installer
# would have written. Read-only — an absent file, invalid JSON, or a
# non-matching entry are all simply "not recognized" here (never reported;
# see migrate_legacy_global_claude for the reporting version of these same
# checks). On a true result, LEGACY_CLAUDE_SETTINGS / LEGACY_CLAUDE_COMMAND
# are set (via _legacy_claude_locate).
legacy_global_claude_recognized() {
  _legacy_claude_locate
  [ -f "$LEGACY_CLAUDE_SETTINGS" ] || return 1
  json_op valid-json "$LEGACY_CLAUDE_SETTINGS" || return 1
  pretooluse_entry_present "$LEGACY_CLAUDE_SETTINGS" "$LEGACY_CLAUDE_COMMAND"
}

# migrate_legacy_global_git — removes a recognized legacy global
# core.hooksPath (and its hook directory). Only ever called from
# --remove-legacy-global, so always reports what it finds, including an
# absent or unrecognized (foreign) value — the caller explicitly asked to
# migrate legacy Bindle state and deserves to know why nothing happened.
migrate_legacy_global_git() {
  local legacy_path
  legacy_path="$(git config --global --get core.hooksPath 2>/dev/null || true)"
  if [ -z "$legacy_path" ]; then
    say "  no global core.hooksPath is set — nothing to migrate"
    return 0
  fi
  if ! hooks_dir_is_intact "$legacy_path"; then
    problem "global core.hooksPath is set to '$legacy_path', but its contents don't match what Bindle's installer would have produced — refusing to remove configuration Bindle cannot positively prove it owns. If this is stale Bindle state from before the repo-local rework, remove it yourself; otherwise leave it, since it likely belongs to another tool."
    return 0
  fi
  say "  a recognized legacy global core.hooksPath ($legacy_path) predates the repo-local model — migrating it away now"
  if git config --global --unset core.hooksPath 2>/dev/null &&
    ! git config --global --get core.hooksPath >/dev/null 2>&1; then
    did "legacy global core.hooksPath unset"
    if rm -rf "$legacy_path" 2>/dev/null && [ ! -e "$legacy_path" ]; then
      did "removed legacy global hook directory $legacy_path"
    else
      problem "failed to remove legacy global hook directory $legacy_path"
    fi
  else
    problem "failed to unset legacy global core.hooksPath during automatic migration"
  fi
}

migrate_legacy_global_claude() {
  _legacy_claude_locate
  local legacy_settings="$LEGACY_CLAUDE_SETTINGS" legacy_command="$LEGACY_CLAUDE_COMMAND"
  local legacy_claude_home legacy_guard_home
  legacy_claude_home="${BINDLE_CLAUDE_HOME:-$HOME/.claude}"
  legacy_guard_home="${BINDLE_GUARD_HOME:-$HOME/.local/share/bindle}"
  local legacy_guard_installed="$legacy_claude_home/hooks/bindle-protected-main-guard"
  local legacy_helper_installed="$legacy_guard_home/bin/allow-main-write.sh"
  local legacy_owned_deny_file="$legacy_guard_home/claude-deny-owned.json"

  if [ ! -f "$legacy_settings" ]; then
    say "  $legacy_settings does not exist — nothing to migrate"
    return 0
  fi
  if ! json_op valid-json "$legacy_settings"; then
    problem "$legacy_settings exists but is not valid JSON — refusing to check it for a legacy Bindle guard entry. Fix or restore it manually if you believe it holds stale Bindle state."
    return 0
  fi
  if ! pretooluse_entry_present "$legacy_settings" "$legacy_command"; then
    say "  no recognized legacy Bindle guard entry found in $legacy_settings — nothing to migrate"
    return 0
  fi

  say "  a recognized legacy global Claude Code guard entry predates the repo-local model — migrating it away now"
  local detached=1
  if json_op remove-pretooluse "$legacy_settings" "$PRETOOLUSE_MATCHER" "$legacy_command"; then
    did "removed the legacy global PreToolUse guard entry from $legacy_settings"
  else
    problem "failed to update $legacy_settings while removing the legacy PreToolUse guard entry — preserving the legacy guard/helper files since the registration referencing them is still active"
    detached=0
  fi

  if [ -f "$legacy_owned_deny_file" ]; then
    local legacy_owned_json
    if legacy_owned_json="$(read_owned_json "$legacy_owned_deny_file")"; then
      if json_op remove-deny "$legacy_settings" "$legacy_owned_json"; then
        did "removed $(json_op length "$legacy_owned_json") legacy guardrail deny entries from $legacy_settings"
        rm -f "$legacy_owned_deny_file"
      else
        problem "failed to update $legacy_settings while removing legacy owned deny entries — preserving $legacy_owned_deny_file so this can be retried"
      fi
    else
      problem "$legacy_owned_deny_file exists but could not be read as a JSON array — refusing to remove legacy guardrail deny entries from $legacy_settings"
    fi
  fi

  if [ "$detached" -eq 1 ]; then
    if [ -f "$legacy_guard_installed" ]; then
      if rm -f "$legacy_guard_installed" 2>/dev/null && [ ! -e "$legacy_guard_installed" ]; then
        did "removed legacy $legacy_guard_installed"
      else
        problem "failed to remove legacy $legacy_guard_installed"
      fi
    fi
    if [ -f "$legacy_helper_installed" ]; then
      if rm -f "$legacy_helper_installed" 2>/dev/null && [ ! -e "$legacy_helper_installed" ]; then
        did "removed legacy $legacy_helper_installed"
      else
        problem "failed to remove legacy $legacy_helper_installed"
      fi
    fi
  fi
}

if [ "$LEGACY_REMOVE" -eq 1 ]; then
  say "== Legacy global Git hook layer =="
  migrate_legacy_global_git
  say ""
  say "== Legacy global Claude Code layer =="
  migrate_legacy_global_claude
  exit "$fail"
fi

# --- repo context: shared by both layers -------------------------------------
#
# Repository identity is the Git common directory (D018) — resolved once,
# absolute, here, and reused by both layers below. The Claude layer needs
# one further step: Claude Code itself resolves a repository's settings
# "through worktrees to the main checkout" (its own documented behavior),
# so repo_root — the main checkout's working-tree path, NOT necessarily
# $REPO_TARGET's own worktree path — is what Claude Code will actually read
# regardless of which linked worktree bindle was run from.
say "== Bindle guardrails for $REPO_TARGET =="

REPO_APPLICABLE=1
repo_common_dir=""
repo_root=""
if ! git -C "$REPO_TARGET" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [ "$GIT_ONLY" -eq 1 ] || [ "$CLAUDE_ONLY" -eq 1 ]; then
    problem "'$REPO_TARGET' is not inside a Git repository — nothing to do"
  else
    say "  '$REPO_TARGET' is not inside a Git repository — skipping repository-scoped guardrails"
  fi
  REPO_APPLICABLE=0
else
  repo_common_dir="$(git -C "$REPO_TARGET" rev-parse --path-format=absolute --git-common-dir)"
  if [ "$(basename "$repo_common_dir")" = ".git" ]; then
    repo_root="$(dirname "$repo_common_dir")"
  else
    repo_root="$repo_common_dir"
  fi
fi

# Absolute, anchored under the target repository's own Git common
# directory: untracked (inside .git), shared across every linked worktree
# for free (docs/WORKTREES.md — the common dir's config and hooks are
# shared repository-level state), and unambiguous regardless of which
# worktree's own private git-dir a relative core.hooksPath would otherwise
# be resolved against.
HOOKS_DIR="$repo_common_dir/bindle-hooks"

# A SEPARATE directory from HOOKS_DIR (also inside .git, also shared across
# worktrees) for the Claude-layer guard/helper scripts: keeps the two
# layers' installers fully independent — one can be applied/removed via
# --git-only/--claude-only without the other's first-install-vs-re-apply
# staging logic ever observing a directory the other layer already
# partially populated.
CLAUDE_DIR="$repo_common_dir/bindle-claude"
CLAUDE_GUARD_INSTALLED="$CLAUDE_DIR/claude-protected-main-guard"
ALLOW_MAIN_WRITE_INSTALLED="$CLAUDE_DIR/allow-main-write.sh"

# The deny-ownership record is a sibling FILE, not nested inside CLAUDE_DIR
# — it must stay reachable even when guard/helper installation fails
# (permissions.deny hardening is independent of the guard-file install, on
# purpose: see the "incomplete Claude guard/helper installation" test).
OWNED_DENY_FILE="$repo_common_dir/bindle-claude-deny-owned.json"

# Claude Code's own project-settings resolution (see module header) — the
# main checkout's working tree, not necessarily $REPO_TARGET.
CLAUDE_SETTINGS_RELATIVE=".claude/settings.local.json"
CLAUDE_SETTINGS="$repo_root/$CLAUDE_SETTINGS_RELATIVE"

# CLAUDE_EXCLUDE_OWNED_FILE — a tiny ownership marker (sibling of
# OWNED_DENY_FILE, same convention): present iff Bindle itself is the one
# that appended the info/exclude line for $CLAUDE_SETTINGS_RELATIVE (see
# ensure_repo_settings_ignored). Its ABSENCE is what makes an
# already-ignored repository (via its own .gitignore, or a pre-existing
# info/exclude entry) permanently safe from --uninstall ever touching that
# line — Bindle never claims an ignore rule it did not itself add.
CLAUDE_EXCLUDE_OWNED_FILE="$repo_common_dir/bindle-claude-exclude-owned"

# ensure_repo_settings_ignored — if $CLAUDE_SETTINGS_RELATIVE isn't already
# ignored in $repo_root (via its own .gitignore, a global gitignore, or a
# prior run of this function), record a machine-local ignore rule in this
# repository's own <git-common-dir>/info/exclude — shared across every
# linked worktree the same way core.hooksPath is, never committed, never
# touching the repository's own tracked .gitignore. Idempotent: never
# appends a duplicate line. Only ever called from the apply path, and only
# after the preflight tracked-file check above has already refused to
# proceed if the path is tracked — this never has to reconcile with an
# already-tracked file.
#
# CLAUDE_EXCLUDE_OWNED_FILE is written ONLY on the genuine first-append
# path below — never when check-ignore already reports the path ignored
# (some other source owns that), and never on the defensive dedup branch
# (a line already present there wasn't necessarily put there by this
# function). This is deliberately the single place ownership can ever be
# claimed, so --uninstall's removal later can never be wrong about whether
# Bindle actually owns the line it's about to touch.
ensure_repo_settings_ignored() {
  git -C "$repo_root" check-ignore -q -- "$CLAUDE_SETTINGS_RELATIVE" && return 0
  local exclude_file="$repo_common_dir/info/exclude"
  mkdir -p "$(dirname "$exclude_file")" 2>/dev/null || return 1
  if [ -f "$exclude_file" ] && grep -qxF "$CLAUDE_SETTINGS_RELATIVE" "$exclude_file" 2>/dev/null; then
    return 0
  fi
  printf '%s\n' "$CLAUDE_SETTINGS_RELATIVE" >>"$exclude_file" || return 1
  : >"$CLAUDE_EXCLUDE_OWNED_FILE"
}

# remove_owned_exclude_entry — removes the machine-local info/exclude entry
# for $CLAUDE_SETTINGS_RELATIVE, but ONLY when CLAUDE_EXCLUDE_OWNED_FILE
# proves Bindle itself added it. A missing marker means the entry predates
# this Bindle install, came from the repository's own .gitignore, or was
# never added at all — every one of those is a no-op here, never touching a
# line Bindle cannot prove it owns. Callers must only invoke this once
# they've already established it's safe to touch the ignore rule at all
# (settings.local.json is gone — see the --uninstall Claude-layer logic
# below); this function itself only ever guards ownership, not safety.
#
# The marker is cleared once this function has made its one attempt,
# whether or not a matching line was actually found to remove — a marker
# surviving a completed attempt would just be permanently stale, since
# nothing else ever revisits it.
remove_owned_exclude_entry() {
  [ -f "$CLAUDE_EXCLUDE_OWNED_FILE" ] || return 0
  local exclude_file="$repo_common_dir/info/exclude"
  if [ -f "$exclude_file" ] && grep -qxF "$CLAUDE_SETTINGS_RELATIVE" "$exclude_file" 2>/dev/null; then
    local tmp grep_status
    tmp="$(mktemp "$repo_common_dir/.bindle-exclude.XXXXXX" 2>/dev/null)"
    if [ -z "$tmp" ]; then
      problem "failed to stage an updated info/exclude while removing the Bindle-owned ignore entry for $CLAUDE_SETTINGS_RELATIVE — leaving it and the ownership record in place to retry on a future --uninstall"
      return 1
    fi
    grep -vxF "$CLAUDE_SETTINGS_RELATIVE" "$exclude_file" >"$tmp" 2>/dev/null
    grep_status=$?
    # grep -v exits 1 (not an error) when every line matched and got
    # filtered out — i.e. our entry was the file's only line. Only exit
    # code 2 (a genuine read error) is a real failure here.
    if [ "$grep_status" -gt 1 ] || ! mv "$tmp" "$exclude_file" 2>/dev/null; then
      rm -f "$tmp" 2>/dev/null
      problem "failed to remove the Bindle-owned ignore entry for $CLAUDE_SETTINGS_RELATIVE from $exclude_file — leaving it and the ownership record in place to retry on a future --uninstall"
      return 1
    fi
    did "removed the Bindle-owned machine-local ignore entry for $CLAUDE_SETTINGS_RELATIVE from $exclude_file"
  fi
  rm -f "$CLAUDE_EXCLUDE_OWNED_FILE"
  return 0
}

# Absolute paths only: both point inside .git, so there is no meaningful
# "default ~/... shorthand" left to print — every install is repository-
# specific by construction.
PRETOOLUSE_COMMAND="$CLAUDE_GUARD_INSTALLED $ALLOW_MAIN_WRITE_INSTALLED"

# =============================================================================
# --status (read-only, drives `bindle status`): reports one of five states
# per layer — installed / not-installed / partial / conflict / invalid —
# using exactly the same ownership/intactness predicates the Preflight and
# apply/uninstall logic below already rely on (hooks_dir_is_intact,
# pretooluse_entry_present, valid-json, read_owned_json, the tracked-file
# check). This is deliberately the SAME functions, not a parallel
# reimplementation, so `bindle status` can never drift from what `bindle
# init`/`bindle remove` actually enforce.
#
# Never runs Preflight, never gates on or reports legacy-global state
# (status is scoped to THIS repository's own configuration, not a
# machine-wide migration concern), and never mutates anything — not even
# the narrow live repairs --apply is allowed to make.
# =============================================================================

# detect_git_status — Git layer: core.hooksPath is a single-value
# integration point, so its state collapses cleanly onto four of the five
# states. There is no separately-detectable "invalid": hooks_dir_is_intact
# only checks the dispatcher's executable bit and each hook symlink's
# target name, never the dispatcher's actual script content, so a
# structurally "intact" but content-corrupted dispatcher is
# indistinguishable from a genuinely good one, and anything that fails the
# shape check already falls out as "partial" below — there is no remaining
# evidence that would let this function tell "malformed" apart from
# "incomplete" for this layer.
detect_git_status() {
  local hookspath dir_exists=0 dir_intact=0
  hookspath="$(git -C "$REPO_TARGET" config --local --get core.hooksPath 2>/dev/null || true)"
  [ -e "$HOOKS_DIR" ] && dir_exists=1
  hooks_dir_is_intact "$HOOKS_DIR" && dir_intact=1

  if [ -n "$hookspath" ] && [ "$hookspath" != "$HOOKS_DIR" ]; then
    # A foreign core.hooksPath (another hook manager) occupies the one
    # integration point Git allows — the same condition apply's own
    # preflight refuses to override.
    echo "conflict"
  elif [ -z "$hookspath" ] && [ "$dir_exists" -eq 0 ]; then
    echo "not-installed"
  elif [ "$hookspath" = "$HOOKS_DIR" ] && [ "$dir_intact" -eq 1 ]; then
    echo "installed"
  else
    # Recognizable Bindle ownership (hookspath points at $HOOKS_DIR, or
    # $HOOKS_DIR exists at Bindle's own reserved path) but the two halves
    # don't both fully agree — e.g. the dispatcher/symlink set is missing
    # or broken, or the directory exists but isn't wired into
    # core.hooksPath yet.
    echo "partial"
  fi
}

# detect_claude_status — Claude layer: unlike core.hooksPath, Claude Code's
# hooks.PreToolUse array is additive/multi-owner, so "another tool already
# has this exact matcher" isn't a meaningful conflict the way a foreign
# core.hooksPath is. The one real single-owner integration point Bindle
# actually claims exclusively here is the settings.local.json FILE itself
# (whether Bindle may modify it at all) — install-guardrails.sh already
# refuses to touch a tracked, team-owned copy of it, which is exactly
# "occupied by something not Bindle-owned".
#
# "Bindle evidence" below is deliberately restricted to paths/markers that
# are exclusively Bindle's own (the guard/helper scripts under
# bindle-claude/, the owned-deny bookkeeping file, and the info/exclude
# ownership marker) plus a PreToolUse entry whose command string names
# those exclusive paths — never mere existence of settings.local.json
# itself, which is Claude Code's own native, non-Bindle-exclusive file and
# may legitimately hold unrelated content. Without that restriction, any
# repo using Claude Code's local settings for something else entirely
# would misreport as a Bindle "partial" install.
#
# "installed" requires OWNED_DENY_FILE unconditionally: bindle remove
# reads it to know which deny entries it may safely remove, and its
# absence loses that information regardless of anything else — the
# installation is no longer complete/intact even if every other artifact
# looks fine. CLAUDE_EXCLUDE_OWNED_FILE is conditional, not required in
# the same unconditional sense: it exists at all only when Bindle itself
# is the one that claimed the info/exclude ignore line (see
# ensure_repo_settings_ignored below), so its ABSENCE is a normal,
# complete install whenever Bindle never needed to claim that line — never
# by itself something "installed" should be blocked on. Once it DOES
# exist, though, it creates its own integrity requirement: it asserts
# bindle remove may safely remove that ignore line, so "installed" also
# requires the line it names still actually being present in
# info/exclude. ensure_repo_settings_ignored() deliberately never creates
# the marker when the repository already ignored
# settings.local.json before Bindle ever touched it (its own .gitignore,
# or a pre-existing info/exclude line) — that is a normal, complete
# install, just one where Bindle never needed to claim an ignore rule.
detect_claude_status() {
  if git -C "$repo_root" ls-files --error-unmatch -- "$CLAUDE_SETTINGS_RELATIVE" >/dev/null 2>&1; then
    echo "conflict"
    return
  fi

  local guard_exists=0 helper_exists=0 owned_deny_exists=0 exclude_owned_exists=0
  [ -x "$CLAUDE_GUARD_INSTALLED" ] && guard_exists=1
  [ -x "$ALLOW_MAIN_WRITE_INSTALLED" ] && helper_exists=1
  [ -f "$OWNED_DENY_FILE" ] && owned_deny_exists=1
  [ -f "$CLAUDE_EXCLUDE_OWNED_FILE" ] && exclude_owned_exists=1

  local owned_deny_json="" owned_deny_valid=1
  if [ "$owned_deny_exists" -eq 1 ] && ! owned_deny_json="$(read_owned_json "$OWNED_DENY_FILE")"; then
    owned_deny_valid=0
  fi

  # exclude_ok — true unless CLAUDE_EXCLUDE_OWNED_FILE claims ownership of
  # an info/exclude ignore line that is no longer actually there (the
  # same "still owns it, still matches" question remove_owned_exclude_entry
  # itself asks before touching that line). Vacuously true when the
  # marker doesn't exist — there's nothing to be inconsistent about.
  local exclude_ok=1
  if [ "$exclude_owned_exists" -eq 1 ]; then
    local exclude_file="$repo_common_dir/info/exclude"
    if [ -f "$exclude_file" ] && grep -qxF "$CLAUDE_SETTINGS_RELATIVE" "$exclude_file" 2>/dev/null; then
      exclude_ok=1
    else
      exclude_ok=0
    fi
  fi

  local settings_exists=0 settings_valid=1
  [ -f "$CLAUDE_SETTINGS" ] && settings_exists=1
  if [ "$settings_exists" -eq 1 ] && ! json_op valid-json "$CLAUDE_SETTINGS"; then
    settings_valid=0
  fi

  local pretooluse_ok=0
  if [ "$settings_exists" -eq 1 ] && [ "$settings_valid" -eq 1 ]; then
    pretooluse_entry_present "$CLAUDE_SETTINGS" "$PRETOOLUSE_COMMAND" && pretooluse_ok=1
  fi

  local bindle_evidence=0
  { [ "$guard_exists" -eq 1 ] || [ "$helper_exists" -eq 1 ] || [ "$owned_deny_exists" -eq 1 ] ||
    [ "$exclude_owned_exists" -eq 1 ] || [ "$pretooluse_ok" -eq 1 ]; } && bindle_evidence=1

  # A broken owned-deny bookkeeping file is always Bindle's own artifact —
  # its mere presence, valid or not, IS the ownership evidence.
  if [ "$owned_deny_exists" -eq 1 ] && [ "$owned_deny_valid" -eq 0 ]; then
    echo "invalid"
    return
  fi
  # An unreadable settings.local.json only counts as Bindle's own
  # "invalid" state when some other exclusively-Bindle artifact already
  # proves Bindle was involved here — otherwise it's simply not
  # (yet/ever) Bindle's problem to report on.
  if [ "$settings_exists" -eq 1 ] && [ "$settings_valid" -eq 0 ] && [ "$bindle_evidence" -eq 1 ]; then
    echo "invalid"
    return
  fi

  if [ "$bindle_evidence" -eq 0 ]; then
    echo "not-installed"
    return
  fi

  local deny_intact=1
  if [ "$owned_deny_exists" -eq 1 ] && [ "$owned_deny_valid" -eq 1 ] && [ "$settings_exists" -eq 1 ] &&
    [ "$settings_valid" -eq 1 ] && [ "$owned_deny_json" != "[]" ]; then
    json_op deny-subset "$CLAUDE_SETTINGS" "$owned_deny_json" || deny_intact=0
  fi

  if [ "$settings_valid" -eq 1 ] && [ "$pretooluse_ok" -eq 1 ] && [ "$guard_exists" -eq 1 ] &&
    [ "$helper_exists" -eq 1 ] && [ "$owned_deny_exists" -eq 1 ] && [ "$deny_intact" -eq 1 ] &&
    [ "$exclude_ok" -eq 1 ]; then
    echo "installed"
  else
    echo "partial"
  fi
}

if [ "$MODE" = "status" ]; then
  if [ "$REPO_APPLICABLE" -ne 1 ]; then
    problem "'$REPO_TARGET' is not inside a Git repository — nothing to report"
    exit 1
  fi
  if [ "$CLAUDE_ONLY" -eq 0 ]; then
    printf 'GIT_STATUS=%s\n' "$(detect_git_status)"
  fi
  if [ "$GIT_ONLY" -eq 0 ]; then
    printf 'CLAUDE_STATUS=%s\n' "$(detect_claude_status)"
  fi
  exit 0
fi

# =============================================================================
# Preflight (--apply/--uninstall only): validate BOTH requested layers
# before mutating either one. Preview never mutates, so it has nothing to
# protect and runs its own inline checks below as before. On ANY preflight
# problem, NOTHING is mutated for either layer — the whole invocation fails
# clean, so `bindle init`/`bindle remove` can never leave one guardrail
# layer newly installed/removed without the other when both were requested.
#
# This is deliberately non-exhaustive: it covers every condition that is
# knowable without mutating anything (legacy-global recognition, an
# existing foreign core.hooksPath, a corrupted local hook/settings file). A
# failure that can only occur DURING mutation (disk fills up, permissions
# change concurrently, ...) is rare and handled separately, narrowly, by
# the post-mutation rollback below — not by trying to predict every
# possible I/O failure here.
# =============================================================================
if [ "$REPO_APPLICABLE" -eq 1 ] && { [ "$MODE" = "apply" ] || [ "$MODE" = "uninstall" ]; }; then
  say "== Preflight =="

  # --- legacy-global gating ---
  # A recognized pre-rework global install must never be silently touched
  # by a normal, repository-scoped invocation. bindle init/remove are NOT
  # the migration mechanism — --remove-legacy-global (or `bindle
  # migrate-legacy-global`) is, and invoking THAT is what makes the
  # machine-wide side effect intentional.
  if [ "$CLAUDE_ONLY" -eq 0 ] && legacy_global_git_recognized; then
    problem "a recognized legacy machine-global Bindle Git guardrail is still installed (global core.hooksPath: $LEGACY_GIT_PATH). 'bindle init'/'bindle remove' are repository-scoped and refuse to silently migrate or remove machine-global state. Run the explicit migration first — 'bindle migrate-legacy-global' (or 'install-guardrails.sh --remove-legacy-global') — then retry."
  fi
  if [ "$GIT_ONLY" -eq 0 ] && legacy_global_claude_recognized; then
    problem "a recognized legacy machine-global Bindle Claude Code guard entry is still installed in $LEGACY_CLAUDE_SETTINGS. 'bindle init'/'bindle remove' are repository-scoped and refuse to silently migrate or remove machine-global state. Run the explicit migration first — 'bindle migrate-legacy-global' (or 'install-guardrails.sh --remove-legacy-global') — then retry."
  fi

  # --- per-layer ownership/conflict preflight (non-mutating) ---
  if [ "$CLAUDE_ONLY" -eq 0 ]; then
    preflight_existing_hookspath="$(git -C "$REPO_TARGET" config --local --get core.hooksPath 2>/dev/null || true)"
    if [ -n "$preflight_existing_hookspath" ] && [ "$preflight_existing_hookspath" != "$HOOKS_DIR" ]; then
      problem "'$REPO_TARGET' already has a local core.hooksPath set to '$preflight_existing_hookspath' (not Bindle's — possibly another hook manager: pre-commit, husky, lefthook, ...). Refusing to replace it — remove or reconcile that configuration yourself first if you want Bindle's guardrails installed here."
    fi
    if [ "$MODE" = "apply" ] && [ -e "$HOOKS_DIR" ] && [ ! -x "$HOOKS_DIR/.bindle-git-hook-dispatch" ]; then
      problem "$HOOKS_DIR already exists but is missing its dispatcher — refusing to repair it live. Remove $HOOKS_DIR manually (or run --uninstall) and re-run --apply for a clean install."
    fi
    if [ "$MODE" = "apply" ] && [ -x "$HOOKS_DIR/.bindle-git-hook-dispatch" ] && ! hooks_dir_is_intact "$HOOKS_DIR"; then
      problem "the active $HOOKS_DIR has a missing or unexpected hook symlink — refusing to repair it live. Remove $HOOKS_DIR manually (or run --uninstall) and re-run --apply for a clean install."
    fi
  fi
  if [ "$GIT_ONLY" -eq 0 ]; then
    if [ -f "$CLAUDE_SETTINGS" ] && ! json_op valid-json "$CLAUDE_SETTINGS"; then
      problem "$CLAUDE_SETTINGS exists but is not valid JSON — refusing to modify hooks/permissions.deny in it. Fix or restore it manually, then retry."
    fi
    if [ "$MODE" = "uninstall" ] && [ -f "$OWNED_DENY_FILE" ] && ! read_owned_json "$OWNED_DENY_FILE" >/dev/null; then
      problem "$OWNED_DENY_FILE exists but could not be read as a JSON array — refusing to remove guardrail deny entries from $CLAUDE_SETTINGS. Fix or restore it manually, then retry."
    fi
    if git -C "$repo_root" ls-files --error-unmatch -- "$CLAUDE_SETTINGS_RELATIVE" >/dev/null 2>&1; then
      problem "'$repo_root' already tracks $CLAUDE_SETTINGS_RELATIVE in Git — refusing to modify a tracked, team-shared file. Untrack it (git rm --cached $CLAUDE_SETTINGS_RELATIVE) if this should be personal/local settings, then retry."
    fi
  fi

  if [ "$fail" -ne 0 ]; then
    say ""
    say "Preflight found one or more problems above — nothing was installed or removed for either guardrail layer."
    exit "$fail"
  fi
fi

# --- deny manifest expansion: canonical policy above -> Claude's required
# individual permissions.deny strings. Nothing below this point encodes
# policy — only how the four data sets above translate into rule syntax.
DENY_MANIFEST=()
for g in "${FILE_DENY_GLOBS[@]}"; do
  for tool in "${FILE_DENY_TOOLS[@]}"; do
    DENY_MANIFEST+=("$tool($g)")
  done
done
for cmd in "${ENV_DUMP_COMMANDS[@]}"; do
  DENY_MANIFEST+=("Bash($cmd)" "Bash($cmd:*)")
done
for f in "${CAT_DENY_FILES[@]}"; do
  DENY_MANIFEST+=("Bash(cat $f)")
done
for cmd in "${KEYCHAIN_DUMP_COMMANDS[@]}"; do
  DENY_MANIFEST+=("Bash($cmd:*)")
done

# JSON array of the deny manifest, for passing to settings_json.py.
deny_manifest_json() {
  printf '%s\n' "${DENY_MANIFEST[@]}" | json_op lines-to-json-array
}

# GIT_LAYER_CHANGED — set to 1 only by a genuine fresh cross-invocation
# state transition (a brand-new install, or a genuine opt-out), never by a
# redundant re-apply/re-uninstall that finds the layer already in the
# desired state. Used below to decide whether a Claude-layer failure later
# in THIS invocation needs to roll the Git layer back.
GIT_LAYER_CHANGED=0

# git_layer_fresh_install — stage the dispatcher + full hook-name symlink
# set, verify, move into place, then set repo-local core.hooksPath. This is
# the normal first-time --apply path, factored into a function so the same
# idempotent logic can also roll a --uninstall back to its pre-invocation
# state if the Claude layer then fails (see the post-mutation rollback
# below). Reports its own problem() on failure; sets GIT_LAYER_CHANGED=1 on
# a genuine fresh install.
git_layer_fresh_install() {
  local staging_dir
  staging_dir="$(mktemp -d "$repo_common_dir/.bindle-hooks.staging.XXXXXX" 2>/dev/null)"
  if [ -z "$staging_dir" ]; then
    problem "failed to create a staging directory under $repo_common_dir"
    problem "staging the Git hook directory failed — leaving core.hooksPath unchanged (never activating an incomplete Git layer)"
    return 1
  fi

  if ! install -m 0755 "$SCRIPT_DIR/git-hook-dispatch.sh" "$staging_dir/.bindle-git-hook-dispatch" 2>/dev/null; then
    problem "failed to stage the dispatcher"
    rm -rf "$staging_dir" 2>/dev/null
    problem "staging the Git hook directory failed — leaving core.hooksPath unchanged (never activating an incomplete Git layer)"
    return 1
  fi

  local name symlinks_failed=0
  for name in "${HOOK_NAMES[@]}"; do
    ln -sf ".bindle-git-hook-dispatch" "$staging_dir/$name" 2>/dev/null || symlinks_failed=1
  done
  if [ "$symlinks_failed" -eq 1 ]; then
    problem "failed to stage one or more standard hook symlinks"
    rm -rf "$staging_dir" 2>/dev/null
    problem "staging the Git hook directory failed — leaving core.hooksPath unchanged (never activating an incomplete Git layer)"
    return 1
  fi

  # Verify every required artifact actually landed in staging before
  # trusting it enough to move into place — a staging directory that
  # merely exists is not the same as one complete.
  if ! hooks_dir_is_intact "$staging_dir"; then
    problem "staged dispatcher/symlinks are missing or incomplete"
    rm -rf "$staging_dir" 2>/dev/null
    problem "staging the Git hook directory failed — leaving core.hooksPath unchanged (never activating an incomplete Git layer)"
    return 1
  fi

  if [ -e "$HOOKS_DIR" ]; then
    problem "$HOOKS_DIR already exists but is missing its dispatcher — refusing to repair it live. Remove $HOOKS_DIR manually (or run --uninstall) and re-run --apply for a clean install."
    rm -rf "$staging_dir" 2>/dev/null
    return 1
  fi

  if ! mv "$staging_dir" "$HOOKS_DIR" 2>/dev/null; then
    problem "failed to move the staged Git hook directory into place at $HOOKS_DIR"
    rm -rf "$staging_dir" 2>/dev/null
    return 1
  fi
  did "installed dispatcher + ${#HOOK_NAMES[@]} standard hook symlinks at $HOOKS_DIR"

  local hookspath_now
  hookspath_now="$(git -C "$REPO_TARGET" config --local --get core.hooksPath 2>/dev/null || true)"
  if [ -z "$hookspath_now" ]; then
    if git -C "$REPO_TARGET" config --local core.hooksPath "$HOOKS_DIR" 2>/dev/null &&
      [ "$(git -C "$REPO_TARGET" config --local --get core.hooksPath 2>/dev/null)" = "$HOOKS_DIR" ]; then
      did "set repo-local core.hooksPath to $HOOKS_DIR for $REPO_TARGET"
      GIT_LAYER_CHANGED=1
    else
      problem "failed to set repo-local core.hooksPath to $HOOKS_DIR for $REPO_TARGET"
      return 1
    fi
  else
    say "  repo-local core.hooksPath already set to $HOOKS_DIR — unchanged"
  fi
  return 0
}

# git_layer_fresh_uninstall — unset repo-local core.hooksPath (only if it
# points at Bindle's own $HOOKS_DIR) and remove $HOOKS_DIR. This is the
# normal --uninstall path, factored into a function so the same logic can
# also roll a --apply back to its pre-invocation state if the Claude layer
# then fails (see the post-mutation rollback below). Reports its own
# problem() on failure; sets GIT_LAYER_CHANGED=1 on a genuine removal.
git_layer_fresh_uninstall() {
  local existing ok=0
  existing="$(git -C "$REPO_TARGET" config --local --get core.hooksPath 2>/dev/null || true)"
  if [ "$existing" = "$HOOKS_DIR" ]; then
    say "  removing repo-local core.hooksPath ($HOOKS_DIR)"
    if git -C "$REPO_TARGET" config --local --unset core.hooksPath 2>/dev/null &&
      ! git -C "$REPO_TARGET" config --local --get core.hooksPath >/dev/null 2>&1; then
      did "core.hooksPath unset for $REPO_TARGET"
      GIT_LAYER_CHANGED=1
      ok=1
    else
      problem "failed to unset repo-local core.hooksPath for $REPO_TARGET"
    fi
  else
    say "  repo-local core.hooksPath does not point at Bindle — leaving it untouched"
    ok=1
  fi

  if [ -d "$HOOKS_DIR" ]; then
    if rm -rf "$HOOKS_DIR" 2>/dev/null && [ ! -e "$HOOKS_DIR" ]; then
      did "removed $HOOKS_DIR"
      GIT_LAYER_CHANGED=1
    else
      problem "failed to remove $HOOKS_DIR"
      ok=0
    fi
  else
    say "  $HOOKS_DIR already absent"
  fi
  [ "$ok" -eq 1 ]
}

# =============================================================================
# Git layer — repo-local, opt-in. Skipped entirely with --claude-only.
# =============================================================================
if [ "$CLAUDE_ONLY" -eq 0 ]; then
  say "== Git hook layer =="
  if [ "$MODE" = "preview" ] && legacy_global_git_recognized; then
    say "  NOTE: a recognized legacy global core.hooksPath ($LEGACY_GIT_PATH) exists — 'bindle init'/'bindle remove' will refuse to run until it is migrated away explicitly ('bindle migrate-legacy-global' / install-guardrails.sh --remove-legacy-global)."
  fi

  if [ "$REPO_APPLICABLE" -eq 1 ]; then
    existing_hookspath="$(git -C "$REPO_TARGET" config --local --get core.hooksPath 2>/dev/null || true)"
    GIT_LAYER_BLOCKED=0
    if [ -n "$existing_hookspath" ] && [ "$existing_hookspath" != "$HOOKS_DIR" ]; then
      problem "'$REPO_TARGET' already has a local core.hooksPath set to '$existing_hookspath' (not Bindle's — possibly another hook manager: pre-commit, husky, lefthook, ...). Refusing to replace it — remove or reconcile that configuration yourself first if you want Bindle's guardrails installed here."
      GIT_LAYER_BLOCKED=1
    fi

    if [ "$MODE" = "uninstall" ]; then
      git_layer_fresh_uninstall
    elif [ "$GIT_LAYER_BLOCKED" -eq 0 ]; then
      if [ "$MODE" = "apply" ]; then
        if [ ! -x "$HOOKS_DIR/.bindle-git-hook-dispatch" ]; then
          # First install (or a previously-deleted installation): the
          # dispatcher specifically isn't there yet, so core.hooksPath
          # either isn't set or points at nothing — no concurrent Git
          # operation can be reading this path.
          git_layer_fresh_install
        else
          # Re-apply to an already-existing $HOOKS_DIR: NEVER replace the
          # directory itself. Two renames (move the live directory aside,
          # move a replacement into its place) are not atomic as a PAIR —
          # between them core.hooksPath would point at a path that doesn't
          # exist, and a concurrent Git operation would silently find no
          # hooks at all, skipping this layer entirely. Instead: verify the
          # existing installation is exactly what Bindle would have
          # installed, then replace ONLY the dispatcher file via a
          # same-directory temp file and a single atomic rename over
          # .bindle-git-hook-dispatch. Every symlink already points at that
          # literal filename and is never touched — Git always resolves
          # either the complete old dispatcher or the complete new one,
          # never a missing hook directory. This is a re-apply of an
          # already-adopted layer, not a fresh adoption — GIT_LAYER_CHANGED
          # deliberately stays 0 here (nothing for a later cross-layer
          # rollback to undo).
          git_layer_ready=1
          if ! hooks_dir_is_intact "$HOOKS_DIR"; then
            problem "the active $HOOKS_DIR has a missing or unexpected hook symlink — refusing to repair it live. Remove $HOOKS_DIR manually (or run --uninstall) and re-run --apply for a clean install."
            git_layer_ready=0
          fi

          if [ "$git_layer_ready" -eq 1 ]; then
            staging_dispatch="$HOOKS_DIR/.bindle-git-hook-dispatch.new.$$"
            if ! install -m 0755 "$SCRIPT_DIR/git-hook-dispatch.sh" "$staging_dispatch" 2>/dev/null; then
              problem "failed to stage the updated dispatcher — the active installation at $HOOKS_DIR is untouched"
              git_layer_ready=0
              rm -f "$staging_dispatch" 2>/dev/null
            elif [ ! -x "$staging_dispatch" ]; then
              problem "staged dispatcher is missing or not executable — the active installation at $HOOKS_DIR is untouched"
              git_layer_ready=0
              rm -f "$staging_dispatch" 2>/dev/null
            elif mv "$staging_dispatch" "$HOOKS_DIR/.bindle-git-hook-dispatch" 2>/dev/null; then
              did "updated the dispatcher at $HOOKS_DIR (all ${#HOOK_NAMES[@]} existing hook symlinks left untouched)"
            else
              problem "failed to swap the updated dispatcher into place at $HOOKS_DIR"
              rm -f "$staging_dispatch" 2>/dev/null
              git_layer_ready=0
            fi
          fi

          if [ "$git_layer_ready" -eq 1 ] && [ -z "$existing_hookspath" ]; then
            if git -C "$REPO_TARGET" config --local core.hooksPath "$HOOKS_DIR" 2>/dev/null &&
              [ "$(git -C "$REPO_TARGET" config --local --get core.hooksPath 2>/dev/null)" = "$HOOKS_DIR" ]; then
              did "set repo-local core.hooksPath to $HOOKS_DIR for $REPO_TARGET"
              GIT_LAYER_CHANGED=1
            else
              problem "failed to set repo-local core.hooksPath to $HOOKS_DIR for $REPO_TARGET"
            fi
          elif [ "$git_layer_ready" -eq 1 ]; then
            say "  repo-local core.hooksPath already set to $HOOKS_DIR — unchanged"
          fi
        fi
      else
        if [ -x "$HOOKS_DIR/.bindle-git-hook-dispatch" ]; then
          would "update dispatcher + ${#HOOK_NAMES[@]} symlinks in $HOOKS_DIR (already exists)"
        else
          would "create $HOOKS_DIR with dispatcher + ${#HOOK_NAMES[@]} symlinks"
        fi
        if [ -z "$existing_hookspath" ]; then
          would "set repo-local core.hooksPath to $HOOKS_DIR for $REPO_TARGET"
        else
          say "  repo-local core.hooksPath already set to $HOOKS_DIR — no change needed"
        fi
      fi
    fi
  fi
fi

# fail_before_claude — the fail flag as it stood right after the Git layer
# finished (whether or not the Git layer actually ran). Compared against
# $fail after the Claude layer below to detect "the Claude layer introduced
# a NEW problem this run" — the only case where a completed Git-layer
# state transition needs rolling back.
fail_before_claude="$fail"

# =============================================================================
# Claude layer: PreToolUse guard + allow-main-write helper, now repo-local —
# installed into $CLAUDE_SETTINGS (the target repository's own
# .claude/settings.local.json), never into any global Claude configuration.
# Skipped entirely with --git-only.
# =============================================================================
if [ "$GIT_ONLY" -eq 0 ]; then
  say ""
  say "== Claude Code layer =="
  if [ "$MODE" = "preview" ] && legacy_global_claude_recognized; then
    say "  NOTE: a recognized legacy global Claude Code guard entry exists in $LEGACY_CLAUDE_SETTINGS — 'bindle init'/'bindle remove' will refuse to run until it is migrated away explicitly ('bindle migrate-legacy-global' / install-guardrails.sh --remove-legacy-global)."
  fi

  if [ "$REPO_APPLICABLE" -eq 1 ]; then
    if [ "$MODE" = "uninstall" ]; then
      # Config must be detached BEFORE the files it references are
      # removed: if settings.local.json's PreToolUse entry still names the
      # guard/helper scripts and those files were deleted first, Claude
      # Code would be left with an active hook registration pointing at
      # nothing. pretooluse_detached only reaches 1 once that entry is
      # confirmed gone (or there was never a settings file to hold one) —
      # the guard/helper files are removed strictly after, and only then.
      pretooluse_detached=1
      deny_detached=1
      settings_file_gone=1
      if [ -f "$CLAUDE_SETTINGS" ]; then
        settings_file_gone=0
        if ! json_op valid-json "$CLAUDE_SETTINGS"; then
          problem "$CLAUDE_SETTINGS exists but is not valid JSON — refusing to modify hooks/permissions.deny in it, and preserving the installed guard/helper files since the registration referencing them can't be safely detached. Fix or restore it manually, then re-run --uninstall."
          pretooluse_detached=0
          deny_detached=0
        else
          if json_op remove-pretooluse "$CLAUDE_SETTINGS" "$PRETOOLUSE_MATCHER" "$PRETOOLUSE_COMMAND"; then
            did "removed the PreToolUse guard entry from $CLAUDE_SETTINGS"
          else
            problem "failed to update $CLAUDE_SETTINGS while removing the PreToolUse guard entry — preserving the installed guard/helper files since the registration referencing them is still active"
            pretooluse_detached=0
          fi

          # permissions.deny / ownership cleanup is a different config
          # surface (unrelated to the PreToolUse entry or the guard/helper
          # files) and stays independently handled regardless of the
          # detach outcome above.
          if owned_deny_json="$(read_owned_json "$OWNED_DENY_FILE")"; then
            if json_op remove-deny "$CLAUDE_SETTINGS" "$owned_deny_json"; then
              did "removed $(json_op length "$owned_deny_json") guardrail deny entries from $CLAUDE_SETTINGS (never a pre-existing entry that happened to match)"
              rm -f "$OWNED_DENY_FILE"
            else
              problem "failed to update $CLAUDE_SETTINGS while removing owned deny entries — preserving $OWNED_DENY_FILE so this can be retried"
              deny_detached=0
            fi
          else
            problem "$OWNED_DENY_FILE exists but could not be read as a JSON array — refusing to remove guardrail deny entries from $CLAUDE_SETTINGS. Preserving the file rather than treating it as empty and deleting the evidence — fix or restore it manually, then re-run --uninstall."
            deny_detached=0
          fi

          # Only once EVERYTHING Bindle owns inside $CLAUDE_SETTINGS was
          # cleanly detached above (both flags still 1) do we even ask
          # whether the file itself is now empty — a partially-detached
          # file must never be judged empty just because one half
          # succeeded. See settings_json.py's doc-is-empty: content left
          # behind by the user (or by any other tool) keeps the file
          # non-empty, so it — and its info/exclude ignore rule, if any —
          # is left completely alone (never made accidentally
          # committable merely to achieve byte-for-byte cleanup).
          if [ "$pretooluse_detached" -eq 1 ] && [ "$deny_detached" -eq 1 ]; then
            if json_op doc-is-empty "$CLAUDE_SETTINGS"; then
              if rm -f "$CLAUDE_SETTINGS" 2>/dev/null && [ ! -e "$CLAUDE_SETTINGS" ]; then
                did "removed $CLAUDE_SETTINGS (empty once Bindle's own content was removed)"
                rmdir "$(dirname "$CLAUDE_SETTINGS")" 2>/dev/null || true
                settings_file_gone=1
              else
                problem "failed to remove $CLAUDE_SETTINGS after it became empty — leaving its machine-local ignore rule (if any) in place"
              fi
            else
              say "  $CLAUDE_SETTINGS still holds content Bindle doesn't own — leaving the file (and its machine-local ignore rule, if any) in place"
            fi
          fi
        fi
      fi

      if [ "$settings_file_gone" -eq 1 ]; then
        remove_owned_exclude_entry
      fi

      if [ "$pretooluse_detached" -eq 1 ]; then
        if [ -f "$CLAUDE_GUARD_INSTALLED" ]; then
          if rm -f "$CLAUDE_GUARD_INSTALLED" 2>/dev/null && [ ! -e "$CLAUDE_GUARD_INSTALLED" ]; then
            did "removed $CLAUDE_GUARD_INSTALLED"
          else
            problem "failed to remove $CLAUDE_GUARD_INSTALLED"
          fi
        fi
        if [ -f "$ALLOW_MAIN_WRITE_INSTALLED" ]; then
          if rm -f "$ALLOW_MAIN_WRITE_INSTALLED" 2>/dev/null && [ ! -e "$ALLOW_MAIN_WRITE_INSTALLED" ]; then
            did "removed $ALLOW_MAIN_WRITE_INSTALLED"
          else
            problem "failed to remove $ALLOW_MAIN_WRITE_INSTALLED"
          fi
        fi
      fi
      # CLAUDE_DIR itself is removed only once genuinely empty — never
      # rm -rf, so a preserved malformed OWNED_DENY_FILE (or anything else
      # left behind by a partial failure above) is never silently
      # destroyed along with it.
      rmdir "$CLAUDE_DIR" 2>/dev/null || true
    else
      if [ "$MODE" = "apply" ]; then
        # The guard and helper scripts must be on disk BEFORE the
        # PreToolUse entry naming them is ever registered — registering a
        # hook whose command points at a file that isn't actually there
        # would activate a Claude-layer guard with a missing artifact.
        # claude_files_ready gates that registration below; it does NOT
        # gate the permissions.deny hardening, which is independent
        # settings content unrelated to whether these two script files
        # exist.
        claude_files_ready=1
        if ! mkdir -p "$CLAUDE_DIR" "$(dirname "$CLAUDE_SETTINGS")" 2>/dev/null; then
          problem "failed to create $CLAUDE_DIR or $(dirname "$CLAUDE_SETTINGS")"
          claude_files_ready=0
        else
          # $CLAUDE_GUARD_INSTALLED is the exact path an already-registered
          # PreToolUse entry's "command" names — on a re-apply, that entry
          # can already be active and resolving to whatever is currently
          # at this path. Staged the same way as the Git dispatcher above
          # (temp file in the same directory, verified, then an atomic
          # same-filesystem rename into place) so a failure partway
          # through never leaves a truncated/partial file where an active
          # hook is looking for it.
          #
          # $ALLOW_MAIN_WRITE_INSTALLED does NOT need the same treatment:
          # the guard script only ever uses that path as a STRING in its
          # deny message (see claude-protected-main-guard.sh) — it never
          # executes it, so nothing about hook resolution depends on its
          # content. A corrupted helper script would only cause a later,
          # separate, explicitly-invoked command to fail cleanly (a normal
          # nonzero exit), not silently break the already-active hook.
          staging_guard="$CLAUDE_DIR/.bindle-protected-main-guard.staging.$$"
          if ! install -m 0755 "$SCRIPT_DIR/claude-protected-main-guard.sh" "$staging_guard" 2>/dev/null; then
            problem "failed to stage $CLAUDE_GUARD_INSTALLED — the active installation (if any) is untouched"
            claude_files_ready=0
            rm -f "$staging_guard" 2>/dev/null
          elif [ ! -x "$staging_guard" ]; then
            problem "staged guard script is missing or not executable — the active installation (if any) is untouched"
            claude_files_ready=0
            rm -f "$staging_guard" 2>/dev/null
          elif ! mv "$staging_guard" "$CLAUDE_GUARD_INSTALLED" 2>/dev/null; then
            problem "failed to move the staged guard script into place at $CLAUDE_GUARD_INSTALLED"
            claude_files_ready=0
            rm -f "$staging_guard" 2>/dev/null
          elif ! install -m 0755 "$SCRIPT_DIR/allow-main-write.sh" "$ALLOW_MAIN_WRITE_INSTALLED" 2>/dev/null; then
            problem "failed to install $ALLOW_MAIN_WRITE_INSTALLED"
            claude_files_ready=0
          else
            did "installed $CLAUDE_GUARD_INSTALLED and $ALLOW_MAIN_WRITE_INSTALLED"
          fi
        fi

        claude_settings_ready=1
        if [ -f "$CLAUDE_SETTINGS" ]; then
          if ! json_op valid-json "$CLAUDE_SETTINGS"; then
            problem "$CLAUDE_SETTINGS exists but is not valid JSON — refusing to modify hooks/permissions.deny in it. Fix or restore it manually, then re-run --apply."
            claude_settings_ready=0
          fi
        elif ! echo '{}' >"$CLAUDE_SETTINGS" 2>/dev/null; then
          problem "failed to create $CLAUDE_SETTINGS"
          claude_settings_ready=0
        fi

        if [ "$claude_settings_ready" -eq 1 ] && ! ensure_repo_settings_ignored; then
          problem "failed to record $CLAUDE_SETTINGS_RELATIVE as ignored in $repo_common_dir/info/exclude — refusing to write repo-local settings that would show up as an accidentally-committable untracked file"
          claude_settings_ready=0
        fi

        if [ "$claude_settings_ready" -eq 1 ]; then
          if [ "$claude_files_ready" -eq 0 ]; then
            problem "guard/helper installation failed — refusing to register the PreToolUse hook entry (never activating a layer with missing artifacts)"
          elif pretooluse_entry_present "$CLAUDE_SETTINGS" "$PRETOOLUSE_COMMAND"; then
            say "  PreToolUse guard entry already present — unchanged"
          else
            if json_op add-pretooluse "$CLAUDE_SETTINGS" "$PRETOOLUSE_MATCHER" "$PRETOOLUSE_COMMAND" 5; then
              did "added PreToolUse guard entry ($PRETOOLUSE_MATCHER) to $CLAUDE_SETTINGS"
            else
              problem "failed to update $CLAUDE_SETTINGS while adding the PreToolUse guard entry"
            fi
          fi

          # Determine which manifest entries are genuinely NEW here — not
          # already present before this merge — BEFORE mutating anything,
          # so a byte-identical pre-existing entry (from the user, or from
          # any other tool) is never recorded as ours (see OWNED_DENY_FILE
          # above).
          if added_this_run="$(json_op deny-diff "$CLAUDE_SETTINGS" "$(deny_manifest_json)")"; then
            if owned_before="$(read_owned_json "$OWNED_DENY_FILE")"; then
              new_owned="$(json_op array-union "$owned_before" "$added_this_run")"
              # Ownership record is written BEFORE settings: if this write
              # fails, settings is never touched, so there is no way to
              # end up claiming a successful apply while settings holds
              # entries the ownership record doesn't know about. The
              # reverse ordering risk — the record listing an entry not
              # yet actually present in settings, if the write below fails
              # — is the harmless direction: a later apply/uninstall
              # applying a set operation against a not-actually-present
              # value is a no-op, not a hazard.
              if json_op write-json "$OWNED_DENY_FILE" "$new_owned"; then
                did "recorded $(json_op length "$added_this_run") newly-added deny entries as Bindle-owned (for a future --uninstall)"
                if json_op merge-deny "$CLAUDE_SETTINGS" "$(deny_manifest_json)"; then
                  did "merged ${#DENY_MANIFEST[@]} guardrail deny entries into $CLAUDE_SETTINGS (existing entries untouched)"
                else
                  problem "failed to update $CLAUDE_SETTINGS while merging deny entries — $OWNED_DENY_FILE already reflects entries not yet present in settings; re-run --apply to retry"
                fi
              else
                problem "failed to update $OWNED_DENY_FILE — refusing to add deny entries to $CLAUDE_SETTINGS this run (ownership tracking would otherwise drift out of sync with what's actually installed)"
              fi
            else
              problem "$OWNED_DENY_FILE exists but could not be read as a JSON array — refusing to add deny entries to $CLAUDE_SETTINGS this run. Fix or remove it manually, then re-run --apply."
            fi
          else
            problem "failed to read $CLAUDE_SETTINGS while computing new deny entries — refusing to modify it"
          fi
        fi
      else
        if git -C "$repo_root" ls-files --error-unmatch -- "$CLAUDE_SETTINGS_RELATIVE" >/dev/null 2>&1; then
          say "  NOTE: $repo_root tracks $CLAUDE_SETTINGS_RELATIVE in Git — 'bindle init' will refuse to run until it's untracked."
        elif ! git -C "$repo_root" check-ignore -q -- "$CLAUDE_SETTINGS_RELATIVE"; then
          would "record $CLAUDE_SETTINGS_RELATIVE as ignored in $repo_common_dir/info/exclude (machine-local; not already ignored here)"
        fi
        if [ -f "$CLAUDE_GUARD_INSTALLED" ]; then
          would "update $CLAUDE_GUARD_INSTALLED and $ALLOW_MAIN_WRITE_INSTALLED (already exist)"
        else
          would "install $CLAUDE_GUARD_INSTALLED and $ALLOW_MAIN_WRITE_INSTALLED"
        fi
        if [ -f "$CLAUDE_SETTINGS" ] && pretooluse_entry_present "$CLAUDE_SETTINGS" "$PRETOOLUSE_COMMAND"; then
          say "  PreToolUse guard entry already present — no change"
        else
          would "add PreToolUse guard entry ($PRETOOLUSE_MATCHER) to $CLAUDE_SETTINGS"
        fi
        would "merge ${#DENY_MANIFEST[@]} guardrail permissions.deny entries into $CLAUDE_SETTINGS (only entries not already present)"
      fi
    fi
  fi
fi

# =============================================================================
# Post-mutation rollback: if the Git layer made a genuine new adoption/
# removal this run (GIT_LAYER_CHANGED=1) and the Claude layer then
# introduced a NEW problem (a failure preflight above could not have
# predicted — e.g. a filesystem error mid-mutation), undo exactly the Git
# layer change this invocation made, via the same idempotent functions a
# normal --apply/--uninstall uses. This is what keeps a forced Claude-layer
# failure from leaving a newly-installed (or newly-removed) Git layer
# behind. Never a generic transaction framework — narrowly scoped to the
# one cross-layer case preflight can't already rule out.
# =============================================================================
if [ "$REPO_APPLICABLE" -eq 1 ] && [ "$fail_before_claude" -eq 0 ] && [ "$fail" -ne 0 ] && [ "$GIT_LAYER_CHANGED" -eq 1 ]; then
  say ""
  say "== Rolling back the Git layer (the Claude layer failed after the Git layer had already succeeded) =="
  if [ "$MODE" = "apply" ]; then
    if git_layer_fresh_uninstall; then
      did "rolled back the Git layer to its pre-invocation state"
    else
      say "  rollback of the Git layer also failed — manual cleanup may be required (see problems above); re-run 'bindle remove' to retry"
    fi
  else
    if git_layer_fresh_install; then
      did "restored the Git layer to its pre-invocation state"
    else
      say "  rollback of the Git layer also failed — manual cleanup may be required (see problems above); re-run 'bindle init' to retry"
    fi
  fi
fi

say ""
if [ "$MODE" = "preview" ]; then
  say "Preview only — no changes made. Re-run with --apply to install, or --uninstall to remove."
fi
if [ "$fail" -ne 0 ]; then
  say "One or more problems reported above."
fi
exit "$fail"
