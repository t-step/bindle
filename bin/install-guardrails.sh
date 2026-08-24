#!/usr/bin/env bash
#
# install-guardrails.sh — preview-first installer for Bindle's local
# guardrail layer: a global Git hook composition layer that protects the
# 'main' branch across every repository on this machine without disabling
# any repository's own hooks, a matching user-level Claude Code PreToolUse
# guard, and permissions.deny hardening for AGENTS.md's existing secret-file
# policy (D012). See plans/archive/2026-08-23-local-guardrail-layer.md.
#
# Usage:
#   bin/install-guardrails.sh              # preview only (default, no writes)
#   bin/install-guardrails.sh --apply      # perform the writes
#   bin/install-guardrails.sh --uninstall  # remove only what this installer
#                                          # can positively identify as its own
#
# Idempotent in both directions. Refuses to replace a pre-existing, DIFFERENT
# global core.hooksPath rather than attempting arbitrary composition with an
# unknown existing hook manager. Never replaces ~/.claude/settings.json
# wholesale — merges into it structurally via jq, touching only the specific
# array entries this installer owns.
#
# Overridable for testing (never touch live locations from a dev/test run —
# AGENTS.md "Runtime isolation"):
#   BINDLE_GUARD_HOME     default: $HOME/.local/share/bindle
#   BINDLE_CLAUDE_HOME    default: $HOME/.claude
#
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

GUARD_HOME="${BINDLE_GUARD_HOME:-$HOME/.local/share/bindle}"
CLAUDE_HOME="${BINDLE_CLAUDE_HOME:-$HOME/.claude}"

HOOKS_DIR="$GUARD_HOME/git-hooks"
GUARD_BIN_DIR="$GUARD_HOME/bin"
ALLOW_MAIN_WRITE_INSTALLED="$GUARD_BIN_DIR/allow-main-write.sh"

CLAUDE_HOOKS_DIR="$CLAUDE_HOME/hooks"
CLAUDE_GUARD_INSTALLED="$CLAUDE_HOOKS_DIR/bindle-protected-main-guard"
CLAUDE_SETTINGS="$CLAUDE_HOME/settings.json"

# Ownership record for permissions.deny: settings.json's array is flat
# strings with no per-entry provenance, so a byte-identical entry that
# already existed before Bindle ever ran is indistinguishable from one
# Bindle generated, purely by looking at the array. This file is the
# smallest mechanism that resolves that: on --apply, only entries that were
# NOT already present get unioned into it; on --uninstall, only entries
# recorded here are removed — never the full generated manifest — so a
# pre-existing overlapping rule is never touched.
OWNED_DENY_FILE="$GUARD_HOME/claude-deny-owned.json"

# Standard client-side Git hooks (githooks(5)), excluding server/bare-repo-
# only hooks (pre-receive, update, proc-receive, post-receive, post-update)
# and Perforce-bridge hooks (p4-*), which don't apply to a developer's own
# checkout. Every name here gets a passthrough symlink regardless of whether
# Bindle has policy for it (bin/git-hook-dispatch.sh decides that itself) —
# this is what keeps repository-owned hooks from being silently disabled.
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
# strings (bin/test-install-guardrails.sh proves the expansion is exact) —
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
case "${1:-}" in
--apply) MODE="apply" ;;
--uninstall) MODE="uninstall" ;;
"") MODE="preview" ;;
*)
  echo "usage: $0 [--apply|--uninstall]" >&2
  exit 2
  ;;
esac

fail=0
say() { printf '%s\n' "$1"; }
would() { printf '  [preview] %s\n' "$1"; }
did() { printf '  ✓ %s\n' "$1"; }
problem() {
  printf '  ✗ %s\n' "$1"
  fail=1
}

if ! command -v git >/dev/null 2>&1; then
  problem "git not found on PATH"
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  problem "jq not found on PATH — required for the Claude-layer settings.json merge"
  if [ "$MODE" != "preview" ]; then
    exit 1
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

# JSON array of the deny manifest, for jq --argjson.
deny_manifest_json() {
  printf '%s\n' "${DENY_MANIFEST[@]}" | jq -R . | jq -s .
}

