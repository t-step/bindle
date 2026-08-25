#!/usr/bin/env bash
#
# test-install-guardrails.sh — regression suite for the Claude-layer half of
# install-guardrails.sh: settings.local.json structural merge, the
# secret-file deny manifest's content, and install/uninstall round-trips
# against pre-existing unrelated repository configuration. The Claude layer
# is repo-local (installed into a target repository's own
# .claude/settings.local.json, never a global Claude configuration), so
# every scenario here uses a real, isolated fixture repository. Fully
# isolated otherwise too (its own HOME, legacy-lookup homes) — never
# touches the real ~/.claude or ~/.local/share/bindle. Only synthetic
# fixtures are used; no real secrets are read or written.
#
# Usage: bin/test-install-guardrails.sh
#
set -uo pipefail

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$REPO_ROOT/src/bindle/_bin/install-guardrails.sh"

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

# claude_settings_for REPO — the repo-local Claude settings path
# install-guardrails.sh would use for REPO (main-checkout-anchored, per
# Claude Code's own worktree resolution).
claude_settings_for() {
  local repo="$1" common root
  common="$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)"
  if [ "$(basename "$common")" = ".git" ]; then root="$(dirname "$common")"; else root="$common"; fi
  printf '%s' "$root/.claude/settings.local.json"
}

# claude_dir_for REPO — the repo-local directory holding the Claude
# guard/helper scripts for REPO.
claude_dir_for() {
  local repo="$1"
  printf '%s/bindle-claude' "$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)"
}

# owned_deny_file_for REPO — the repo-local deny-ownership record for
# REPO. A sibling of claude_dir_for, not nested inside it (see
# install-guardrails.sh: it must stay reachable even when guard/helper
# installation fails).
owned_deny_file_for() {
  local repo="$1"
  printf '%s/bindle-claude-deny-owned.json' "$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)"
}

# owned_exclude_file_for REPO — the repo-local info/exclude-ownership
# marker for REPO (present iff Bindle itself added the machine-local
# ignore rule for settings.local.json).
owned_exclude_file_for() {
  local repo="$1"
  printf '%s/bindle-claude-exclude-owned' "$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)"
}

# exclude_file_for REPO — the repo's own <git-common-dir>/info/exclude.
exclude_file_for() {
  local repo="$1"
  printf '%s/info/exclude' "$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)"
}

