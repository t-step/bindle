#!/usr/bin/env bash
#
# allow-main-write.sh — mints a single-use token letting the NEXT
# Edit/Write/MultiEdit/NotebookEdit on 'main' in THIS worktree succeed, for the
# bindle-protected-main-guard hook.
#
# Run ONLY after the user explicitly authorizes modifying 'main' in the current
# conversation, never inferred. Distinct from the Git-layer ALLOW_MAIN_WRITE=1:
# tool calls cannot receive a command-scoped env var
# (plans/archive/2026-08-23-local-guardrail-layer.md, Decisions #2).
#
# Bound to repo + worktree + TTL; the guard consumes it on the next attempted
# use, valid or not, so it is never a standing "unlock main" switch. Not
# session-bound: no documented source shows CLAUDE_CODE_SESSION_ID equals
# PreToolUse's session_id, and an unverified binding would pose as a guarantee
# (same plan, Evidence).
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

# Temp file + same-fs mv: the guard never reads a partial token.
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
