#!/usr/bin/env bash
#
# test-install-guardrails.sh — regression suite for the Claude-layer half of
# bin/install-guardrails.sh: settings.json structural merge, the secret-file
# deny manifest's content, and install/uninstall round-trips against
# pre-existing unrelated user configuration. Fully isolated (its own HOME,
# guard install home, and Claude home) — never touches the real
# ~/.claude or ~/.local/share/bindle. Only synthetic fixtures are used;
# no real secrets are read or written.
#
# Usage: bin/test-install-guardrails.sh
#
set -uo pipefail

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$REPO_ROOT/bin/install-guardrails.sh"

pass=0 fail=0
check() { # check "description" command...
  local desc="$1"
  shift
  if "$@"; then
    printf '  ✓ %s\n' "$desc"
    pass=$((pass + 1))
  else
    printf '  ✗ %s\n' "$desc"
    fail=$((fail + 1))
  fi
}

# inode_of FILE — the file's inode number, portable across GNU coreutils
# stat (Linux, `-c`) and BSD stat (macOS, `-f`). Used to prove a path's
# identity is unchanged (same inode) or was atomically replaced (different
# inode) without depending on either platform's stat flavor.
inode_of() {
  stat -c %i "$1" 2>/dev/null || stat -f %i "$1" 2>/dev/null
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export BINDLE_GUARD_HOME="$TMP/guard-home"
export BINDLE_CLAUDE_HOME="$TMP/claude-home"
export HOME="$TMP/fake-home"
mkdir -p "$HOME" "$BINDLE_CLAUDE_HOME"
git config --global user.email test@example.com
git config --global user.name Test

SETTINGS="$BINDLE_CLAUDE_HOME/settings.json"

# Pre-existing user config this installer must never touch — an unrelated
# PreToolUse entry (different matcher), an unrelated top-level key, and an
# unrelated permissions.deny entry that happens to sit in the same array
# Bindle's manifest also writes into.
cat >"$SETTINGS" <<'EOF'
{
  "model": "sonnet",
  "hooks": {
    "PreToolUse": [
      {"matcher": "Agent", "hooks": [{"type": "command", "command": "~/.claude/hooks/subagent-limit-guard", "timeout": 5}]}
    ]
  },
  "permissions": {
    "deny": ["Bash(rm -rf /)"]
  },
  "customUserSetting": "must-survive"
}
EOF

"$INSTALLER" --apply >/dev/null

# ===========================================================================
echo "structural merge preserves unrelated existing configuration:"

check "the pre-existing unrelated PreToolUse (Agent) entry survives" bash -c \
  "jq -e '.hooks.PreToolUse | any(.matcher == \"Agent\")' '$SETTINGS' >/dev/null"
check "our new PreToolUse (Edit|Write|MultiEdit|NotebookEdit) entry was added" bash -c \
  "jq -e '.hooks.PreToolUse | any(.matcher == \"Edit|Write|MultiEdit|NotebookEdit\")' '$SETTINGS' >/dev/null"
check "the pre-existing unrelated permissions.deny entry survives" bash -c \
  "jq -e '.permissions.deny | any(. == \"Bash(rm -rf /)\")' '$SETTINGS' >/dev/null"
check "the unrelated top-level customUserSetting key survives" bash -c \
  "[ \"\$(jq -r '.customUserSetting' '$SETTINGS')\" = must-survive ]"

# ===========================================================================
echo "secret-file deny manifest content:"

check "settings.json is well-formed JSON after merge" jq -e . "$SETTINGS" >/dev/null

check ".env is denied for Read" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(.env)\")' '$SETTINGS' >/dev/null"
check ".env.local is denied for Read" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(.env.local)\")' '$SETTINGS' >/dev/null"
check ".env.*.local is denied for Read" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(.env.*.local)\")' '$SETTINGS' >/dev/null"
check "secrets/** is denied for Read" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(secrets/**)\")' '$SETTINGS' >/dev/null"
check ".env is denied for Edit and Write too, not just Read" bash -c \
  "jq -e '.permissions.deny | any(. == \"Edit(.env)\") and any(. == \"Write(.env)\")' '$SETTINGS' >/dev/null"

check ".env.example is never targeted by any deny pattern (excluded by construction)" bash -c \
  "! jq -e '.permissions.deny | any(test(\"\\\\.env\\\\.example\"))' '$SETTINGS' >/dev/null"
check ".env.template is never targeted by any deny pattern" bash -c \
  "! jq -e '.permissions.deny | any(test(\"\\\\.env\\\\.template\"))' '$SETTINGS' >/dev/null"

check "id_rsa (private key) is denied" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(id_rsa)\")' '$SETTINGS' >/dev/null"
check "id_rsa.pub (the PUBLIC half) is never denied — not a secret" bash -c \
  "! jq -e '.permissions.deny | any(test(\"id_rsa\\\\.pub\"))' '$SETTINGS' >/dev/null"
check "*.pem is NOT blanket-denied — PEM is also a public certificate format" bash -c \
  "! jq -e '.permissions.deny | any(. == \"Read(*.pem)\")' '$SETTINGS' >/dev/null"
check "privkey.pem (an actual private-key shape) IS denied" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(privkey.pem)\")' '$SETTINGS' >/dev/null"

check "obvious 'env' dump is denied for Bash" bash -c \
  "jq -e '.permissions.deny | any(. == \"Bash(env)\")' '$SETTINGS' >/dev/null"
check "obvious 'printenv' dump is denied for Bash" bash -c \
  "jq -e '.permissions.deny | any(. == \"Bash(printenv)\")' '$SETTINGS' >/dev/null"
check "obvious macOS Keychain dump is denied for Bash" bash -c \
  "jq -e '.permissions.deny | any(. == \"Bash(security dump-keychain:*)\")' '$SETTINGS' >/dev/null"
check "an ordinary, unrelated Bash command shape is not touched by the manifest" bash -c \
  "! jq -e '.permissions.deny | any(. == \"Bash(npm test)\")' '$SETTINGS' >/dev/null"

# ===========================================================================
echo "idempotency:"

BEFORE_LEN="$(jq '.permissions.deny | length' "$SETTINGS")"
BEFORE_PTU_LEN="$(jq '.hooks.PreToolUse | length' "$SETTINGS")"
"$INSTALLER" --apply >/dev/null
AFTER_LEN="$(jq '.permissions.deny | length' "$SETTINGS")"
AFTER_PTU_LEN="$(jq '.hooks.PreToolUse | length' "$SETTINGS")"
check "re-applying does not duplicate permissions.deny entries" bash -c \
  "[ '$BEFORE_LEN' = '$AFTER_LEN' ]"
check "re-applying does not duplicate the PreToolUse guard entry" bash -c \
  "[ '$BEFORE_PTU_LEN' = '$AFTER_PTU_LEN' ]"

# ===========================================================================
echo "uninstall preserves unrelated configuration:"

"$INSTALLER" --uninstall >/dev/null

check "the unrelated PreToolUse (Agent) entry still survives uninstall" bash -c \
  "jq -e '.hooks.PreToolUse | any(.matcher == \"Agent\")' '$SETTINGS' >/dev/null"
check "our PreToolUse guard entry is gone after uninstall" bash -c \
  "! jq -e '.hooks.PreToolUse | any(.matcher == \"Edit|Write|MultiEdit|NotebookEdit\")' '$SETTINGS' >/dev/null"
check "the unrelated permissions.deny entry still survives uninstall" bash -c \
  "jq -e '.permissions.deny | any(. == \"Bash(rm -rf /)\")' '$SETTINGS' >/dev/null"
check "our guardrail deny entries are gone after uninstall" bash -c \
  "! jq -e '.permissions.deny | any(. == \"Read(.env)\")' '$SETTINGS' >/dev/null"
check "the unrelated top-level key still survives uninstall" bash -c \
  "[ \"\$(jq -r '.customUserSetting' '$SETTINGS')\" = must-survive ]"

# ===========================================================================
echo "a pre-existing entry byte-identical to a Bindle-generated rule survives install + uninstall:"

# A fresh, isolated sandbox (separate from the shared one above) whose
# settings.json already contains "Read(.env)" — the EXACT string Bindle's
# own manifest also generates — before Bindle ever runs. Ownership must be
# tracked by "did Bindle add this," not "does this string appear in the
# generated manifest," or an --uninstall would delete a rule it never put
# there (bin/install-guardrails.sh, OWNED_DENY_FILE).
OVERLAP_CLAUDE_HOME="$TMP/overlap-claude-home"
OVERLAP_GUARD_HOME="$TMP/overlap-guard-home"
mkdir -p "$OVERLAP_CLAUDE_HOME"
OVERLAP_SETTINGS="$OVERLAP_CLAUDE_HOME/settings.json"
cat >"$OVERLAP_SETTINGS" <<'EOF'
{
  "permissions": {
    "deny": ["Read(.env)"]
  }
}
EOF

BINDLE_CLAUDE_HOME="$OVERLAP_CLAUDE_HOME" BINDLE_GUARD_HOME="$OVERLAP_GUARD_HOME" \
  "$INSTALLER" --apply >/dev/null
check "the pre-existing Read(.env) entry is still present after install (not duplicated)" bash -c \
  "[ \"\$(jq '[.permissions.deny[] | select(. == \"Read(.env)\")] | length' '$OVERLAP_SETTINGS')\" = 1 ]"

BINDLE_CLAUDE_HOME="$OVERLAP_CLAUDE_HOME" BINDLE_GUARD_HOME="$OVERLAP_GUARD_HOME" \
  "$INSTALLER" --uninstall >/dev/null
check "the pre-existing byte-identical Read(.env) entry survives uninstall" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(.env)\")' '$OVERLAP_SETTINGS' >/dev/null"
check "every OTHER Bindle-generated deny entry was removed, leaving only the pre-existing one" bash -c \
  "[ \"\$(jq '.permissions.deny | length' '$OVERLAP_SETTINGS')\" = 1 ]"

# ===========================================================================
echo "a malformed existing settings.json is refused safely, never mutated:"

# --apply against malformed JSON.
MALFORMED_APPLY_CLAUDE_HOME="$TMP/malformed-apply-claude-home"
MALFORMED_APPLY_GUARD_HOME="$TMP/malformed-apply-guard-home"
mkdir -p "$MALFORMED_APPLY_CLAUDE_HOME"
MALFORMED_APPLY_SETTINGS="$MALFORMED_APPLY_CLAUDE_HOME/settings.json"
printf '{ this is not valid json' >"$MALFORMED_APPLY_SETTINGS"

# shellcheck disable=SC2317,SC2329
apply_refuses_malformed_settings() {
  ! BINDLE_CLAUDE_HOME="$MALFORMED_APPLY_CLAUDE_HOME" BINDLE_GUARD_HOME="$MALFORMED_APPLY_GUARD_HOME" \
    "$INSTALLER" --apply >/dev/null 2>&1
}
check "--apply against a malformed settings.json exits nonzero" apply_refuses_malformed_settings
check "--apply leaves the malformed settings.json byte-for-byte untouched" bash -c \
  "[ \"\$(cat '$MALFORMED_APPLY_SETTINGS')\" = '{ this is not valid json' ]"

# --uninstall against malformed JSON. Config must be detached before the
# files it references are removed: if settings.json can't be safely
# updated, the PreToolUse entry (if any) is still active, so the guard and
# helper files it names must be PRESERVED, not deleted out from under it.
MALFORMED_UNINSTALL_CLAUDE_HOME="$TMP/malformed-uninstall-claude-home"
MALFORMED_UNINSTALL_GUARD_HOME="$TMP/malformed-uninstall-guard-home"
BINDLE_CLAUDE_HOME="$MALFORMED_UNINSTALL_CLAUDE_HOME" BINDLE_GUARD_HOME="$MALFORMED_UNINSTALL_GUARD_HOME" \
  "$INSTALLER" --apply >/dev/null
MALFORMED_UNINSTALL_SETTINGS="$MALFORMED_UNINSTALL_CLAUDE_HOME/settings.json"
printf '{ this is not valid json either' >"$MALFORMED_UNINSTALL_SETTINGS"

# shellcheck disable=SC2317,SC2329
uninstall_refuses_malformed_settings() {
  ! BINDLE_CLAUDE_HOME="$MALFORMED_UNINSTALL_CLAUDE_HOME" BINDLE_GUARD_HOME="$MALFORMED_UNINSTALL_GUARD_HOME" \
    "$INSTALLER" --uninstall >/dev/null 2>&1
}
check "--uninstall against a malformed settings.json exits nonzero" uninstall_refuses_malformed_settings
check "--uninstall leaves the malformed settings.json byte-for-byte untouched" bash -c \
  "[ \"\$(cat '$MALFORMED_UNINSTALL_SETTINGS')\" = '{ this is not valid json either' ]"
check "--uninstall PRESERVES the installed guard script when settings.json is malformed (the still-active registration must keep resolving)" bash -c \
  "[ -e '$MALFORMED_UNINSTALL_CLAUDE_HOME/hooks/bindle-protected-main-guard' ]"
check "--uninstall PRESERVES the installed helper script when settings.json is malformed" bash -c \
  "[ -e '$MALFORMED_UNINSTALL_GUARD_HOME/bin/allow-main-write.sh' ]"

# ===========================================================================
echo "a malformed claude-deny-owned.json is preserved, not deleted, during uninstall:"

MALFORMED_OWNED_CLAUDE_HOME="$TMP/malformed-owned-claude-home"
MALFORMED_OWNED_GUARD_HOME="$TMP/malformed-owned-guard-home"
BINDLE_CLAUDE_HOME="$MALFORMED_OWNED_CLAUDE_HOME" BINDLE_GUARD_HOME="$MALFORMED_OWNED_GUARD_HOME" \
  "$INSTALLER" --apply >/dev/null
MALFORMED_OWNED_SETTINGS="$MALFORMED_OWNED_CLAUDE_HOME/settings.json"
MALFORMED_OWNED_FILE="$MALFORMED_OWNED_GUARD_HOME/claude-deny-owned.json"
printf '{not valid json' >"$MALFORMED_OWNED_FILE"
DENY_LEN_BEFORE="$(jq '.permissions.deny | length' "$MALFORMED_OWNED_SETTINGS")"

# shellcheck disable=SC2317,SC2329
uninstall_refuses_malformed_owned_file() {
  ! BINDLE_CLAUDE_HOME="$MALFORMED_OWNED_CLAUDE_HOME" BINDLE_GUARD_HOME="$MALFORMED_OWNED_GUARD_HOME" \
    "$INSTALLER" --uninstall >/dev/null 2>&1
}
check "--uninstall exits nonzero when claude-deny-owned.json is malformed" uninstall_refuses_malformed_owned_file
check "the malformed claude-deny-owned.json is preserved, not deleted" bash -c \
  "[ \"\$(cat '$MALFORMED_OWNED_FILE')\" = '{not valid json' ]"
check "permissions.deny in settings.json is left completely unchanged" bash -c \
  "[ \"\$(jq '.permissions.deny | length' '$MALFORMED_OWNED_SETTINGS')\" = '$DENY_LEN_BEFORE' ]"

# ===========================================================================
echo "a settings.json write failure is reported, never claimed as success:"

# Simulates a temp-file-write/rename failure the smallest practical way:
# make ~/.claude itself unwritable (new files can't be created directly in
# it, which is exactly where settings.json's own atomic-write temp file
# must live) while pre-creating the hooks/ and bin/ subdirectories so guard-
# script installation is unaffected — isolating the failure to exactly the
# settings.json read/write path this task is about.
WRITEFAIL_CLAUDE_HOME="$TMP/writefail-claude-home"
WRITEFAIL_GUARD_HOME="$TMP/writefail-guard-home"
mkdir -p "$WRITEFAIL_CLAUDE_HOME/hooks" "$WRITEFAIL_GUARD_HOME/bin"
echo '{}' >"$WRITEFAIL_CLAUDE_HOME/settings.json"
chmod 555 "$WRITEFAIL_CLAUDE_HOME"

# shellcheck disable=SC2317,SC2329
apply_reports_write_failure() {
  ! BINDLE_CLAUDE_HOME="$WRITEFAIL_CLAUDE_HOME" BINDLE_GUARD_HOME="$WRITEFAIL_GUARD_HOME" \
    "$INSTALLER" --apply >/dev/null 2>&1
}
check "--apply exits nonzero when settings.json's directory is unwritable" apply_reports_write_failure
check "settings.json itself was never partially written" bash -c \
  "[ \"\$(cat '$WRITEFAIL_CLAUDE_HOME/settings.json')\" = '{}' ]"
chmod 755 "$WRITEFAIL_CLAUDE_HOME"

# ===========================================================================
echo "an incomplete Git layer never activates core.hooksPath:"

# core.hooksPath is REAL global git config (scoped to this test's own $HOME,
# but shared across every scenario run within this one test file) — an
# earlier scenario's successful --apply can leave it pointing at that
# scenario's own sandbox. Start from a known-clean slate so this test
# observes only what IT does, not leftover state from an earlier one.
git config --global --unset core.hooksPath 2>/dev/null || true

# The dispatcher + symlink set is now built in a sibling staging directory
# under GUARD_HOME first (bin/install-guardrails.sh, "staged install"), so
# simulating a failure means blocking NEW entries directly under GUARD_HOME
# (where the staging dir would be created) while leaving an already-created
# GUARD_BIN_DIR (Claude layer's own install target) writable — isolating
# the failure to only the git-hooks staging step, not cascading into the
# unrelated Claude layer.
GITBLOCK_GUARD_HOME="$TMP/gitblock-guard-home"
GITBLOCK_CLAUDE_HOME="$TMP/gitblock-claude-home"
mkdir -p "$GITBLOCK_GUARD_HOME/bin" "$GITBLOCK_CLAUDE_HOME"
chmod 555 "$GITBLOCK_GUARD_HOME"
GITBLOCK_LOG="$TMP/gitblock-output.log"

# shellcheck disable=SC2317,SC2329
git_layer_apply_fails() {
  ! BINDLE_GUARD_HOME="$GITBLOCK_GUARD_HOME" BINDLE_CLAUDE_HOME="$GITBLOCK_CLAUDE_HOME" \
    "$INSTALLER" --apply >"$GITBLOCK_LOG" 2>&1
}
check "--apply exits nonzero when the Git guard staging location is blocked" git_layer_apply_fails

# shellcheck disable=SC2317,SC2329
core_hookspath_not_activated() {
  ! git config --global --get core.hooksPath >/dev/null 2>&1
}
check "core.hooksPath is never activated (left unset, not pointed at a broken install)" core_hookspath_not_activated

# Captured output is read back from a file, not embedded via shell quoting
# — some problem messages legitimately contain an apostrophe ("Bindle's
# guardrails"), which would break a quoted-string embedding.
check "no false success is reported for the broken Git layer (no 'set global core.hooksPath' line)" bash -c \
  "! grep -q 'set global core.hooksPath' '$GITBLOCK_LOG'"
check "the failure is actually reported" bash -c \
  "grep -q 'core.hooksPath unchanged' '$GITBLOCK_LOG'"
check "the independent Claude layer still installs normally (proves this doesn't cascade)" bash -c \
  "[ -e '$GITBLOCK_CLAUDE_HOME/hooks/bindle-protected-main-guard' ]"

chmod 755 "$GITBLOCK_GUARD_HOME"
# Leave core.hooksPath clean for whatever runs next.
git config --global --unset core.hooksPath 2>/dev/null || true

# ===========================================================================
echo "a re-apply preserves the SAME \$HOOKS_DIR continuously, replacing only the dispatcher:"

git config --global --unset core.hooksPath 2>/dev/null || true

REAPPLY_GUARD_HOME="$TMP/reapply-guard-home"
REAPPLY_CLAUDE_HOME="$TMP/reapply-claude-home"

# Establish a genuinely valid, active installation first.
BINDLE_GUARD_HOME="$REAPPLY_GUARD_HOME" BINDLE_CLAUDE_HOME="$REAPPLY_CLAUDE_HOME" \
  "$INSTALLER" --apply >/dev/null
REAPPLY_HOOKS_DIR="$REAPPLY_GUARD_HOME/git-hooks"
REAPPLY_DISPATCHER="$REAPPLY_HOOKS_DIR/.bindle-git-hook-dispatch"
check "the initial install actually activated core.hooksPath (sanity check before forcing a failure)" bash -c \
  "[ \"\$(git config --global --get core.hooksPath)\" = '$REAPPLY_HOOKS_DIR' ]"
# The directory's own inode is the identity that matters for the concurrency
# guarantee: core.hooksPath names a PATH, and if that path were ever renamed
# away even briefly (the old two-rename swap), a concurrent Git operation
# could observe it missing. Proving the inode never changes proves the
# directory itself was never replaced — only ever mutated in place.
BEFORE_DIR_INODE="$(inode_of "$REAPPLY_HOOKS_DIR")"
BEFORE_DISPATCHER_INODE="$(inode_of "$REAPPLY_DISPATCHER")"
BEFORE_DISPATCHER_SUM="$(cksum <"$REAPPLY_DISPATCHER")"
BEFORE_SYMLINK_COUNT="$(find "$REAPPLY_HOOKS_DIR" -type l | wc -l | tr -d ' ')"

echo "  a successful re-apply:"
# shellcheck disable=SC2317,SC2329
reapply_succeeds() {
  BINDLE_GUARD_HOME="$REAPPLY_GUARD_HOME" BINDLE_CLAUDE_HOME="$REAPPLY_CLAUDE_HOME" \
    "$INSTALLER" --apply >/dev/null 2>&1
}
check "  exits cleanly" reapply_succeeds
AFTER_DIR_INODE="$(inode_of "$REAPPLY_HOOKS_DIR")"
AFTER_DISPATCHER_INODE="$(inode_of "$REAPPLY_DISPATCHER")"
check "  \$HOOKS_DIR's own inode is unchanged — the directory itself was never replaced" bash -c \
  "[ '$AFTER_DIR_INODE' = '$BEFORE_DIR_INODE' ]"
check "  the dispatcher's inode DID change — it was atomically replaced, not edited in place" bash -c \
  "[ '$AFTER_DISPATCHER_INODE' != '$BEFORE_DISPATCHER_INODE' ]"
check "  core.hooksPath is still correctly set" bash -c \
  "[ \"\$(git config --global --get core.hooksPath)\" = '$REAPPLY_HOOKS_DIR' ]"
check "  every one of the $BEFORE_SYMLINK_COUNT hook symlinks is still present and valid" bash -c \
  "[ \"\$(find '$REAPPLY_HOOKS_DIR' -type l | wc -l | tr -d ' ')\" = '$BEFORE_SYMLINK_COUNT' ]"
check "  no leftover '.new' temp file was left behind" bash -c \
  "[ -z \"\$(find '$REAPPLY_HOOKS_DIR' -maxdepth 1 -name '.bindle-git-hook-dispatch.new.*')\" ]"

echo "  a re-apply whose dispatcher staging fails:"
BEFORE_DISPATCHER_SUM="$(cksum <"$REAPPLY_DISPATCHER")"
BEFORE_DIR_INODE="$(inode_of "$REAPPLY_HOOKS_DIR")"
# Block writing a NEW file directly inside $HOOKS_DIR (where the temp
# dispatcher must be staged before the atomic rename) — the directory
# itself, and everything already in it, stays fully usable throughout.
chmod 555 "$REAPPLY_HOOKS_DIR"

# shellcheck disable=SC2317,SC2329
reapply_fails_during_staging() {
  ! BINDLE_GUARD_HOME="$REAPPLY_GUARD_HOME" BINDLE_CLAUDE_HOME="$REAPPLY_CLAUDE_HOME" \
    "$INSTALLER" --apply >/dev/null 2>&1
}
check "  exits nonzero when staging the updated dispatcher fails" reapply_fails_during_staging

chmod 755 "$REAPPLY_HOOKS_DIR"

AFTER_DIR_INODE="$(inode_of "$REAPPLY_HOOKS_DIR")"
check "  \$HOOKS_DIR's own inode is unchanged (never touched, not even attempted)" bash -c \
  "[ '$AFTER_DIR_INODE' = '$BEFORE_DIR_INODE' ]"
check "  core.hooksPath still points at the pre-existing installation, unchanged" bash -c \
  "[ \"\$(git config --global --get core.hooksPath)\" = '$REAPPLY_HOOKS_DIR' ]"
check "  the pre-existing dispatcher file still exists and is unchanged (same content)" bash -c \
  "[ -x '$REAPPLY_DISPATCHER' ] && [ \"\$(cksum <'$REAPPLY_DISPATCHER')\" = '$BEFORE_DISPATCHER_SUM' ]"
check "  every pre-existing hook symlink is still present and usable" bash -c \
  "[ \"\$(find '$REAPPLY_HOOKS_DIR' -type l | wc -l | tr -d ' ')\" = '$BEFORE_SYMLINK_COUNT' ]"
check "  no leftover '.new' temp file was left behind" bash -c \
  "[ -z \"\$(find '$REAPPLY_HOOKS_DIR' -maxdepth 1 -name '.bindle-git-hook-dispatch.new.*')\" ]"

echo "  a re-apply against a corrupted existing installation fails safely, without live repair:"
rm -f "$REAPPLY_HOOKS_DIR/pre-push"

# shellcheck disable=SC2317,SC2329
reapply_fails_on_corruption() {
  ! BINDLE_GUARD_HOME="$REAPPLY_GUARD_HOME" BINDLE_CLAUDE_HOME="$REAPPLY_CLAUDE_HOME" \
    "$INSTALLER" --apply >/dev/null 2>&1
}
check "  exits nonzero when an existing hook symlink is missing" reapply_fails_on_corruption
check "  the missing symlink is NOT silently recreated (no live repair)" bash -c \
  "[ ! -e '$REAPPLY_HOOKS_DIR/pre-push' ]"
check "  the dispatcher itself is untouched" bash -c \
  "[ \"\$(cksum <'$REAPPLY_DISPATCHER')\" = '$BEFORE_DISPATCHER_SUM' ]"

git config --global --unset core.hooksPath 2>/dev/null || true

# ===========================================================================
echo "incomplete Claude guard/helper installation never registers the PreToolUse entry:"

# A plain FILE occupies the exact path the Claude hooks directory needs —
# isolated to only that install step (the Git layer and the independent
# permissions.deny hardening are untouched and should still succeed).
CLAUDEBLOCK_GUARD_HOME="$TMP/claudeblock-guard-home"
CLAUDEBLOCK_CLAUDE_HOME="$TMP/claudeblock-claude-home"
mkdir -p "$CLAUDEBLOCK_GUARD_HOME" "$CLAUDEBLOCK_CLAUDE_HOME"
touch "$CLAUDEBLOCK_CLAUDE_HOME/hooks"
CLAUDEBLOCK_SETTINGS="$CLAUDEBLOCK_CLAUDE_HOME/settings.json"

# shellcheck disable=SC2317,SC2329
claude_layer_apply_fails() {
  ! BINDLE_GUARD_HOME="$CLAUDEBLOCK_GUARD_HOME" BINDLE_CLAUDE_HOME="$CLAUDEBLOCK_CLAUDE_HOME" \
    "$INSTALLER" --apply >/dev/null 2>&1
}
check "--apply exits nonzero when the Claude guard/helper install location is blocked" claude_layer_apply_fails

check "the PreToolUse guard entry is NOT registered when guard/helper install failed" bash -c \
  "! jq -e '.hooks.PreToolUse | any(.matcher == \"Edit|Write|MultiEdit|NotebookEdit\")' '$CLAUDEBLOCK_SETTINGS' >/dev/null 2>&1"
check "the guard script itself was never installed" bash -c \
  "[ ! -e '$CLAUDEBLOCK_CLAUDE_HOME/hooks/bindle-protected-main-guard' ]"
check "the independent Git layer still activates normally (proves this doesn't cascade)" bash -c \
  "[ -x '$CLAUDEBLOCK_GUARD_HOME/git-hooks/.bindle-git-hook-dispatch' ]"
check "the independent permissions.deny hardening still applies (not gated on guard-file install)" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(.env)\")' '$CLAUDEBLOCK_SETTINGS' >/dev/null"

# ===========================================================================
printf '\n  install-guardrails: %d/%d checks passed\n' "$pass" "$((pass + fail))"
exit "$fail"
