#!/usr/bin/env bash
#
# claude-protected-main-guard.sh — template for a Claude Code PreToolUse
# hook (matcher: Edit|Write|MultiEdit|NotebookEdit). Installed by
# bin/install-guardrails.sh as ~/.claude/hooks/bindle-protected-main-guard
# (copied, not symlinked — must keep working after this checkout is gone).
#
# Earlier, harness-specific tripwire for the same policy the Git layer
# (bin/git-hook-dispatch.sh) enforces underneath it: blocks tracked-file
# mutation while the target repository's current branch is 'main', with a
# one-shot escape hatch minted by bin/allow-main-write.sh — see
# plans/active/2026-08-23-local-guardrail-layer.md, Decisions #2, for why
# this can't just reuse the Git layer's ALLOW_MAIN_WRITE=1 env var.
#
# Reads the same stdin-JSON / structured-decision shape as the existing
# ~/.claude/hooks/subagent-limit-guard on this machine: never parses a
# command string, only semantic fields the harness provides.
#
# The one-shot capability is bound to repository + worktree + TTL only, not
# session — no documented source establishes that the session identifier a
# Bash subprocess can observe is the same identifier PreToolUse hooks receive
# on stdin, and a best-effort binding here would be a security property
# masquerading as a guaranteed one. See
# plans/active/2026-08-23-local-guardrail-layer.md, Evidence.
#
set -euo pipefail

PROTECTED_BRANCH="main"
# The helper's installed location is passed as $1 by the settings.json
# command line (bin/install-guardrails.sh writes it explicitly, since this
# guard applies to every repo on the machine, not just the one it happens to
# be checked out from — a relative "bin/allow-main-write.sh" would only
# resolve inside the Bindle checkout itself). Falls back to the default
# install location so the script is still runnable standalone for testing.
ALLOW_MAIN_WRITE_HELPER="${1:-$HOME/.local/share/bindle/bin/allow-main-write.sh}"

input="$(cat)"
cwd="$(jq -r '.cwd // empty' <<<"$input")"
file_path="$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' <<<"$input")"

deny() {
  jq -n --arg reason "$1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
  exit 0
}

# Resolve the target directory: the edited file's directory when known,
# else the tool call's reported cwd. If neither is available, there is
# nothing to check against — allow (this hook has no opinion outside a
# resolvable Git repository).
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

deny_message="bindle guardrail: '$PROTECTED_BRANCH' is protected — this edit was blocked. Branch first (git switch -c <name>), or — only after the user has explicitly authorized a one-off edit to '$PROTECTED_BRANCH' in this conversation — run '$ALLOW_MAIN_WRITE_HELPER' in $worktree, then retry."

if [ ! -e "$token_path" ]; then
  deny "$deny_message"
fi

# Atomic single-consumer claim: an mv-based rename either succeeds exclusively
# or fails cleanly if another concurrent invocation already claimed it — the
# smallest portable exclusive-claim mechanism available here. The token is
# consumed by this claim regardless of whether it goes on to validate, so a
# stale or mismatched token can never be reused (Decisions #2).
claim_path="${token_path}.claimed.$$"
if ! mv "$token_path" "$claim_path" 2>/dev/null; then
  deny "$deny_message"
fi

# Fail closed on anything but a well-formed token: a truncated write (a
# process killed mid-mint, before bin/allow-main-write.sh's own atomic
# rename lands — see its header), hand-edited garbage, an unreadable file
# (permissions), or a value of the wrong type must all be treated as "no
# valid authorization," never let `jq`'s failure escape as an unhandled
# error under `set -e` and abort the hook without a decision. Read via
# `cat` (not a file redirection) so an unreadable file's error is ours to
# suppress rather than a bash-level redirection failure printed regardless
# of this script's own stderr handling; an unreadable file then simply
# yields empty content, which fails the structural check below like any
# other malformed body. A single check up front means the extraction after
# it can trust the shape and never needs its own per-field fallback.
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