# read_owned_deny_json — echoes the persisted "entries Bindle actually
# added" set and returns 0. An ABSENT record is a normal, expected state
# (nothing tracked yet) and echoes "[]". A PRESENT-but-broken record
# (unreadable, or not a JSON array) returns nonzero and echoes nothing —
# callers must treat that as a hard stop, never silently substitute "[]",
# since doing so both under-tracks ownership and would let the caller go
# on to delete the only evidence of what should have been removed.
read_owned_deny_json() {
  [ -f "$OWNED_DENY_FILE" ] || {
    echo "[]"
    return 0
  }
  local content
  content="$(cat "$OWNED_DENY_FILE" 2>/dev/null)" || return 1
  jq -e 'type == "array"' >/dev/null 2>&1 <<<"$content" || return 1
  printf '%s' "$content"
}

# jq_atomic_write DEST JQ_ARGS... — runs `jq "$@"`, capturing stdout into a
# temp file in DEST's own directory (so the final rename is a same-
# filesystem, atomic `mv`, matching bin/allow-main-write.sh's token write),
# then replaces DEST with it. On ANY failure — jq itself, the temp file
# write, or the rename — DEST is left completely untouched, the temp file
# is cleaned up, and this returns nonzero with nothing printed. Callers
# decide how to report; this never prints a success marker on failure and
# never partially overwrites DEST.
jq_atomic_write() {
  local dest="$1"
  shift
  local dest_dir tmp
  dest_dir="$(dirname -- "$dest")"
  tmp="$(mktemp "$dest_dir/.bindle-jqtmp.XXXXXX" 2>/dev/null)" || return 1
  if ! jq "$@" >"$tmp" 2>/dev/null; then
    rm -f "$tmp"
    return 1
  fi
  if ! jq -e . "$tmp" >/dev/null 2>&1; then
    rm -f "$tmp"
    return 1
  fi
  mv "$tmp" "$dest" 2>/dev/null || {
    rm -f "$tmp"
    return 1
  }
}

# --- helper: is a given hook-group entry already present in settings.json --
pretooluse_entry_present() {
  local cmd="$1"
  jq -e --arg matcher "$PRETOOLUSE_MATCHER" --arg cmd "$cmd" \
    '(.hooks.PreToolUse // []) | any(.matcher == $matcher and ((.hooks // []) | any(.command == $cmd)))' \
    "$CLAUDE_SETTINGS" >/dev/null 2>&1
}

# These deliberately print a literal '~/...' string for settings.json's
# "command" field, matching the ~-form every existing hook entry in that
# file already uses (Claude Code's own shell expands it at run time) — not
# a tilde this script's own shell should expand.
# shellcheck disable=SC2088
helper_ref() {
  if [ "$GUARD_HOME" = "$HOME/.local/share/bindle" ]; then
    printf '~/.local/share/bindle/bin/allow-main-write.sh'
  else
    printf '%s' "$ALLOW_MAIN_WRITE_INSTALLED"
  fi
}
# shellcheck disable=SC2088
guard_ref() {
  if [ "$CLAUDE_HOME" = "$HOME/.claude" ]; then
    printf '~/.claude/hooks/bindle-protected-main-guard'
  else
    printf '%s' "$CLAUDE_GUARD_INSTALLED"
  fi
}
PRETOOLUSE_COMMAND="$(guard_ref) $(helper_ref)"

# =============================================================================
# Git layer
# =============================================================================
say "== Git hook layer =="

existing_hookspath="$(git config --global --get core.hooksPath 2>/dev/null || true)"
GIT_LAYER_BLOCKED=0
if [ -n "$existing_hookspath" ] && [ "$existing_hookspath" != "$HOOKS_DIR" ]; then
  problem "global core.hooksPath is already set to '$existing_hookspath' (not Bindle's). Refusing to replace it — remove or reconcile that configuration yourself first if you want Bindle's guardrails installed globally."
  GIT_LAYER_BLOCKED=1
fi

if [ "$MODE" = "uninstall" ]; then
  if [ "$existing_hookspath" = "$HOOKS_DIR" ]; then
    say "  removing global core.hooksPath ($HOOKS_DIR)"
    if git config --global --unset core.hooksPath 2>/dev/null &&
      ! git config --global --get core.hooksPath >/dev/null 2>&1; then
      did "core.hooksPath unset"
    else
      problem "failed to unset global core.hooksPath"
    fi
  else
    say "  global core.hooksPath does not point at Bindle — leaving it untouched"
  fi
  if [ -d "$HOOKS_DIR" ]; then
    if rm -rf "$HOOKS_DIR" 2>/dev/null && [ ! -e "$HOOKS_DIR" ]; then
      did "removed $HOOKS_DIR"
    else
      problem "failed to remove $HOOKS_DIR"
    fi
  else
    say "  $HOOKS_DIR already absent"
  fi
