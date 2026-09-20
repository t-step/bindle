#!/usr/bin/env bash
#
# install-guardrails.sh — preview-first installer for Bindle's guardrail layer.
# Both halves are repo-local and opt-in, scoped to one repository (`--repo`,
# default: $PWD); a repository that never runs this (directly, or via `bindle
# init`) is unaffected:
#
#   * Git layer: a hook-composition dispatcher (protects 'main' without
#     disabling the target repository's own hooks), installed via `git config
#     --local core.hooksPath`.
#   * Claude layer: a PreToolUse guard plus permissions.deny hardening for
#     AGENTS.md's secret-file policy (D012), installed into the target
#     repository's own `.claude/settings.local.json`, never global Claude
#     config.
#
# Design history: plans/archive/2026-08-23-local-guardrail-layer.md (original,
# machine-global) and plans/active/2026-08-24-repo-local-guardrails.md
# (repo-local rework).
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
# Idempotent in both directions. Refuses to replace a pre-existing, DIFFERENT
# repo-local core.hooksPath (another hook manager: pre-commit, husky, lefthook,
# ...) rather than attempt composition. Never replaces an existing
# settings.local.json wholesale: it merges structurally via settings_json.py
# (package-owned, run under the interpreter already running Bindle, see
# BINDLE_PYTHON), touching only the array entries this installer owns. No
# external JSON tool (jq) is required.
#
# Never writes a target repository's tracked .gitignore. If
# .claude/settings.local.json isn't already ignored, the Claude layer adds a
# machine-local entry to <git-common-dir>/info/exclude (shared across linked
# worktrees like core.hooksPath, never committed). If the file is already
# tracked, the Claude layer refuses to touch it rather than rewrite team-shared
# configuration.
#
# --uninstall removes that info/exclude entry only when BOTH hold: (1) Bindle
# can positively prove it added the entry (an already-ignored repo never gets
# one, so there is nothing to claim), and (2) removal is safe:
# settings.local.json is empty once Bindle's content is detached. A
# settings.local.json still holding user content keeps both the file and its
# ignore rule, so it never becomes accidentally committable.
#
# Every --apply/--uninstall is repository-scoped: it never mutates
# machine-global Bindle state. If a RECOGNIZED pre-rework global install (Git
# core.hooksPath and/or Claude PreToolUse guard) is present, --apply/--uninstall
# refuses to run and points at --remove-legacy-global, rather than silently
# migrating (a machine-wide side effect from a repo-scoped command) or giving a
# misleading repo-local result while stale global state may still apply. An
# unrelated/foreign global value is never reported or touched.
#
# BINDLE_GUARD_HOME / BINDLE_CLAUDE_HOME only locate a pre-rework global install
# for migration; they no longer influence where anything NEW is installed
# (always repo-local). Overridable for testing (never touch live locations from
# a dev/test run, AGENTS.md "Runtime isolation"):
#   BINDLE_GUARD_HOME     default: $HOME/.local/share/bindle
#   BINDLE_CLAUDE_HOME    default: $HOME/.claude
#   BINDLE_PYTHON         interpreter for the Claude-layer JSON helper
#                         (settings_json.py). `bindle init`/`bindle remove`/
#                         `bindle migrate-legacy-global` set it to the
#                         interpreter already running Bindle; direct/test
#                         invocation falls back to `python3` on PATH.
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Standard client-side hooks (githooks(5)); excludes server/bare-repo hooks and
# Perforce (p4-*) hooks. Every name gets a passthrough symlink whether or not
# Bindle has policy for it, so repo-owned hooks are never silently disabled.
HOOK_NAMES=(
  applypatch-msg pre-applypatch post-applypatch
  pre-commit pre-merge-commit prepare-commit-msg commit-msg post-commit
  pre-rebase post-checkout post-merge pre-push
  reference-transaction push-to-checkout pre-auto-gc post-rewrite
  sendemail-validate fsmonitor-watchman post-index-change
)

