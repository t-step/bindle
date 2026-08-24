#!/usr/bin/env bash
#
# test-claude-protected-main-guard.sh — regression suite for
# bin/claude-protected-main-guard.sh and bin/allow-main-write.sh, driven with
# synthetic PreToolUse stdin JSON (the same shape documented for Claude Code
# hooks and used by ~/.claude/hooks/subagent-limit-guard on this machine) —
# no live Claude Code session is needed. Fully isolated: its own HOME and
# fixture repos, never the real ~/.claude or ~/.local/share/bindle.
#
# Usage: bin/test-claude-protected-main-guard.sh
#
set -uo pipefail

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUARD="$REPO_ROOT/bin/claude-protected-main-guard.sh"
HELPER="$REPO_ROOT/bin/allow-main-write.sh"

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

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/fake-home"
mkdir -p "$HOME"
git config --global user.email test@example.com
git config --global user.name Test

FIX="$TMP/fixture-repo"
git init -q --initial-branch=main "$FIX"
git -C "$FIX" config user.email test@example.com
git -C "$FIX" config user.name Test
echo one >"$FIX/f.txt"
git -C "$FIX" add f.txt
git -C "$FIX" commit -q -m init

# guard_input FILE — the stdin JSON a PreToolUse Edit call carries.
# shellcheck disable=SC2317,SC2329
guard_input() {
  jq -n --arg cwd "$FIX" --arg fp "$1" \
    '{cwd: $cwd, tool_name: "Edit", tool_input: {file_path: $fp}}'
}

# guard_decision FILE — "allow" (empty stdout) or "deny".
# shellcheck disable=SC2317,SC2329
guard_decision() {
  local out
  out="$(guard_input "$1" | "$GUARD" "$HELPER")"
  if [ -z "$out" ]; then
    echo allow
  else
    jq -r '.hookSpecificOutput.permissionDecision' <<<"$out"
  fi
}

# guard_denies_cleanly FILE — true only if the guard exits 0 AND produces a
# well-formed deny decision. A bare "was stdout empty?" check (guard_decision
# above) cannot tell a real "allow" apart from an unhandled crash (nonzero
# exit, no output) — this distinguishes them, which is exactly what the
# fail-closed malformed-token behavior below needs to prove.
# shellcheck disable=SC2317,SC2329
guard_denies_cleanly() {
  local out rc
  out="$(guard_input "$1" | "$GUARD" "$HELPER" 2>/dev/null)"
  rc=$?
  [ "$rc" -eq 0 ] || return 1
  jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1 <<<"$out"
}

# ===========================================================================
echo "branch gating:"

# shellcheck disable=SC2317,SC2329
edit_on_main_denied() { [ "$(guard_decision "$FIX/f.txt")" = deny ]; }
check "edit on main is denied" edit_on_main_denied

git -C "$FIX" switch -q -c feature-branch
# shellcheck disable=SC2317,SC2329
edit_after_branch_allowed() { [ "$(guard_decision "$FIX/f.txt")" = allow ]; }
check "edit after branching off main is allowed" edit_after_branch_allowed
git -C "$FIX" switch -q main

# shellcheck disable=SC2317,SC2329
edit_outside_git_allowed() { [ "$(cd /tmp && echo '{}' | "$GUARD" "$HELPER")" = "" ]; }
check "a tool call with no resolvable Git repo is allowed (not this guard's concern)" edit_outside_git_allowed

# ===========================================================================
echo "one-shot authorization capability:"

(cd "$FIX" && "$HELPER" >/dev/null)
# shellcheck disable=SC2317,SC2329
first_use_allowed() { [ "$(guard_decision "$FIX/f.txt")" = allow ]; }
check "a freshly minted token allows exactly one edit on main" first_use_allowed

# shellcheck disable=SC2317,SC2329
second_use_denied() { [ "$(guard_decision "$FIX/f.txt")" = deny ]; }
check "the same token cannot be used a second time" second_use_denied

(cd "$FIX" && "$HELPER" --ttl 1 >/dev/null)
sleep 2
# shellcheck disable=SC2317,SC2329
expired_denied() { [ "$(guard_decision "$FIX/f.txt")" = deny ]; }
check "an expired token is denied" expired_denied

# A token whose recorded worktree/common_dir does not match the current
# repository is denied even though it is otherwise well-formed and unexpired
# — content-validated, not just presence-checked (defense in depth beyond
# the physical per-worktree token path).
GIT_DIR_ABS="$(git -C "$FIX" rev-parse --absolute-git-dir)"
jq -n --arg common_dir "$(git -C "$FIX" rev-parse --path-format=absolute --git-common-dir)" \
  --arg worktree "/nonexistent/other/worktree" \
  --argjson created_at 1 --argjson expires_at 9999999999 \
  '{common_dir: $common_dir, worktree: $worktree, created_at: $created_at, expires_at: $expires_at}' \
  >"$GIT_DIR_ABS/bindle-allow-main-write.json"