elif [ "$GIT_LAYER_BLOCKED" -eq 0 ]; then
  if [ "$MODE" = "apply" ]; then
    git_layer_ready=1
    if [ ! -e "$HOOKS_DIR" ]; then
      # First install (or a previously-deleted installation): nothing is
      # live yet, so core.hooksPath either isn't set or points at nothing
      # — no concurrent Git operation can be reading this path. Build the
      # complete dispatcher + full symlink set off to the side, verify
      # it, then move it into place with a single atomic rename, and only
      # THEN set core.hooksPath.
      staging_dir=""
      if ! mkdir -p "$GUARD_HOME" 2>/dev/null; then
        problem "failed to create $GUARD_HOME"
        git_layer_ready=0
      else
        staging_dir="$(mktemp -d "$GUARD_HOME/.git-hooks.staging.XXXXXX" 2>/dev/null)"
        if [ -z "$staging_dir" ]; then
          problem "failed to create a staging directory under $GUARD_HOME"
          git_layer_ready=0
        fi
      fi

      if [ "$git_layer_ready" -eq 1 ] &&
        ! install -m 0755 "$REPO_ROOT/bin/git-hook-dispatch.sh" "$staging_dir/.bindle-git-hook-dispatch" 2>/dev/null; then
        problem "failed to stage the dispatcher"
        git_layer_ready=0
      fi

      if [ "$git_layer_ready" -eq 1 ]; then
        symlinks_failed=0
        for name in "${HOOK_NAMES[@]}"; do
          ln -sf ".bindle-git-hook-dispatch" "$staging_dir/$name" 2>/dev/null || symlinks_failed=1
        done
        if [ "$symlinks_failed" -eq 1 ]; then
          problem "failed to stage one or more standard hook symlinks"
          git_layer_ready=0
        fi
      fi

      # Verify every required artifact actually landed in staging before
      # trusting it enough to move into place — a staging directory that
      # merely exists is not the same as one that's complete.
      if [ "$git_layer_ready" -eq 1 ] && [ ! -x "$staging_dir/.bindle-git-hook-dispatch" ]; then
        problem "staged dispatcher is missing or not executable"
        git_layer_ready=0
      fi
      if [ "$git_layer_ready" -eq 1 ]; then
        missing_symlink=0
        for name in "${HOOK_NAMES[@]}"; do
          [ -L "$staging_dir/$name" ] || missing_symlink=1
        done
        if [ "$missing_symlink" -eq 1 ]; then
          problem "one or more staged hook symlinks are missing"
          git_layer_ready=0
        fi
      fi

      if [ "$git_layer_ready" -eq 0 ]; then
        [ -n "$staging_dir" ] && rm -rf "$staging_dir" 2>/dev/null
        problem "staging the Git hook directory failed — leaving core.hooksPath unchanged (never activating an incomplete Git layer)"
      elif mv "$staging_dir" "$HOOKS_DIR" 2>/dev/null; then
        did "installed dispatcher + ${#HOOK_NAMES[@]} standard hook symlinks at $HOOKS_DIR"
      else
        problem "failed to move the staged Git hook directory into place at $HOOKS_DIR"
        rm -rf "$staging_dir" 2>/dev/null
        git_layer_ready=0
      fi
    else
      # Re-apply to an already-existing $HOOKS_DIR: NEVER replace the
      # directory itself. Two renames (move the live directory aside,
      # move a replacement into its place) are not atomic as a PAIR —
      # between them core.hooksPath would point at a path that doesn't
      # exist, and a concurrent Git operation would silently find no
      # hooks at all, skipping this layer entirely. Instead: verify the
      # existing installation is exactly what Bindle would have
      # installed (dispatcher present and executable, every symlink
      # present and correctly targeting it), then replace ONLY the
      # dispatcher file via a same-directory temp file and a single
      # atomic rename over .bindle-git-hook-dispatch. Every symlink
      # already points at that literal filename and is never touched —
      # Git always resolves either the complete old dispatcher or the
      # complete new one, never a missing hook directory.
      if [ ! -x "$HOOKS_DIR/.bindle-git-hook-dispatch" ]; then
        problem "the active $HOOKS_DIR is missing its dispatcher, or it isn't executable — refusing to repair it live. Remove $HOOKS_DIR manually (or run --uninstall) and re-run --apply for a clean install."
        git_layer_ready=0
      else
        unexpected_symlink=0
        for name in "${HOOK_NAMES[@]}"; do
          if [ ! -L "$HOOKS_DIR/$name" ] || [ "$(readlink "$HOOKS_DIR/$name")" != ".bindle-git-hook-dispatch" ]; then
            unexpected_symlink=1
          fi
        done
        if [ "$unexpected_symlink" -eq 1 ]; then
          problem "the active $HOOKS_DIR has a missing or unexpected hook symlink — refusing to repair it live. Remove $HOOKS_DIR manually (or run --uninstall) and re-run --apply for a clean install."
          git_layer_ready=0
        fi
      fi

      if [ "$git_layer_ready" -eq 1 ]; then
        staging_dispatch="$HOOKS_DIR/.bindle-git-hook-dispatch.new.$$"
        if ! install -m 0755 "$REPO_ROOT/bin/git-hook-dispatch.sh" "$staging_dispatch" 2>/dev/null; then
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
    fi

    if [ "$git_layer_ready" -eq 1 ]; then
      if [ -z "$existing_hookspath" ]; then
        if git config --global core.hooksPath "$HOOKS_DIR" 2>/dev/null &&
          [ "$(git config --global --get core.hooksPath 2>/dev/null)" = "$HOOKS_DIR" ]; then
          did "set global core.hooksPath to $HOOKS_DIR"
        else
          problem "failed to set global core.hooksPath to $HOOKS_DIR"
        fi
      else
        say "  global core.hooksPath already set to $HOOKS_DIR — unchanged"
      fi
    fi
  else
    if [ -d "$HOOKS_DIR" ]; then
      would "update dispatcher + ${#HOOK_NAMES[@]} symlinks in $HOOKS_DIR (already exists)"
    else
      would "create $HOOKS_DIR with dispatcher + ${#HOOK_NAMES[@]} symlinks"
    fi
    if [ -z "$existing_hookspath" ]; then
      would "set global core.hooksPath to $HOOKS_DIR"
    else
      say "  global core.hooksPath already set to $HOOKS_DIR — no change needed"
    fi
  fi
