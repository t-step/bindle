#!/usr/bin/env bash
#
# allow-main-write.sh — mints a single-use authorization token letting the
# NEXT Edit/Write/MultiEdit/NotebookEdit tool call on 'main' in THIS
# worktree succeed, for Claude Code's bindle-protected-main-guard hook.
#
# Run this ONLY after the user has explicitly authorized modifying 'main'
# in the current conversation — never inferred from the task. This is a
# distinct mechanism from the Git-layer ALLOW_MAIN_WRITE=1 override:
# Edit/Write/MultiEdit/NotebookEdit are tool calls, not shell invocations,
# so they cannot receive a command-scoped environment variable the way a
# Bash-issued `git commit` can. See
# plans/archive/2026-08-23-local-guardrail-layer.md, Decisions #2.
#
# The token is bound to repository identity, exact worktree, and a TTL as a
# stale-token backstop. The guard consumes it on the very next attempted
# use, valid or not — it never becomes a standing "unlock main" switch.
#
# Not session-bound: CLAUDE_CODE_SESSION_ID is observed in the Bash tool's
# subprocess environment on this machine, but no documented source
# establishes it carries the same value as PreToolUse's session_id field —
# see plans/archive/2026-08-23-local-guardrail-layer.md, Evidence. Binding to
# an unverified identifier would be a best-effort property presented as a
# guarantee, so the supported invariant is repo + worktree + TTL + single-use
# only.
#
# Usage: bin/allow-main-write.sh [--ttl SECONDS]
#
set -euo pipefail

TTL=300
if [ "${1:-}" = "--ttl" ]; then
  TTL="${2:?--ttl requires a value}"
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "allow-main-write: not inside a Git repository — nothing to authorize." >&2
  exit 1
fi

branch="$(git symbolic-ref --quiet --short HEAD || true)"
if [ "$branch" != "main" ]; then
  echo "allow-main-write: current branch is '${branch:-<detached HEAD>}', not 'main' — nothing to authorize (the guard only restricts 'main')." >&2
  exit 1
fi

common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
worktree="$(git rev-parse --show-toplevel)"
git_dir="$(git rev-parse --absolute-git-dir)"
now="$(date +%s)"
expires_at=$((now + TTL))

# Written atomically: build the full token in a same-directory temp file
# first, then rename it into place. A `mv` within one filesystem is a
# single rename syscall, so the guard reading $token_path can never observe
# a partially-written file — it either sees the complete prior token (if
# any) or the complete new one, never a truncated in-progress write.
token_path="$git_dir/bindle-allow-main-write.json"
tmp_token="$token_path.tmp.$$"
jq -n \
  --arg common_dir "$common_dir" \
  --arg worktree "$worktree" \
  --argjson created_at "$now" \
  --argjson expires_at "$expires_at" \
  '{common_dir: $common_dir, worktree: $worktree, created_at: $created_at, expires_at: $expires_at}' \
  >"$tmp_token"
mv "$tmp_token" "$token_path"

echo "allow-main-write: authorized ONE subsequent Edit/Write/MultiEdit/NotebookEdit on 'main' in $worktree, expiring in ${TTL}s or on first use, whichever comes first."