# shellcheck disable=SC2317,SC2329
wrong_worktree_denied() { [ "$(guard_decision "$FIX/f.txt")" = deny ]; }
check "a token recorded for a different worktree is denied" wrong_worktree_denied
check "a mismatched token is consumed on the attempt, not left behind" bash -c \
  "[ ! -e '$GIT_DIR_ABS/bindle-allow-main-write.json' ]"

# ===========================================================================
echo "fail-closed against a malformed token (never an unhandled crash):"

TOKEN_PATH="$(git -C "$FIX" rev-parse --absolute-git-dir)/bindle-allow-main-write.json"

# shellcheck disable=SC2317,SC2329
check_malformed_token() { # check_malformed_token DESCRIPTION CONTENT
  local desc="$1" content="$2"
  printf '%s' "$content" >"$TOKEN_PATH"
  check "$desc" guard_denies_cleanly "$FIX/f.txt"
  check "$desc — token file is consumed, not left behind" bash -c "[ ! -e '$TOKEN_PATH' ]"
}

check_malformed_token "a completely empty token file is denied cleanly" ""
check_malformed_token "truncated/incomplete JSON is denied cleanly" '{"common_dir": "/x", "wor'
check_malformed_token "a JSON array instead of an object is denied cleanly" '[1,2,3]'
check_malformed_token "a non-numeric expires_at is denied cleanly" \
  '{"common_dir":"/x","worktree":"/y","expires_at":"not-a-number"}'
check_malformed_token "a fractional expires_at is denied cleanly" \
  '{"common_dir":"/x","worktree":"/y","expires_at":300.5}'
check_malformed_token "a missing common_dir field is denied cleanly" \
  '{"worktree":"/y","expires_at":9999999999}'

# An unreadable token (e.g. a permissions problem, not a content problem)
# must fail closed the same way — deny cleanly, never crash the hook.
printf '{"common_dir":"/x","worktree":"/y","expires_at":9999999999}' >"$TOKEN_PATH"
chmod 000 "$TOKEN_PATH"
check "an unreadable token file is denied cleanly, not an unhandled crash" \
  guard_denies_cleanly "$FIX/f.txt"
chmod 644 "$TOKEN_PATH" 2>/dev/null || true
rm -f "$TOKEN_PATH"

# ===========================================================================
echo "concurrency: exactly one of two simultaneous invocations may consume a token:"

git -C "$FIX" switch -q main
(cd "$FIX" && "$HELPER" >/dev/null)

CONCURRENT_OUT_1="$TMP/concurrent-out-1"
CONCURRENT_OUT_2="$TMP/concurrent-out-2"
guard_input "$FIX/f.txt" | "$GUARD" "$HELPER" >"$CONCURRENT_OUT_1" 2>/dev/null &
concurrent_pid_1=$!
guard_input "$FIX/f.txt" | "$GUARD" "$HELPER" >"$CONCURRENT_OUT_2" 2>/dev/null &
concurrent_pid_2=$!
wait "$concurrent_pid_1"
wait "$concurrent_pid_2"

# shellcheck disable=SC2317,SC2329
exactly_one_concurrent_allow() {
  local allowed=0
  [ -s "$CONCURRENT_OUT_1" ] || allowed=$((allowed + 1))
  [ -s "$CONCURRENT_OUT_2" ] || allowed=$((allowed + 1))
  [ "$allowed" -eq 1 ]
}
check "exactly one of two simultaneous invocations was allowed" exactly_one_concurrent_allow

# shellcheck disable=SC2317,SC2329
exactly_one_concurrent_deny() {
  local denied=0
  jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1 <"$CONCURRENT_OUT_1" &&
    denied=$((denied + 1))
  jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1 <"$CONCURRENT_OUT_2" &&
    denied=$((denied + 1))
  [ "$denied" -eq 1 ]
}
check "the other simultaneous invocation was denied, not silently dropped" exactly_one_concurrent_deny
check "no claim/token artifact is left behind after the race" bash -c \
  "[ ! -e '$TOKEN_PATH' ] && [ -z \"\$(find '$(dirname "$TOKEN_PATH")' -maxdepth 1 -name '*.claimed.*')\" ]"

# ===========================================================================
echo "allow-main-write.sh helper:"

git -C "$FIX" switch -q feature-branch
# shellcheck disable=SC2317,SC2329
helper_refuses_off_main() { ! (cd "$FIX" && "$HELPER") >/dev/null 2>&1; }
check "the helper refuses to mint a token when not on 'main'" helper_refuses_off_main
git -C "$FIX" switch -q main

# shellcheck disable=SC2317,SC2329
helper_requires_git_repo() { ! (cd "$TMP" && "$HELPER") >/dev/null 2>&1; }
check "the helper refuses outside a Git repository" helper_requires_git_repo

# ===========================================================================
printf '\n  claude-protected-main-guard: %d/%d checks passed\n' "$pass" "$((pass + fail))"
exit "$fail"
