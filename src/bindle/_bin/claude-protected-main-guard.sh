#!/usr/bin/env bash
#
# claude-protected-main-guard.sh — template for a Claude Code PreToolUse hook
# (matcher: Edit|Write|MultiEdit|NotebookEdit). Installed by
# bin/install-guardrails.sh as ~/.claude/hooks/bindle-protected-main-guard
# (copied, not symlinked — must keep working after this checkout is gone).
#
# Harness-level tripwire for the policy bin/git-hook-dispatch.sh enforces at the
# Git layer: blocks tracked-file mutation while the target repo is on 'main',
# with a one-shot escape hatch from bin/allow-main-write.sh (why it can't reuse
# ALLOW_MAIN_WRITE=1: plans/archive/2026-08-23-local-guardrail-layer.md,
# Decisions #2).
#
# Reads stdin JSON and emits a structured decision; never parses a command
# string.
#
# The one-shot token is bound to repo + worktree + TTL, not session: no
# documented source shows a Bash subprocess's session id equals PreToolUse's
# (same plan, Evidence).
#
set -euo pipefail

PROTECTED_BRANCH="main"
# Helper path arrives as $1 from settings.json (this guard runs for every repo,
# so a relative path would not resolve); the default keeps standalone runs
# working.
ALLOW_MAIN_WRITE_HELPER="${1:-$HOME/.local/share/bindle/bin/allow-main-write.sh}"

input="$(cat)"
cwd="$(jq -r '.cwd // empty' <<<"$input")"
file_path="$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' <<<"$input")"

deny() {
  jq -n --arg reason "$1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
  exit 0
}

# No resolvable target means no opinion: allow.
target_dir=""
if [ -n "$file_path" ]; then
  target_dir="$(dirname -- "$file_path")"
elif [ -n "$cwd" ]; then
  target_dir="$cwd"
else
  exit 0
fi

if ! git -C "$target_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

branch="$(git -C "$target_dir" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [ "$branch" != "$PROTECTED_BRANCH" ]; then
  exit 0
fi

common_dir="$(git -C "$target_dir" rev-parse --path-format=absolute --git-common-dir)"
worktree="$(git -C "$target_dir" rev-parse --show-toplevel)"
git_dir="$(git -C "$target_dir" rev-parse --absolute-git-dir)"
token_path="$git_dir/bindle-allow-main-write.json"

deny_message="bindle guardrail: '$PROTECTED_BRANCH' is protected — this edit was blocked. Branch first (bindle branch <name>), or — only after the user has explicitly authorized a one-off edit to '$PROTECTED_BRANCH' in this conversation — run '$ALLOW_MAIN_WRITE_HELPER' in $worktree, then retry."

if [ ! -e "$token_path" ]; then
  deny "$deny_message"
fi

# mv is the portable exclusive claim; consumed even if invalid (Decisions #2).
claim_path="${token_path}.claimed.$$"
if ! mv "$token_path" "$claim_path" 2>/dev/null; then
  deny "$deny_message"
fi

# Fail closed: a malformed, truncated, unreadable or wrong-typed token means "no
# valid authorization", never a jq error aborting under set -e.
# `cat` rather than a redirection so an unreadable file's error stays ours to
# suppress; it yields empty content and fails the check below.
claim_content="$(cat "$claim_path" 2>/dev/null)" || claim_content=""
rm -f "$claim_path"
if ! jq -e '
    type == "object"
    and (.common_dir | type == "string" and length > 0)
    and (.worktree | type == "string" and length > 0)
    and (.expires_at | type == "number" and . == (. | floor))
  ' >/dev/null 2>&1 <<<"$claim_content"; then
  deny "$deny_message (a pending authorization exists but is malformed)"
fi

token_common_dir="$(jq -r '.common_dir' <<<"$claim_content")"
token_worktree="$(jq -r '.worktree' <<<"$claim_content")"
token_expires_at="$(jq -r '.expires_at' <<<"$claim_content")"

now="$(date +%s)"

if [ "$token_common_dir" != "$common_dir" ] || [ "$token_worktree" != "$worktree" ]; then
  deny "$deny_message (a pending authorization exists but does not match this repository/worktree)"
fi
if [ "$now" -gt "$token_expires_at" ]; then
  deny "$deny_message (the pending authorization expired)"
fi

exit 0