fi

# =============================================================================
# Claude layer: PreToolUse guard + allow-main-write helper
# =============================================================================
say ""
say "== Claude Code layer (user-level: $CLAUDE_HOME) =="

if [ "$MODE" = "uninstall" ]; then
  # Config must be detached BEFORE the files it references are removed: if
  # settings.json's PreToolUse entry still names bindle-protected-main-guard
  # / allow-main-write.sh and those files were deleted first, Claude Code
  # would be left with an active hook registration pointing at nothing.
  # pretooluse_detached only reaches 1 once that entry is confirmed gone (or
  # there was never a settings.json to hold one) — the guard/helper files
  # are removed strictly after, and only then.
  pretooluse_detached=1
  if [ -f "$CLAUDE_SETTINGS" ]; then
    if ! jq -e . "$CLAUDE_SETTINGS" >/dev/null 2>&1; then
      problem "$CLAUDE_SETTINGS exists but is not valid JSON — refusing to modify hooks/permissions.deny in it, and preserving the installed guard/helper files since the registration referencing them can't be safely detached. Fix or restore it manually, then re-run --uninstall."
      pretooluse_detached=0
    else
      # shellcheck disable=SC2016 # single-quoted jq filter, not shell expansion
      if jq_atomic_write "$CLAUDE_SETTINGS" --arg matcher "$PRETOOLUSE_MATCHER" --arg cmd "$PRETOOLUSE_COMMAND" \
        '.hooks.PreToolUse = ((.hooks.PreToolUse // []) | map(select(
           (.matcher == $matcher and ((.hooks // []) | any(.command == $cmd))) | not
         )))' \
        "$CLAUDE_SETTINGS"; then
        did "removed the PreToolUse guard entry from $CLAUDE_SETTINGS"
      else
        problem "failed to update $CLAUDE_SETTINGS while removing the PreToolUse guard entry — preserving the installed guard/helper files since the registration referencing them is still active"
        pretooluse_detached=0
      fi

      # permissions.deny / ownership cleanup is a different config surface
      # (unrelated to the PreToolUse entry or the guard/helper files) and
      # stays independently handled regardless of the detach outcome above.
      #
      # The owned-set read gates whether deny removal proceeds AT ALL: a
      # present-but-broken OWNED_DENY_FILE must never be silently treated
      # as "[]" (that would both remove nothing this run — under-tracking
      # — and, if we then deleted the file unconditionally, destroy the
      # only record of what still needs removing).
      if owned_deny_json="$(read_owned_deny_json)"; then
        # shellcheck disable=SC2016 # single-quoted jq filter, not shell expansion
        if jq_atomic_write "$CLAUDE_SETTINGS" --argjson remove "$owned_deny_json" \
          '.permissions.deny = ((.permissions.deny // []) - $remove)' \
          "$CLAUDE_SETTINGS"; then
          did "removed $(jq 'length' <<<"$owned_deny_json") guardrail deny entries from $CLAUDE_SETTINGS (never a pre-existing entry that happened to match)"
          rm -f "$OWNED_DENY_FILE"
        else
          problem "failed to update $CLAUDE_SETTINGS while removing owned deny entries — preserving $OWNED_DENY_FILE so this can be retried"
        fi
      else
        problem "$OWNED_DENY_FILE exists but could not be read as a JSON array — refusing to remove guardrail deny entries from $CLAUDE_SETTINGS. Preserving the file rather than treating it as empty and deleting the evidence — fix or restore it manually, then re-run --uninstall."
      fi
    fi
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
else
  if [ "$MODE" = "apply" ]; then
    # The guard and helper scripts must be on disk BEFORE the PreToolUse
    # entry naming them is ever registered — registering a hook whose
    # command points at a file that isn't actually there would activate a
    # Claude-layer guard with a missing artifact. claude_files_ready gates
    # that registration below; it does NOT gate the permissions.deny
    # hardening, which is independent settings.json content unrelated to
    # whether these two script files exist.
    claude_files_ready=1
    if ! mkdir -p "$CLAUDE_HOOKS_DIR" "$GUARD_BIN_DIR" 2>/dev/null; then
      problem "failed to create $CLAUDE_HOOKS_DIR or $GUARD_BIN_DIR"
      claude_files_ready=0
    else
      # $CLAUDE_GUARD_INSTALLED is the exact path an already-registered
      # PreToolUse entry's "command" names — on a re-apply, that entry can
      # already be active and resolving to whatever is currently at this
      # path. Staged the same way as the Git dispatcher above (temp file
      # in the same directory, verified, then an atomic same-filesystem
      # rename into place) so a failure partway through never leaves a
      # truncated/partial file where an active hook is looking for it.
      #
      # $ALLOW_MAIN_WRITE_INSTALLED does NOT need the same treatment: the
      # guard script only ever uses that path as a STRING in its deny
      # message (see bin/claude-protected-main-guard.sh) — it never
      # executes it, so nothing about hook resolution depends on its
      # content. A corrupted helper script would only cause a later,
      # separate, explicitly-invoked command to fail cleanly (a normal
      # nonzero exit), not silently break the already-active hook.
      staging_guard="$CLAUDE_HOOKS_DIR/.bindle-protected-main-guard.staging.$$"
      if ! install -m 0755 "$REPO_ROOT/bin/claude-protected-main-guard.sh" "$staging_guard" 2>/dev/null; then
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
      elif ! install -m 0755 "$REPO_ROOT/bin/allow-main-write.sh" "$ALLOW_MAIN_WRITE_INSTALLED" 2>/dev/null; then
        problem "failed to install $ALLOW_MAIN_WRITE_INSTALLED"
        claude_files_ready=0
      else
        did "installed $CLAUDE_GUARD_INSTALLED and $ALLOW_MAIN_WRITE_INSTALLED"
      fi
    fi

    claude_settings_ready=1
    if [ -f "$CLAUDE_SETTINGS" ]; then
      if ! jq -e . "$CLAUDE_SETTINGS" >/dev/null 2>&1; then
        problem "$CLAUDE_SETTINGS exists but is not valid JSON — refusing to modify hooks/permissions.deny in it. Fix or restore it manually, then re-run --apply."
        claude_settings_ready=0
      fi
    elif ! echo '{}' >"$CLAUDE_SETTINGS" 2>/dev/null; then
      problem "failed to create $CLAUDE_SETTINGS"
      claude_settings_ready=0
    fi

    if [ "$claude_settings_ready" -eq 1 ]; then
      if [ "$claude_files_ready" -eq 0 ]; then
        problem "guard/helper installation failed — refusing to register the PreToolUse hook entry (never activating a layer with missing artifacts)"
      elif pretooluse_entry_present "$PRETOOLUSE_COMMAND"; then
        say "  PreToolUse guard entry already present — unchanged"
      else
        # shellcheck disable=SC2016 # single-quoted jq filter, not shell expansion
        if jq_atomic_write "$CLAUDE_SETTINGS" --arg matcher "$PRETOOLUSE_MATCHER" --arg cmd "$PRETOOLUSE_COMMAND" \
          '.hooks = (.hooks // {}) |
           .hooks.PreToolUse = ((.hooks.PreToolUse // []) + [
             {matcher: $matcher, hooks: [{type: "command", command: $cmd, timeout: 5}]}
           ])' \
          "$CLAUDE_SETTINGS"; then
          did "added PreToolUse guard entry ($PRETOOLUSE_MATCHER) to $CLAUDE_SETTINGS"
        else
          problem "failed to update $CLAUDE_SETTINGS while adding the PreToolUse guard entry"
        fi
      fi

      # Determine which manifest entries are genuinely NEW here — not
      # already present before this merge — BEFORE mutating anything, so a
      # byte-identical pre-existing entry (from the user, or from any
      # other tool) is never recorded as ours (see OWNED_DENY_FILE above).
      if added_this_run="$(jq --argjson new "$(deny_manifest_json)" \
        '(.permissions.deny // []) as $existing | ($new - $existing)' \
        "$CLAUDE_SETTINGS")"; then
        if owned_before="$(read_owned_deny_json)"; then
          new_owned="$(jq -n --argjson existing "$owned_before" --argjson added "$added_this_run" \
            '($existing + $added) | unique')"
          # Ownership record is written BEFORE settings.json: if this
          # write fails, settings.json is never touched, so there is no
          # way to end up claiming a successful apply while settings.json
          # holds entries the ownership record doesn't know about. The
          # reverse ordering risk — the record listing an entry not yet
          # actually present in settings.json, if the write below fails
          # — is the harmless direction: a later apply/uninstall applying
          # a set operation against a not-actually-present value is a
          # no-op, not a hazard.
          # shellcheck disable=SC2016 # single-quoted jq filter, not shell expansion
          if jq_atomic_write "$OWNED_DENY_FILE" -n --argjson v "$new_owned" '$v'; then
            did "recorded $(jq 'length' <<<"$added_this_run") newly-added deny entries as Bindle-owned (for a future --uninstall)"
            # shellcheck disable=SC2016 # single-quoted jq filter, not shell expansion
            if jq_atomic_write "$CLAUDE_SETTINGS" --argjson new "$(deny_manifest_json)" \
              '.permissions = (.permissions // {}) |
               .permissions.deny = ((.permissions.deny // []) + ($new - (.permissions.deny // [])))' \
              "$CLAUDE_SETTINGS"; then
              did "merged ${#DENY_MANIFEST[@]} guardrail deny entries into $CLAUDE_SETTINGS (existing entries untouched)"
            else
              problem "failed to update $CLAUDE_SETTINGS while merging deny entries — $OWNED_DENY_FILE already reflects entries not yet present in settings.json; re-run --apply to retry"
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
    would "install $CLAUDE_GUARD_INSTALLED and $ALLOW_MAIN_WRITE_INSTALLED"
    if [ -f "$CLAUDE_SETTINGS" ] && pretooluse_entry_present "$PRETOOLUSE_COMMAND"; then
      say "  PreToolUse guard entry already present — no change"
    else
      would "add PreToolUse guard entry ($PRETOOLUSE_MATCHER) to $CLAUDE_SETTINGS"
    fi
    would "merge ${#DENY_MANIFEST[@]} guardrail permissions.deny entries into $CLAUDE_SETTINGS (only entries not already present)"
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