# Canonical secret/credential policy (plan Decisions #5): the ONE place it is
# declared. Everything below expands it into Claude's per-tool permission rules
# (test-install-guardrails.sh proves the expansion exact); a new secret filename
# is one FILE_DENY_GLOBS line.
#
# Precise key/env path shapes: not a blanket *.pem (also a public-certificate
# format) and not id_*.pub (the public SSH half).
FILE_DENY_GLOBS=(
  ".env" ".env.local" ".env.*.local"
  "id_rsa" "id_ed25519" "id_ecdsa" "id_dsa"
  "*.pfx" "*.p12"
  "privkey.pem" "*-key.pem" "*_key.pem"
  "secrets/**"
)

# Tools that must deny every FILE_DENY_GLOBS pattern identically. Grep is
# included for AGENTS.md's "search" policy, though a directory-wide Grep merely
# CONTAINING these paths is a documented, un-closed gap (permission globs are
# path-anchored, not content-scoped).
#
# No "Write" entry: Claude Code never matches file-editing tool calls against a
# `Write(path)` rule; one `Edit(path)` rule covers
# Edit/Write/MultiEdit/NotebookEdit (the PRETOOLUSE_MATCHER set), and a
# `Write(glob)` deny is dead weight its startup diagnostics flag as "not matched
# by file permission checks".
FILE_DENY_TOOLS=(Read Edit Grep)

# Denied bare and with args: distinct shapes under Claude's Bash rule syntax.
ENV_DUMP_COMMANDS=(env printenv)

CAT_DENY_FILES=(".env" ".env.local")

# These always take arguments, so only the wildcard form is needed.
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

# True iff DIR holds the dispatcher plus a full, correctly-targeted HOOK_NAMES
# symlink set. Never trust a partial match enough to live-repair; it also proves
# a pre-existing global core.hooksPath is Bindle's own before removal.
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

# Runs settings_json.py (package-owned, jq-free) under $BINDLE_PY; mutating
# verbs write atomically and on ANY failure leave the destination untouched and
# return nonzero with nothing printed.
json_op() {
  "$BINDLE_PY" "$SCRIPT_DIR/settings_json.py" "$@"
}

# An ABSENT file is normal and echoes "[]". A PRESENT-but-broken one
# (unreadable, not a JSON array) returns nonzero with no output: callers must
# hard-stop, never substitute "[]", which under-tracks ownership and deletes the
# evidence of what to remove.
read_owned_json() {
  local file="$1"
  json_op read-array "$file"
}

pretooluse_entry_present() {
  local settings="$1" cmd="$2"
  json_op pretooluse-present "$settings" "$PRETOOLUSE_MATCHER" "$cmd"
}

if ! command -v git >/dev/null 2>&1; then
  problem "git not found on PATH"
  exit 1
fi

# Required whenever the Claude layer might run, including legacy-Claude
# detection (reached by --remove-legacy-global and every --apply/--uninstall
# gating check even under --git-only). Init/remove/migrate set BINDLE_PYTHON, so
# this fails only for direct/test invocation without python3 on PATH.
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

# Legacy (pre-rework) global-install detection and migration. Both layers once
# installed machine-globally (Git via global core.hooksPath, Claude via a
# PreToolUse entry in ~/.claude/settings.json); an opted-out repo must not
# silently fall back into either, but a repo-scoped init/remove is not the place
# for a machine-wide mutation. Two separate concerns:
#   * legacy_global_*_recognized: READ-ONLY detection; gates --apply/--uninstall
#     (refuse, don't migrate) and preview advisories.
#   * migrate_legacy_global_*: the migration itself, only from the explicit
#     --remove-legacy-global, where invoking it makes the machine-wide side
#     effect intentional.
# Both act only on state positively provable as Bindle's own
# (hooks_dir_is_intact / pretooluse_entry_present); a foreign global value is
# never reported, gated on, or touched.
#
# Read-only; on true, sets LEGACY_GIT_PATH.
legacy_global_git_recognized() {
  LEGACY_GIT_PATH="$(git config --global --get core.hooksPath 2>/dev/null || true)"
  [ -n "$LEGACY_GIT_PATH" ] && hooks_dir_is_intact "$LEGACY_GIT_PATH"
}