new_fixture() { # new_fixture DIR — a fresh, committed fixture repo at DIR
  local dir="$1"
  rm -rf "$dir"
  git init -q --initial-branch=main "$dir"
  git -C "$dir" config user.email test@example.com
  git -C "$dir" config user.name Test
  git -C "$dir" commit -q --allow-empty -m init
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export BINDLE_GUARD_HOME="$TMP/legacy-guard-home"
export BINDLE_CLAUDE_HOME="$TMP/legacy-claude-home"
export HOME="$TMP/fake-home"
mkdir -p "$HOME"
git config --global user.email test@example.com
git config --global user.name Test

FIX="$TMP/fixture-repo"
new_fixture "$FIX"
SETTINGS="$(claude_settings_for "$FIX")"
mkdir -p "$(dirname "$SETTINGS")"

# Pre-existing repository config this installer must never touch — an
# unrelated PreToolUse entry (different matcher), an unrelated top-level
# key, and an unrelated permissions.deny entry that happens to sit in the
# same array Bindle's manifest also writes into.
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

"$INSTALLER" --apply --claude-only --repo "$FIX" >/dev/null

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
FIX_CLAUDE_DIR="$(claude_dir_for "$FIX")"
check "the guard/helper scripts were installed inside the repo's own .git, not anywhere global" \
  test -x "$FIX_CLAUDE_DIR/claude-protected-main-guard"

# ===========================================================================
echo "secret-file deny manifest content:"

check "settings.local.json is well-formed JSON after merge" jq -e . "$SETTINGS" >/dev/null

check ".env is denied for Read" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(.env)\")' '$SETTINGS' >/dev/null"
check ".env.local is denied for Read" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(.env.local)\")' '$SETTINGS' >/dev/null"
check ".env.*.local is denied for Read" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(.env.*.local)\")' '$SETTINGS' >/dev/null"
check "secrets/** is denied for Read" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(secrets/**)\")' '$SETTINGS' >/dev/null"
check ".env is denied for Edit too, not just Read" bash -c \
  "jq -e '.permissions.deny | any(. == \"Edit(.env)\")' '$SETTINGS' >/dev/null"
check "no separate Write(.env) deny entry — Claude Code doesn't match Write(path); Edit(path) already covers it" bash -c \
  "! jq -e '.permissions.deny | any(. == \"Write(.env)\")' '$SETTINGS' >/dev/null"

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
"$INSTALLER" --apply --claude-only --repo "$FIX" >/dev/null
AFTER_LEN="$(jq '.permissions.deny | length' "$SETTINGS")"
AFTER_PTU_LEN="$(jq '.hooks.PreToolUse | length' "$SETTINGS")"
check "re-applying does not duplicate permissions.deny entries" bash -c \
  "[ '$BEFORE_LEN' = '$AFTER_LEN' ]"
check "re-applying does not duplicate the PreToolUse guard entry" bash -c \
  "[ '$BEFORE_PTU_LEN' = '$AFTER_PTU_LEN' ]"

# ===========================================================================
echo "uninstall preserves unrelated configuration:"

"$INSTALLER" --uninstall --claude-only --repo "$FIX" >/dev/null

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
check "the repo-local guard/helper directory was removed" bash -c \
  "[ ! -d \"\$(git -C '$FIX' rev-parse --path-format=absolute --git-common-dir)/bindle-claude\" ]"

# ===========================================================================
echo "a pre-existing entry byte-identical to a Bindle-generated rule survives install + uninstall:"

# A fresh, isolated fixture whose settings.local.json already contains
# "Read(.env)" — the EXACT string Bindle's own manifest also generates —
# before Bindle ever runs. Ownership must be tracked by "did Bindle add
# this," not "does this string appear in the generated manifest," or an
# --uninstall would delete a rule it never put there (OWNED_DENY_FILE).
OVERLAP_REPO="$TMP/overlap-repo"
new_fixture "$OVERLAP_REPO"
OVERLAP_SETTINGS="$(claude_settings_for "$OVERLAP_REPO")"
mkdir -p "$(dirname "$OVERLAP_SETTINGS")"
cat >"$OVERLAP_SETTINGS" <<'EOF'
{
  "permissions": {
    "deny": ["Read(.env)"]
  }
}
EOF

"$INSTALLER" --apply --claude-only --repo "$OVERLAP_REPO" >/dev/null
check "the pre-existing Read(.env) entry is still present after install (not duplicated)" bash -c \
  "[ \"\$(jq '[.permissions.deny[] | select(. == \"Read(.env)\")] | length' '$OVERLAP_SETTINGS')\" = 1 ]"

"$INSTALLER" --uninstall --claude-only --repo "$OVERLAP_REPO" >/dev/null
check "the pre-existing byte-identical Read(.env) entry survives uninstall" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(.env)\")' '$OVERLAP_SETTINGS' >/dev/null"
check "every OTHER Bindle-generated deny entry was removed, leaving only the pre-existing one" bash -c \
  "[ \"\$(jq '.permissions.deny | length' '$OVERLAP_SETTINGS')\" = 1 ]"

# ===========================================================================
echo "a malformed existing settings.local.json is refused safely, never mutated:"

# --apply against malformed JSON.
MALFORMED_APPLY_REPO="$TMP/malformed-apply-repo"
new_fixture "$MALFORMED_APPLY_REPO"
MALFORMED_APPLY_SETTINGS="$(claude_settings_for "$MALFORMED_APPLY_REPO")"
mkdir -p "$(dirname "$MALFORMED_APPLY_SETTINGS")"
printf '{ this is not valid json' >"$MALFORMED_APPLY_SETTINGS"

# shellcheck disable=SC2317,SC2329
apply_refuses_malformed_settings() {
  ! "$INSTALLER" --apply --claude-only --repo "$MALFORMED_APPLY_REPO" >/dev/null 2>&1
}
check "--apply against a malformed settings.local.json exits nonzero" apply_refuses_malformed_settings
check "--apply leaves the malformed settings.local.json byte-for-byte untouched" bash -c \
  "[ \"\$(cat '$MALFORMED_APPLY_SETTINGS')\" = '{ this is not valid json' ]"

# --uninstall against malformed JSON. Config must be detached before the
# files it references are removed: if settings can't be safely updated,
# the PreToolUse entry (if any) is still active, so the guard and helper
# files it names must be PRESERVED, not deleted out from under it.
MALFORMED_UNINSTALL_REPO="$TMP/malformed-uninstall-repo"
new_fixture "$MALFORMED_UNINSTALL_REPO"
"$INSTALLER" --apply --claude-only --repo "$MALFORMED_UNINSTALL_REPO" >/dev/null
MALFORMED_UNINSTALL_SETTINGS="$(claude_settings_for "$MALFORMED_UNINSTALL_REPO")"
MALFORMED_UNINSTALL_CLAUDE_DIR="$(claude_dir_for "$MALFORMED_UNINSTALL_REPO")"
printf '{ this is not valid json either' >"$MALFORMED_UNINSTALL_SETTINGS"

# shellcheck disable=SC2317,SC2329
uninstall_refuses_malformed_settings() {
  ! "$INSTALLER" --uninstall --claude-only --repo "$MALFORMED_UNINSTALL_REPO" >/dev/null 2>&1
}
check "--uninstall against a malformed settings.local.json exits nonzero" uninstall_refuses_malformed_settings
check "--uninstall leaves the malformed settings.local.json byte-for-byte untouched" bash -c \
  "[ \"\$(cat '$MALFORMED_UNINSTALL_SETTINGS')\" = '{ this is not valid json either' ]"
check "--uninstall PRESERVES the installed guard script when settings is malformed (the still-active registration must keep resolving)" bash -c \
  "[ -e '$MALFORMED_UNINSTALL_CLAUDE_DIR/claude-protected-main-guard' ]"
check "--uninstall PRESERVES the installed helper script when settings is malformed" bash -c \
  "[ -e '$MALFORMED_UNINSTALL_CLAUDE_DIR/allow-main-write.sh' ]"

# ===========================================================================
echo "a malformed claude-deny-owned.json is preserved, not deleted, during uninstall:"

MALFORMED_OWNED_REPO="$TMP/malformed-owned-repo"
new_fixture "$MALFORMED_OWNED_REPO"
"$INSTALLER" --apply --claude-only --repo "$MALFORMED_OWNED_REPO" >/dev/null
MALFORMED_OWNED_SETTINGS="$(claude_settings_for "$MALFORMED_OWNED_REPO")"
MALFORMED_OWNED_FILE="$(owned_deny_file_for "$MALFORMED_OWNED_REPO")"
printf '{not valid json' >"$MALFORMED_OWNED_FILE"
DENY_LEN_BEFORE="$(jq '.permissions.deny | length' "$MALFORMED_OWNED_SETTINGS")"

# shellcheck disable=SC2317,SC2329
uninstall_refuses_malformed_owned_file() {
  ! "$INSTALLER" --uninstall --claude-only --repo "$MALFORMED_OWNED_REPO" >/dev/null 2>&1
}
check "--uninstall exits nonzero when claude-deny-owned.json is malformed" uninstall_refuses_malformed_owned_file
check "the malformed claude-deny-owned.json is preserved, not deleted" bash -c \
  "[ \"\$(cat '$MALFORMED_OWNED_FILE')\" = '{not valid json' ]"
check "permissions.deny in settings.local.json is left completely unchanged" bash -c \
  "[ \"\$(jq '.permissions.deny | length' '$MALFORMED_OWNED_SETTINGS')\" = '$DENY_LEN_BEFORE' ]"

# ===========================================================================
echo "a settings.local.json write failure is reported, never claimed as success:"

# Simulates a temp-file-write/rename failure the smallest practical way:
# make the repo's .claude/ directory itself unwritable (new files can't be
# created directly in it, which is exactly where settings.local.json's own
# atomic-write temp file must live) — isolating the failure to exactly the
# settings read/write path this task is about.
WRITEFAIL_REPO="$TMP/writefail-repo"
new_fixture "$WRITEFAIL_REPO"
WRITEFAIL_SETTINGS="$(claude_settings_for "$WRITEFAIL_REPO")"
mkdir -p "$(dirname "$WRITEFAIL_SETTINGS")"
echo '{}' >"$WRITEFAIL_SETTINGS"
chmod 555 "$(dirname "$WRITEFAIL_SETTINGS")"

# shellcheck disable=SC2317,SC2329
apply_reports_write_failure() {
  ! "$INSTALLER" --apply --claude-only --repo "$WRITEFAIL_REPO" >/dev/null 2>&1
}
check "--apply exits nonzero when settings.local.json's directory is unwritable" apply_reports_write_failure
check "settings.local.json itself was never partially written" bash -c \
  "[ \"\$(cat '$WRITEFAIL_SETTINGS')\" = '{}' ]"
chmod 755 "$(dirname "$WRITEFAIL_SETTINGS")"

# ===========================================================================
echo "an incomplete Git layer never activates core.hooksPath:"

# The dispatcher + symlink set is built in a sibling staging directory
# under the target repository's own Git common directory first
# (install-guardrails.sh, "staged install"), so simulating a failure means
# blocking new entries directly under that repo's .git (where the staging
# dir would be created) — isolating the failure to only the git-hooks
# staging step, not cascading into the unrelated Claude layer. The Claude
# layer's own directory is pre-created (writable) so its independence from
# .git's own permissions is what's actually under test here, not merely
# "mkdir -p into a read-only .git fails for everyone."
GITBLOCK_REPO="$TMP/gitblock-repo"
new_fixture "$GITBLOCK_REPO"
mkdir -p "$(claude_dir_for "$GITBLOCK_REPO")"
chmod 555 "$GITBLOCK_REPO/.git"
GITBLOCK_LOG="$TMP/gitblock-output.log"

# shellcheck disable=SC2317,SC2329
git_layer_apply_fails() {
  ! "$INSTALLER" --apply --repo "$GITBLOCK_REPO" >"$GITBLOCK_LOG" 2>&1
}
check "--apply exits nonzero when the Git hooks staging location is blocked" git_layer_apply_fails

chmod 755 "$GITBLOCK_REPO/.git"

# shellcheck disable=SC2317,SC2329
core_hookspath_not_activated() {
  ! git -C "$GITBLOCK_REPO" config --local --get core.hooksPath >/dev/null 2>&1
}
check "core.hooksPath is never activated (left unset, not pointed at a broken install)" core_hookspath_not_activated

# Captured output is read back from a file, not embedded via shell quoting
# — some problem messages legitimately contain an apostrophe ("Bindle's
# guardrails"), which would break a quoted-string embedding.
check "no false success is reported for the broken Git layer (no 'set repo-local core.hooksPath' line)" bash -c \
  "! grep -q 'set repo-local core.hooksPath' '$GITBLOCK_LOG'"
check "the failure is actually reported" bash -c \
  "grep -q 'core.hooksPath unchanged' '$GITBLOCK_LOG'"
GITBLOCK_CLAUDE_DIR="$(claude_dir_for "$GITBLOCK_REPO")"
check "the independent Claude layer still installs normally (proves this doesn't cascade)" \
  test -e "$GITBLOCK_CLAUDE_DIR/claude-protected-main-guard"

# ===========================================================================
echo "a re-apply preserves the SAME \$HOOKS_DIR continuously, replacing only the dispatcher:"

REAPPLY_REPO="$TMP/reapply-repo"
new_fixture "$REAPPLY_REPO"

# Establish a genuinely valid, active installation first.
"$INSTALLER" --apply --git-only --repo "$REAPPLY_REPO" >/dev/null
REAPPLY_HOOKS_DIR="$(git -C "$REAPPLY_REPO" rev-parse --path-format=absolute --git-common-dir)/bindle-hooks"
REAPPLY_DISPATCHER="$REAPPLY_HOOKS_DIR/.bindle-git-hook-dispatch"
check "the initial install actually activated core.hooksPath (sanity check before forcing a failure)" bash -c \
  "[ \"\$(git -C '$REAPPLY_REPO' config --local --get core.hooksPath)\" = '$REAPPLY_HOOKS_DIR' ]"
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
  "$INSTALLER" --apply --git-only --repo "$REAPPLY_REPO" >/dev/null 2>&1
}
check "  exits cleanly" reapply_succeeds
AFTER_DIR_INODE="$(inode_of "$REAPPLY_HOOKS_DIR")"
AFTER_DISPATCHER_INODE="$(inode_of "$REAPPLY_DISPATCHER")"
check "  \$HOOKS_DIR's own inode is unchanged — the directory itself was never replaced" bash -c \
  "[ '$AFTER_DIR_INODE' = '$BEFORE_DIR_INODE' ]"
check "  the dispatcher's inode DID change — it was atomically replaced, not edited in place" bash -c \
  "[ '$AFTER_DISPATCHER_INODE' != '$BEFORE_DISPATCHER_INODE' ]"
check "  core.hooksPath is still correctly set" bash -c \
  "[ \"\$(git -C '$REAPPLY_REPO' config --local --get core.hooksPath)\" = '$REAPPLY_HOOKS_DIR' ]"
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
  ! "$INSTALLER" --apply --git-only --repo "$REAPPLY_REPO" >/dev/null 2>&1
}
check "  exits nonzero when staging the updated dispatcher fails" reapply_fails_during_staging

chmod 755 "$REAPPLY_HOOKS_DIR"

AFTER_DIR_INODE="$(inode_of "$REAPPLY_HOOKS_DIR")"
check "  \$HOOKS_DIR's own inode is unchanged (never touched, not even attempted)" bash -c \
  "[ '$AFTER_DIR_INODE' = '$BEFORE_DIR_INODE' ]"
check "  core.hooksPath still points at the pre-existing installation, unchanged" bash -c \
  "[ \"\$(git -C '$REAPPLY_REPO' config --local --get core.hooksPath)\" = '$REAPPLY_HOOKS_DIR' ]"
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
  ! "$INSTALLER" --apply --git-only --repo "$REAPPLY_REPO" >/dev/null 2>&1
}
check "  exits nonzero when an existing hook symlink is missing" reapply_fails_on_corruption
check "  the missing symlink is NOT silently recreated (no live repair)" bash -c \
  "[ ! -e '$REAPPLY_HOOKS_DIR/pre-push' ]"
check "  the dispatcher itself is untouched" bash -c \
  "[ \"\$(cksum <'$REAPPLY_DISPATCHER')\" = '$BEFORE_DISPATCHER_SUM' ]"

# ===========================================================================
echo "incomplete Claude guard/helper installation never registers the PreToolUse entry, and rolls the Git layer back:"

# A plain FILE occupies the exact path the Claude-layer directory needs.
# Both layers are requested (no --git-only/--claude-only), so this also
# proves the cross-layer atomicity contract: the Git layer succeeds first,
# but since the overall `bindle init` fails, it must not be left newly
# installed without the Claude layer — install-guardrails.sh rolls it back.
CLAUDEBLOCK_REPO="$TMP/claudeblock-repo"
new_fixture "$CLAUDEBLOCK_REPO"
CLAUDEBLOCK_CLAUDE_DIR="$(claude_dir_for "$CLAUDEBLOCK_REPO")"
touch "$CLAUDEBLOCK_CLAUDE_DIR"
CLAUDEBLOCK_SETTINGS="$(claude_settings_for "$CLAUDEBLOCK_REPO")"

# shellcheck disable=SC2317,SC2329
claude_layer_apply_fails() {
  ! "$INSTALLER" --apply --repo "$CLAUDEBLOCK_REPO" >/dev/null 2>&1
}
check "--apply exits nonzero when the Claude guard/helper install location is blocked" claude_layer_apply_fails

check "the PreToolUse guard entry is NOT registered when guard/helper install failed" bash -c \
  "! jq -e '.hooks.PreToolUse | any(.matcher == \"Edit|Write|MultiEdit|NotebookEdit\")' '$CLAUDEBLOCK_SETTINGS' >/dev/null 2>&1"
check "the guard script itself was never installed" bash -c \
  "[ ! -e '$CLAUDEBLOCK_CLAUDE_DIR/claude-protected-main-guard' ]"
check "the Git layer was rolled back after the Claude layer failed (cross-layer atomicity — no newly-installed Git layer left behind)" bash -c \
  "! git -C '$CLAUDEBLOCK_REPO' config --local --get core.hooksPath >/dev/null 2>&1 && [ ! -e \"\$(git -C '$CLAUDEBLOCK_REPO' rev-parse --path-format=absolute --git-common-dir)/bindle-hooks\" ]"
check "the independent permissions.deny hardening still applies (not gated on guard-file install)" bash -c \
  "jq -e '.permissions.deny | any(. == \"Read(.env)\")' '$CLAUDEBLOCK_SETTINGS' >/dev/null"

# ===========================================================================
echo "legacy global migration (--remove-legacy-global):"

LEGACY_REPO="$TMP/legacy-repo"
new_fixture "$LEGACY_REPO"

check "--remove-legacy-global is a clean no-op when no global core.hooksPath / legacy Claude settings exist" bash -c \
  "'$INSTALLER' --remove-legacy-global >/dev/null"

# A genuine prior install (from before the repo-local rework) is
# indistinguishable, structurally, from today's repo-local install — so
# reuse the installer itself to produce templates, then relocate them into
# global config/state the way the old implementation would have.
"$INSTALLER" --apply --repo "$LEGACY_REPO" >/dev/null
LEGACY_GIT_DIR="$TMP/legacy-global-git-hooks"
mv "$(git -C "$LEGACY_REPO" config --local --get core.hooksPath)" "$LEGACY_GIT_DIR"
git -C "$LEGACY_REPO" config --local --unset core.hooksPath
git config --global core.hooksPath "$LEGACY_GIT_DIR"

LEGACY_CLAUDE_DIR="$(claude_dir_for "$LEGACY_REPO")"
LEGACY_OWNED_DENY_FILE="$(owned_deny_file_for "$LEGACY_REPO")"
mkdir -p "$BINDLE_CLAUDE_HOME/hooks" "$BINDLE_GUARD_HOME/bin"
cp "$LEGACY_CLAUDE_DIR/claude-protected-main-guard" "$BINDLE_CLAUDE_HOME/hooks/bindle-protected-main-guard"
cp "$LEGACY_CLAUDE_DIR/allow-main-write.sh" "$BINDLE_GUARD_HOME/bin/allow-main-write.sh"
cp "$LEGACY_OWNED_DENY_FILE" "$BINDLE_GUARD_HOME/claude-deny-owned.json"
# Non-default BINDLE_CLAUDE_HOME/BINDLE_GUARD_HOME (test isolation) means
# the legacy installer would have written the resolved ABSOLUTE paths, not
# the '~/...' default shorthand.
LEGACY_CMD="$BINDLE_CLAUDE_HOME/hooks/bindle-protected-main-guard $BINDLE_GUARD_HOME/bin/allow-main-write.sh"
cat >"$BINDLE_CLAUDE_HOME/settings.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [{"type": "command", "command": "$LEGACY_CMD", "timeout": 5}]}
    ]
  },
  "permissions": {"deny": $(cat "$BINDLE_GUARD_HOME/claude-deny-owned.json")}
}
EOF
rm -rf "$LEGACY_CLAUDE_DIR"
rm -f "$LEGACY_OWNED_DENY_FILE"
git -C "$LEGACY_REPO" config --local --unset core.hooksPath 2>/dev/null || true

check "--remove-legacy-global removes a genuinely Bindle-owned global core.hooksPath" bash -c \
  "'$INSTALLER' --remove-legacy-global >/dev/null"
check "the global core.hooksPath is unset afterward" bash -c \
  '! git config --global --get core.hooksPath >/dev/null 2>&1'
check "the legacy Git hook directory itself was removed" bash -c \
  "[ ! -e '$LEGACY_GIT_DIR' ]"
check "the legacy global Claude PreToolUse entry was removed" bash -c \
  "[ \"\$(jq '.hooks.PreToolUse | length' '$BINDLE_CLAUDE_HOME/settings.json')\" = 0 ]"
check "the legacy global Claude owned deny entries were removed" bash -c \
  "[ \"\$(jq '.permissions.deny | length' '$BINDLE_CLAUDE_HOME/settings.json')\" = 0 ]"
check "the legacy global Claude guard/helper files were removed" bash -c \
  "[ ! -e '$BINDLE_CLAUDE_HOME/hooks/bindle-protected-main-guard' ] && [ ! -e '$BINDLE_GUARD_HOME/bin/allow-main-write.sh' ]"

git config --global core.hooksPath /some/other/hook/manager
# shellcheck disable=SC2317,SC2329
legacy_remove_refuses_foreign_value() {
  ! "$INSTALLER" --remove-legacy-global >/dev/null 2>&1
}
check "--remove-legacy-global refuses a global core.hooksPath it cannot prove it owns" \
  legacy_remove_refuses_foreign_value
check "the foreign global core.hooksPath is left untouched" bash -c \
  "[ \"\$(git config --global --get core.hooksPath)\" = /some/other/hook/manager ]"
git config --global --unset core.hooksPath

# ===========================================================================
echo "a normal --apply/--uninstall refuses to run when recognized legacy global state exists, and never migrates or mutates it:"

# bindle init/remove are repository-scoped: a recognized pre-rework global
# install must block them with an actionable error pointing at the explicit
# migration surface, never be silently migrated (or silently ignored) as a
# side effect of what looks like a repo-scoped command. A foreign global
# value must never block, migrate, or otherwise affect the outcome.
BLOCK_TEMPLATE_REPO="$TMP/legacyblock-template-repo"
new_fixture "$BLOCK_TEMPLATE_REPO"
"$INSTALLER" --apply --git-only --repo "$BLOCK_TEMPLATE_REPO" >/dev/null
BLOCK_LEGACY_GIT_DIR="$TMP/legacyblock-legacy-git-hooks"
mv "$(git -C "$BLOCK_TEMPLATE_REPO" config --local --get core.hooksPath)" "$BLOCK_LEGACY_GIT_DIR"
git -C "$BLOCK_TEMPLATE_REPO" config --local --unset core.hooksPath
git config --global core.hooksPath "$BLOCK_LEGACY_GIT_DIR"

BLOCK_REPO_A="$TMP/legacyblock-repo-a"
BLOCK_REPO_B="$TMP/legacyblock-repo-b"
new_fixture "$BLOCK_REPO_A"
new_fixture "$BLOCK_REPO_B"
BLOCK_LOG="$TMP/legacyblock-output.log"

# shellcheck disable=SC2317,SC2329
legacyblock_apply_fails() {
  ! "$INSTALLER" --apply --git-only --repo "$BLOCK_REPO_A" >"$BLOCK_LOG" 2>&1
}
check "a normal --apply against Repo A fails clearly when recognized legacy global state exists" \
  legacyblock_apply_fails
check "the failure message is actionable and points at the explicit migration surface" bash -c \
  "grep -q 'bindle migrate-legacy-global' '$BLOCK_LOG' && grep -q 'repository-scoped' '$BLOCK_LOG'"
check "Repo A: no repo-local core.hooksPath was installed (whole invocation aborted before mutating anything)" bash -c \
  "! git -C '$BLOCK_REPO_A' config --local --get core.hooksPath >/dev/null 2>&1"
check "the recognized legacy global core.hooksPath was NOT migrated away — it survives untouched" bash -c \
  "[ \"\$(git config --global --get core.hooksPath)\" = '$BLOCK_LEGACY_GIT_DIR' ] && [ -e '$BLOCK_LEGACY_GIT_DIR' ]"

# Repo B proves this isn't a one-shot: the legacy global state still blocks
# a SECOND, different repository's ordinary init exactly the same way — a
# single machine-global condition, not something the first invocation
# consumed or otherwise changed.
check "a normal --apply against a DIFFERENT repository (Repo B) is blocked identically by the same legacy global state" bash -c \
  "! '$INSTALLER' --apply --git-only --repo '$BLOCK_REPO_B' >/dev/null 2>&1"
check "Repo B: no repo-local core.hooksPath was installed either" bash -c \
  "! git -C '$BLOCK_REPO_B' config --local --get core.hooksPath >/dev/null 2>&1"

# The explicit migration mechanism (not a normal --apply) is what clears
# the block, positively-owned state only.
"$INSTALLER" --remove-legacy-global >/dev/null
check "explicit migration clears the recognized legacy global core.hooksPath" bash -c \
  '! git config --global --get core.hooksPath >/dev/null 2>&1'
check "a normal --apply against Repo A now succeeds once the legacy state is migrated away explicitly" bash -c \
  "'$INSTALLER' --apply --git-only --repo '$BLOCK_REPO_A' >/dev/null 2>&1"
check "Repo A: repo-local core.hooksPath is now installed" bash -c \
  "git -C '$BLOCK_REPO_A' config --local --get core.hooksPath >/dev/null 2>&1"

git config --global core.hooksPath /some/other/hook/manager
FOREIGN_REPO="$TMP/legacyblock-foreign-repo"
new_fixture "$FOREIGN_REPO"
check "a normal --apply never blocks on, touches, or fails because of an unrelated (foreign) global core.hooksPath" bash -c \
  "'$INSTALLER' --apply --git-only --repo '$FOREIGN_REPO' >/dev/null 2>&1"
check "the foreign global core.hooksPath is left completely untouched" bash -c \
  "[ \"\$(git config --global --get core.hooksPath)\" = /some/other/hook/manager ]"
git config --global --unset core.hooksPath

# ===========================================================================
echo "a plain --apply/--uninstall with no flags still does both layers, scoped to \$PWD:"

PLAIN_REPO="$TMP/plain-repo"
new_fixture "$PLAIN_REPO"

# shellcheck disable=SC2317,SC2329
plain_apply_from_repo_cwd() (
  cd "$PLAIN_REPO" || exit 1
  "$INSTALLER" --apply >/dev/null 2>&1
)
check "a plain --apply (no --repo, no --git-only) succeeds from inside a repository" \
  plain_apply_from_repo_cwd
check "it installed the Git layer for \$PWD" bash -c \
  "[ \"\$(git -C '$PLAIN_REPO' config --local --get core.hooksPath)\" = \"\$(git -C '$PLAIN_REPO' rev-parse --path-format=absolute --git-common-dir)/bindle-hooks\" ]"
PLAIN_CLAUDE_DIR="$(claude_dir_for "$PLAIN_REPO")"
check "it also installed the Claude layer for \$PWD" \
  test -e "$PLAIN_CLAUDE_DIR/claude-protected-main-guard"
check "it never touched the global core.hooksPath" bash -c \
  '! git config --global --get core.hooksPath >/dev/null 2>&1'

# ===========================================================================
echo ".claude/settings.local.json Git hygiene — not ignored yet:"

# A repository whose .gitignore says nothing about .claude/settings.local.json
# must not gain an accidentally-committable untracked file: --apply should
# record a machine-local ignore rule in the repo's own info/exclude instead
# of touching the repository's own tracked .gitignore.
UNIGNORED_REPO="$TMP/unignored-repo"
new_fixture "$UNIGNORED_REPO"
"$INSTALLER" --apply --claude-only --repo "$UNIGNORED_REPO" >/dev/null

check "settings.local.json was created" \
  test -f "$UNIGNORED_REPO/.claude/settings.local.json"
check "the repository's own .gitignore was NOT modified" bash -c \
  "[ ! -e '$UNIGNORED_REPO/.gitignore' ]"
check ".claude/settings.local.json is now ignored (via info/exclude)" bash -c \
  "git -C '$UNIGNORED_REPO' check-ignore -q -- .claude/settings.local.json"
check "info/exclude, not .gitignore, is the mechanism used" bash -c \
  "grep -qxF '.claude/settings.local.json' '$(git -C "$UNIGNORED_REPO" rev-parse --path-format=absolute --git-common-dir)/info/exclude'"

"$INSTALLER" --apply --claude-only --repo "$UNIGNORED_REPO" >/dev/null
check "re-applying does not duplicate the info/exclude entry" bash -c \
  "[ \"\$(grep -cxF '.claude/settings.local.json' '$(git -C "$UNIGNORED_REPO" rev-parse --path-format=absolute --git-common-dir)/info/exclude')\" = 1 ]"
check "the ownership marker for the info/exclude entry was recorded" \
  test -f "$(owned_exclude_file_for "$UNIGNORED_REPO")"

"$INSTALLER" --uninstall --claude-only --repo "$UNIGNORED_REPO" >/dev/null
check "--uninstall removed settings.local.json entirely (empty once Bindle's content was gone)" bash -c \
  "[ ! -e '$UNIGNORED_REPO/.claude/settings.local.json' ]"
check "--uninstall removed the Bindle-owned info/exclude entry it added" bash -c \
  "! grep -qxF '.claude/settings.local.json' '$(exclude_file_for "$UNIGNORED_REPO")' 2>/dev/null"
check "--uninstall removed the ownership marker" bash -c \
  "[ ! -e '$(owned_exclude_file_for "$UNIGNORED_REPO")' ]"
check "the path is no longer reported as ignored (the repo is back to its pre-init state)" bash -c \
  "! git -C '$UNIGNORED_REPO' check-ignore -q -- .claude/settings.local.json"

check "a repeated --apply/--uninstall cycle stays idempotent" bash -c \
  "'$INSTALLER' --apply --claude-only --repo '$UNIGNORED_REPO' >/dev/null &&
   '$INSTALLER' --apply --claude-only --repo '$UNIGNORED_REPO' >/dev/null &&
   '$INSTALLER' --uninstall --claude-only --repo '$UNIGNORED_REPO' >/dev/null &&
   '$INSTALLER' --uninstall --claude-only --repo '$UNIGNORED_REPO' >/dev/null"
check "after the repeated cycle, settings.local.json is gone again" bash -c \
  "[ ! -e '$UNIGNORED_REPO/.claude/settings.local.json' ]"
check "after the repeated cycle, no stray info/exclude entry or ownership marker remains" bash -c \
  "{ [ ! -f '$(exclude_file_for "$UNIGNORED_REPO")' ] || ! grep -qxF '.claude/settings.local.json' '$(exclude_file_for "$UNIGNORED_REPO")'; } &&
   [ ! -e '$(owned_exclude_file_for "$UNIGNORED_REPO")' ]"

# ===========================================================================
echo ".claude/settings.local.json Git hygiene — already ignored:"

# A repository that already ignores the file (its own .gitignore, Claude
# Code's own common convention) needs no info/exclude entry added.
IGNORED_REPO="$TMP/ignored-repo"
new_fixture "$IGNORED_REPO"
mkdir -p "$IGNORED_REPO/.claude"
printf '.claude/settings.local.json\n' >"$IGNORED_REPO/.gitignore"
git -C "$IGNORED_REPO" add .gitignore
git -C "$IGNORED_REPO" commit -q -m "ignore claude local settings"

"$INSTALLER" --apply --claude-only --repo "$IGNORED_REPO" >/dev/null
check "settings.local.json was created" \
  test -f "$IGNORED_REPO/.claude/settings.local.json"
check "no info/exclude entry was added (already ignored via .gitignore)" bash -c \
  "excl='$(git -C "$IGNORED_REPO" rev-parse --path-format=absolute --git-common-dir)/info/exclude'; [ ! -f \"\$excl\" ] || ! grep -qxF '.claude/settings.local.json' \"\$excl\""
check "no ownership marker was recorded (Bindle never claimed a rule it didn't add)" bash -c \
  "[ ! -e '$(owned_exclude_file_for "$IGNORED_REPO")' ]"

"$INSTALLER" --uninstall --claude-only --repo "$IGNORED_REPO" >/dev/null
check "--uninstall removed settings.local.json (empty once Bindle's content was gone)" bash -c \
  "[ ! -e '$IGNORED_REPO/.claude/settings.local.json' ]"
check "--uninstall left the repository's own .gitignore byte-for-byte unchanged" bash -c \
  "[ \"\$(cat '$IGNORED_REPO/.gitignore')\" = '.claude/settings.local.json' ]"
check "the path is still ignored after --uninstall (via the untouched .gitignore, not Bindle)" bash -c \
  "git -C '$IGNORED_REPO' check-ignore -q -- .claude/settings.local.json"

# ===========================================================================
echo ".claude/settings.local.json Git hygiene — a pre-existing info/exclude rule survives remove:"

# An info/exclude entry that predates 'bindle init' (added by the user, or
# by some other tool) must never be claimed as Bindle-owned, and so must
# survive '--uninstall' untouched — case 2 of the ownership contract.
PREEXIST_REPO="$TMP/preexist-exclude-repo"
new_fixture "$PREEXIST_REPO"
mkdir -p "$(dirname "$(exclude_file_for "$PREEXIST_REPO")")"
printf '.claude/settings.local.json\n' >"$(exclude_file_for "$PREEXIST_REPO")"

"$INSTALLER" --apply --claude-only --repo "$PREEXIST_REPO" >/dev/null
check "settings.local.json was created" \
  test -f "$PREEXIST_REPO/.claude/settings.local.json"
check "no ownership marker was recorded (the info/exclude entry predates this init)" bash -c \
  "[ ! -e '$(owned_exclude_file_for "$PREEXIST_REPO")' ]"

"$INSTALLER" --uninstall --claude-only --repo "$PREEXIST_REPO" >/dev/null
check "--uninstall removed settings.local.json (empty once Bindle's content was gone)" bash -c \
  "[ ! -e '$PREEXIST_REPO/.claude/settings.local.json' ]"
check "--uninstall left the pre-existing info/exclude entry in place (Bindle never owned it)" bash -c \
  "[ \"\$(grep -cxF '.claude/settings.local.json' '$(exclude_file_for "$PREEXIST_REPO")')\" = 1 ]"

# ===========================================================================
echo ".claude/settings.local.json Git hygiene — unrelated user content survives remove, ignore rule stays:"

# If settings.local.json still holds content Bindle doesn't own after
# --uninstall detaches its own entries, the file must not be deleted and
# its Bindle-owned info/exclude entry must not be removed either — doing
# either would make previously-hidden repository configuration
# accidentally committable.
UNRELATED_REPO="$TMP/unrelated-content-repo"
new_fixture "$UNRELATED_REPO"
"$INSTALLER" --apply --claude-only --repo "$UNRELATED_REPO" >/dev/null
check "the info/exclude entry was recorded as Bindle-owned" \
  test -f "$(owned_exclude_file_for "$UNRELATED_REPO")"

UNRELATED_SETTINGS="$(claude_settings_for "$UNRELATED_REPO")"
jq '. + {customUserSetting: "must-survive"}' "$UNRELATED_SETTINGS" >"$UNRELATED_SETTINGS.tmp"
mv "$UNRELATED_SETTINGS.tmp" "$UNRELATED_SETTINGS"

"$INSTALLER" --uninstall --claude-only --repo "$UNRELATED_REPO" >/dev/null
check "settings.local.json still exists (unrelated content preserved)" \
  test -f "$UNRELATED_SETTINGS"
check "the unrelated user setting survived --uninstall" bash -c \
  "[ \"\$(jq -r .customUserSetting '$UNRELATED_SETTINGS')\" = 'must-survive' ]"
check "Bindle's own PreToolUse guard entry was still removed" bash -c \
  "! jq -e '.hooks.PreToolUse | any(.matcher == \"Edit|Write|MultiEdit|NotebookEdit\")' '$UNRELATED_SETTINGS' >/dev/null 2>&1"
check "the info/exclude entry was left in place (deleting it would make the surviving file accidentally committable)" bash -c \
  "grep -qxF '.claude/settings.local.json' '$(exclude_file_for "$UNRELATED_REPO")'"
check "the ownership marker was left in place (nothing was safe to clean up yet)" \
  test -f "$(owned_exclude_file_for "$UNRELATED_REPO")"
check "the path is still reported as ignored" bash -c \
  "git -C '$UNRELATED_REPO' check-ignore -q -- .claude/settings.local.json"

# ===========================================================================
echo ".claude/settings.local.json Git hygiene — already tracked:"

# A repository that tracks the file (however unusual) is team-shared
# configuration Bindle must never rewrite silently.
TRACKED_REPO="$TMP/tracked-repo"
new_fixture "$TRACKED_REPO"
mkdir -p "$TRACKED_REPO/.claude"
printf '{}\n' >"$TRACKED_REPO/.claude/settings.local.json"
git -C "$TRACKED_REPO" add .claude/settings.local.json
git -C "$TRACKED_REPO" commit -q -m "track claude local settings"
TRACKED_BEFORE="$(cat "$TRACKED_REPO/.claude/settings.local.json")"

check "--apply refuses to run against a repo tracking settings.local.json" bash -c \
  "! '$INSTALLER' --apply --claude-only --repo '$TRACKED_REPO' >/dev/null 2>&1"
check "the tracked settings.local.json content is completely unchanged" bash -c \
  "[ \"\$(cat '$TRACKED_REPO/.claude/settings.local.json')\" = '$TRACKED_BEFORE' ]"
check "--uninstall also refuses to run against a repo tracking settings.local.json" bash -c \
  "! '$INSTALLER' --uninstall --claude-only --repo '$TRACKED_REPO' >/dev/null 2>&1"

# ===========================================================================
printf '\n  install-guardrails: %d/%d checks passed\n' "$pass" "$((pass + fail))"
exit "$fail"