# Sets LEGACY_CLAUDE_SETTINGS / LEGACY_CLAUDE_COMMAND to what the pre-rework
# installer would have written; shared so detection and migration can never
# disagree about what "recognized" means.
_legacy_claude_locate() {
  local legacy_claude_home legacy_guard_home
  local legacy_guard_ref legacy_helper_ref

  legacy_claude_home="${BINDLE_CLAUDE_HOME:-$HOME/.claude}"
  legacy_guard_home="${BINDLE_GUARD_HOME:-$HOME/.local/share/bindle}"
  LEGACY_CLAUDE_SETTINGS="$legacy_claude_home/settings.json"

  # The literal '~/...' is deliberate (SC2088): it matches what the pre-rework
  # installer wrote, for Claude Code's own shell to expand.
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

# Read-only: an absent file, invalid JSON, or a non-matching entry is simply
# "not recognized" (reporting is migrate_legacy_global_claude's job).
legacy_global_claude_recognized() {
  _legacy_claude_locate
  [ -f "$LEGACY_CLAUDE_SETTINGS" ] || return 1
  json_op valid-json "$LEGACY_CLAUDE_SETTINGS" || return 1
  pretooluse_entry_present "$LEGACY_CLAUDE_SETTINGS" "$LEGACY_CLAUDE_COMMAND"
}

# Only called from --remove-legacy-global, so it reports everything it finds,
# including an absent or foreign value: the caller asked to migrate and deserves
# to know why nothing happened.
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

# Repository identity is the Git common directory (D018), resolved once here for
# both layers. Claude Code resolves a repo's settings "through worktrees to the
# main checkout", so repo_root (that main checkout, NOT necessarily
# $REPO_TARGET's worktree) is what it actually reads.
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

# Anchored under the repo's Git common dir: untracked, shared across linked
# worktrees (docs/WORKTREES.md), and unambiguous where a relative core.hooksPath
# would resolve against a worktree's private git-dir.
HOOKS_DIR="$repo_common_dir/bindle-hooks"

# SEPARATE from HOOKS_DIR (also in .git, shared across worktrees) so the layers
# stay independent: either can be applied/removed via --git-only/--claude-only
# without its staging logic seeing a directory the other layer partially
# populated.
CLAUDE_DIR="$repo_common_dir/bindle-claude"
CLAUDE_GUARD_INSTALLED="$CLAUDE_DIR/claude-protected-main-guard"
ALLOW_MAIN_WRITE_INSTALLED="$CLAUDE_DIR/allow-main-write.sh"

# Sibling FILE, not inside CLAUDE_DIR: it must stay reachable when guard/helper
# installation fails (permissions.deny hardening is independent on purpose; see
# the "incomplete Claude guard/helper installation" test).
OWNED_DENY_FILE="$repo_common_dir/bindle-claude-deny-owned.json"

# Main checkout's tree per Claude Code's settings resolution, not $REPO_TARGET.
CLAUDE_SETTINGS_RELATIVE=".claude/settings.local.json"
CLAUDE_SETTINGS="$repo_root/$CLAUDE_SETTINGS_RELATIVE"

# Ownership marker (sibling of OWNED_DENY_FILE): present iff Bindle itself
# appended the info/exclude line (see ensure_repo_settings_ignored). Its ABSENCE
# keeps an already-ignored repo safe from --uninstall touching that line: Bindle
# never claims an ignore rule it did not add.
CLAUDE_EXCLUDE_OWNED_FILE="$repo_common_dir/bindle-claude-exclude-owned"

# If $CLAUDE_SETTINGS_RELATIVE isn't already ignored (own .gitignore, global
# gitignore, or a prior run), appends a machine-local rule to
# <git-common-dir>/info/exclude; never touches the tracked .gitignore or appends
# a duplicate. Apply path only, after the preflight tracked-file check.
#
# CLAUDE_EXCLUDE_OWNED_FILE is written ONLY on the genuine first-append path:
# not when check-ignore already reports the path ignored (another source owns
# that), nor on the defensive dedup branch (a present line wasn't necessarily
# ours). This is the single place ownership can be claimed, so --uninstall can
# never be wrong about it.
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

# Removes the info/exclude entry only when CLAUDE_EXCLUDE_OWNED_FILE proves
# Bindle added it; a missing marker (entry predates Bindle, came from
# .gitignore, or never existed) is a no-op. Guards ownership only, not safety:
# callers must already have established that settings.local.json is gone.
#
# The marker is cleared after this function's one attempt even if no line
# matched; a surviving marker would be permanently stale.
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
    # grep -v exits 1 (not an error) when every line was filtered out, i.e. our
    # entry was the only line; only exit 2 is a real failure.
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

# Absolute paths only: both live inside .git, so no "~/..." shorthand applies.
PRETOOLUSE_COMMAND="$CLAUDE_GUARD_INSTALLED $ALLOW_MAIN_WRITE_INSTALLED"

# --status (read-only, drives `bindle status`): reports installed /
# not-installed / partial / conflict / invalid per layer using the SAME
# ownership/intactness predicates as preflight and apply/uninstall
# (hooks_dir_is_intact, pretooluse_entry_present, valid-json, read_owned_json,
# the tracked-file check), not a parallel reimplementation, so it cannot drift
# from what init/remove enforce. Never runs preflight, never reports
# legacy-global state (scoped to THIS repo), never mutates, not even the narrow
# live repairs --apply makes.
#
# core.hooksPath is a single-value integration point, so state collapses onto
# four of the five states. No detectable "invalid": hooks_dir_is_intact checks
# only the dispatcher's executable bit and symlink target names, never its
# content, so a content-corrupted dispatcher looks intact and anything failing
# the shape check is already "partial".
detect_git_status() {
  local hookspath dir_exists=0 dir_intact=0
  hookspath="$(git -C "$REPO_TARGET" config --local --get core.hooksPath 2>/dev/null || true)"
  [ -e "$HOOKS_DIR" ] && dir_exists=1
  hooks_dir_is_intact "$HOOKS_DIR" && dir_intact=1

  if [ -n "$hookspath" ] && [ "$hookspath" != "$HOOKS_DIR" ]; then
    # Foreign core.hooksPath (another hook manager): apply refuses it too.
    echo "conflict"
  elif [ -z "$hookspath" ] && [ "$dir_exists" -eq 0 ]; then
    echo "not-installed"
  elif [ "$hookspath" = "$HOOKS_DIR" ] && [ "$dir_intact" -eq 1 ]; then
    echo "installed"
  else
    # Bindle-recognizable (hookspath at $HOOKS_DIR, or $HOOKS_DIR exists) but
    # the halves disagree: dispatcher/symlinks missing or broken, or the
    # directory not yet wired into core.hooksPath.
    echo "partial"
  fi
}

# Claude Code's hooks.PreToolUse array is additive/multi-owner, so another tool
# holding the same matcher is not a conflict. The one single-owner point Bindle
# claims is the settings.local.json FILE itself; a tracked, team-owned copy
# (which install refuses to touch) counts as "occupied by something not
# Bindle-owned", i.e. conflict.
#
# "Bindle evidence" is restricted to exclusively-Bindle paths/markers
# (guard/helper under bindle-claude/, the owned-deny file, the info/exclude
# marker) plus a PreToolUse entry naming those paths; never mere existence of
# settings.local.json, which is Claude Code's own file and may hold unrelated
# content (else any repo using it for something else would misreport as
# "partial").
#
# "installed" requires OWNED_DENY_FILE unconditionally: remove reads it to know
# which deny entries it may remove, so its absence loses that information.
# CLAUDE_EXCLUDE_OWNED_FILE is conditional: it exists only when Bindle claimed
# the info/exclude line (never for an already-ignored repo, which is a normal
# complete install), but once it exists "installed" also requires the line it
# names to still be present, since the marker asserts remove may delete it.
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

  # True unless the marker claims an info/exclude line that is no longer there
  # (the check remove_owned_exclude_entry makes); vacuously true without the
  # marker.
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

  # A broken owned-deny file is always Bindle's own artifact: its presence,
  # valid or not, IS the ownership evidence.
  if [ "$owned_deny_exists" -eq 1 ] && [ "$owned_deny_valid" -eq 0 ]; then
    echo "invalid"
    return
  fi
  # An unreadable settings.local.json is Bindle's "invalid" only when another
  # exclusively-Bindle artifact proves Bindle was involved.
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

# Preflight (--apply/--uninstall only): validate BOTH requested layers before
# mutating either, so on ANY problem nothing is mutated and init/remove can
# never leave one layer installed/removed without the other. Preview never
# mutates and runs its own inline checks.
#
# Deliberately non-exhaustive: covers what is knowable without mutating
# (legacy-global recognition, a foreign core.hooksPath, a corrupted local
# hook/settings file). Failures possible only DURING mutation (disk full,
# concurrent permission change) are handled narrowly by the post-mutation
# rollback below.
if [ "$REPO_APPLICABLE" -eq 1 ] && { [ "$MODE" = "apply" ] || [ "$MODE" = "uninstall" ]; }; then
  say "== Preflight =="

  # A recognized pre-rework global install must never be silently touched by a
  # repo-scoped invocation; the explicit migration (--remove-legacy-global /
  # `bindle migrate-legacy-global`) is what makes the machine-wide side effect
  # intentional.
  if [ "$CLAUDE_ONLY" -eq 0 ] && legacy_global_git_recognized; then
    problem "a recognized legacy machine-global Bindle Git guardrail is still installed (global core.hooksPath: $LEGACY_GIT_PATH). 'bindle init'/'bindle remove' are repository-scoped and refuse to silently migrate or remove machine-global state. Run the explicit migration first — 'bindle migrate-legacy-global' (or 'install-guardrails.sh --remove-legacy-global') — then retry."
  fi
  if [ "$GIT_ONLY" -eq 0 ] && legacy_global_claude_recognized; then
    problem "a recognized legacy machine-global Bindle Claude Code guard entry is still installed in $LEGACY_CLAUDE_SETTINGS. 'bindle init'/'bindle remove' are repository-scoped and refuse to silently migrate or remove machine-global state. Run the explicit migration first — 'bindle migrate-legacy-global' (or 'install-guardrails.sh --remove-legacy-global') — then retry."
  fi

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

# Deny manifest expansion: canonical policy above -> Claude's individual
# permissions.deny strings; nothing below encodes policy.
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

deny_manifest_json() {
  printf '%s\n' "${DENY_MANIFEST[@]}" | json_op lines-to-json-array
}

# Set to 1 only by a genuine cross-invocation transition (fresh install or
# opt-out), never by a redundant re-apply/re-uninstall; decides whether a later
# Claude-layer failure in THIS invocation must roll the Git layer back.
GIT_LAYER_CHANGED=0

# A function so a failed Claude layer can roll --uninstall back to its
# pre-invocation state. Reports its own problem() and sets GIT_LAYER_CHANGED=1
# on a genuine fresh install.
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

# Unsets core.hooksPath only if it points at Bindle's own $HOOKS_DIR, then
# removes $HOOKS_DIR. A function so a failed Claude layer can roll --apply back.
# Reports its own problem() and sets GIT_LAYER_CHANGED=1 on a genuine removal.
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
          # No dispatcher yet, so core.hooksPath is unset or points at nothing
          # and no concurrent Git operation can be reading this path.
          git_layer_fresh_install
        else
          # Re-apply to an existing $HOOKS_DIR: NEVER replace the directory.
          # Moving it aside and a replacement in is two renames, not atomic as a
          # PAIR: between them core.hooksPath points nowhere and a concurrent
          # Git operation silently finds no hooks. Instead verify the install is
          # intact, then replace ONLY the dispatcher via a same-directory temp
          # file and one atomic rename; every symlink names that literal
          # filename, so Git sees the complete old or complete new dispatcher. A
          # re-apply, not a fresh adoption: GIT_LAYER_CHANGED deliberately stays
          # 0 (nothing for a cross-layer rollback to undo).
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

# $fail as of the end of the Git layer; compared after the Claude layer to
# detect a NEW Claude-layer problem, the only case where a completed Git-layer
# transition needs rolling back.
fail_before_claude="$fail"

if [ "$GIT_ONLY" -eq 0 ]; then
  say ""
  say "== Claude Code layer =="
  if [ "$MODE" = "preview" ] && legacy_global_claude_recognized; then
    say "  NOTE: a recognized legacy global Claude Code guard entry exists in $LEGACY_CLAUDE_SETTINGS — 'bindle init'/'bindle remove' will refuse to run until it is migrated away explicitly ('bindle migrate-legacy-global' / install-guardrails.sh --remove-legacy-global)."
  fi

  if [ "$REPO_APPLICABLE" -eq 1 ]; then
    if [ "$MODE" = "uninstall" ]; then
      # Detach config BEFORE removing the files it references: deleting
      # guard/helper first would leave an active hook registration pointing at
      # nothing. pretooluse_detached reaches 1 only once the entry is confirmed
      # gone (or no settings file existed); the files are removed strictly
      # after.
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

          # permissions.deny/ownership cleanup is a separate config surface,
          # handled independently of the detach outcome above.
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

          # Ask whether the file is empty only once EVERYTHING Bindle owns was
          # cleanly detached (a partially-detached file must not be judged
          # empty). Content left by the user or another tool (settings_json.py
          # doc-is-empty) keeps the file and its ignore rule untouched, never
          # made accidentally committable.
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
      # rmdir, never rm -rf: leftovers from a partial failure must survive.
      rmdir "$CLAUDE_DIR" 2>/dev/null || true
    else
      if [ "$MODE" = "apply" ]; then
        # Guard and helper scripts must be on disk BEFORE the PreToolUse entry
        # naming them is registered. claude_files_ready gates only that
        # registration, not the independent permissions.deny hardening.
        claude_files_ready=1
        if ! mkdir -p "$CLAUDE_DIR" "$(dirname "$CLAUDE_SETTINGS")" 2>/dev/null; then
          problem "failed to create $CLAUDE_DIR or $(dirname "$CLAUDE_SETTINGS")"
          claude_files_ready=0
        else
          # $CLAUDE_GUARD_INSTALLED is the path an already-registered PreToolUse
          # entry names and may be live on a re-apply, so it is staged like the
          # Git dispatcher (same-dir temp file, verified, atomic rename) to
          # never leave a truncated file where an active hook looks.
          #
          # $ALLOW_MAIN_WRITE_INSTALLED needs no such staging: the guard uses
          # that path only as a STRING in its deny message and never executes
          # it, so a corrupted helper only fails a later explicit command
          # cleanly.
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

          # Compute the genuinely NEW manifest entries BEFORE mutating, so a
          # byte-identical pre-existing entry (the user's or another tool's) is
          # never recorded as ours (see OWNED_DENY_FILE).
          if added_this_run="$(json_op deny-diff "$CLAUDE_SETTINGS" "$(deny_manifest_json)")"; then
            if owned_before="$(read_owned_json "$OWNED_DENY_FILE")"; then
              new_owned="$(json_op array-union "$owned_before" "$added_this_run")"
              # Record written BEFORE settings: if this write fails settings is
              # untouched, so a successful apply never leaves entries the record
              # doesn't know about. The reverse risk (record lists an entry not
              # yet in settings if the write below fails) is harmless: a later
              # set operation on an absent value is a no-op.
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

# Post-mutation rollback: if the Git layer made a genuine adoption/removal this
# run (GIT_LAYER_CHANGED=1) and the Claude layer then introduced a NEW problem
# preflight could not predict (e.g. a mid-mutation filesystem error), undo
# exactly that Git change via the same idempotent functions. Narrowly scoped to
# that one cross-layer case, not a transaction framework.
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
