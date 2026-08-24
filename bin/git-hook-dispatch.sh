#!/usr/bin/env bash
#
# git-hook-dispatch.sh — Bindle's single Git hook implementation. Installed
# once by bin/install-guardrails.sh and symlinked under every standard
# client-side Git hook name inside a global core.hooksPath directory, so
# this same file runs for every hook Git invokes, whichever name it was
# invoked as ($0's basename tells it).
#
# Rationale (plans/active/2026-08-23-local-guardrail-layer.md, "Decisions"
# #1): setting core.hooksPath globally redirects Git's hook lookup for
# EVERY hook name, not only the ones Bindle has policy for. A dispatcher
# that only existed for pre-commit/pre-merge-commit/pre-rebase would
# silently disable commit-msg (Cocogitto), post-commit/post-merge
# (projectmem), pre-push, and any repo-owned hook Bindle has no opinion
# about. This script is symlinked under the FULL standard hook-name surface
# so nothing is silently dropped: for hook names with Bindle policy it
# checks that policy first; for every hook name it transparently delegates
# to the repository's own hook of the same name afterward, if one exists.
#
# Policy-bearing hook names were chosen empirically, not by assumption — see
# the plan's evidence table. A plain `pre-commit` guard alone does NOT cover
# rebase-replay, cherry-pick, or `git commit --no-verify` (verified in fixture
# repos this session): rebase-replayed commits and cherry-picks skip
# pre-commit/commit-msg entirely, and --no-verify skips pre-commit too.
# prepare-commit-msg is the broadest single interception point observed
# (fires for commit, merge, rebase-replay, and cherry-pick, and survives
# --no-verify) but does not cover `git am`, which uses an entirely separate
# hook family (applypatch-msg/pre-applypatch/post-applypatch) — hence
# pre-applypatch is included too. pre-commit and pre-merge-commit are kept
# as well for a faster rejection in the common (non-bypass) case; the
# branch/override decision itself lives in one function below, not
# duplicated per hook.
#
set -euo pipefail

PROTECTED_BRANCH="main"

hook_name="$(basename "$0")"

# Nothing to protect or delegate to outside a Git working tree.
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

# current_branch — the branch HEAD currently points at, or empty when
# detached (detached HEAD is never treated as PROTECTED_BRANCH by name).
current_branch() {
  git symbolic-ref --quiet --short HEAD 2>/dev/null || true
}

# branch_under_mutation ARGS... — the branch this hook invocation is about
# to mutate. Every policy-bearing hook mutates the current branch EXCEPT
# pre-rebase, which receives the branch actually being rebased as $2 —
# present only when rebasing a branch other than the current one (git
# defaults $2 to the current branch and omits it).
branch_under_mutation() {
  if [ "$hook_name" = "pre-rebase" ] && [ -n "${2:-}" ]; then
    printf '%s\n' "$2"
  else
    current_branch
  fi
}

# check_protected_branch ARGS... — block if the branch under mutation is
# PROTECTED_BRANCH and ALLOW_MAIN_WRITE is not set. This is the ONE place
# the branch/override decision is made; every policy-bearing hook name below
# calls it, nothing re-implements the check.
check_protected_branch() {
  local target
  target="$(branch_under_mutation "$@")"
  [ "$target" = "$PROTECTED_BRANCH" ] || return 0
  [ -z "${ALLOW_MAIN_WRITE:-}" ] || return 0

  # An unborn branch (no commit yet — e.g. a brand-new `git init`) has no
  # established history to protect. Blocking it would block repository
  # bootstrap itself, which is not what "protect main from routine mutation"
  # means — the invariant is about an EXISTING clean integration branch.
  # Found empirically: a fixture repo's very first commit was being blocked,
  # which is the wrong behavior, not a stricter one.
  git rev-parse --verify --quiet HEAD >/dev/null 2>&1 || return 0

  local dirty_note=""
  if [ -n "$(git status --porcelain 2>/dev/null || true)" ]; then
    dirty_note=" '$PROTECTED_BRANCH' also has uncommitted changes — consider a branch so that work isn't lost."
  fi

  cat >&2 <<MSG
bindle guardrail: '$PROTECTED_BRANCH' is protected — blocked '$hook_name'.
$dirty_note
Create a branch from '$PROTECTED_BRANCH' first:
  git switch -c <branch-name>

If this write to '$PROTECTED_BRANCH' is genuinely intentional, scope the
override to this one command (it does not persist to the next command):
  ALLOW_MAIN_WRITE=1 <your original command>
MSG
  exit 1
}

case "$hook_name" in
pre-commit | pre-merge-commit | prepare-commit-msg | pre-rebase | pre-applypatch)
  check_protected_branch "$@"
  ;;
esac

# Transparent delegation: run the repository's OWN hook of this name, if it
# has one, with the original args/stdin, and let its exit status become
# ours. Resolved as a direct filesystem path (not another core.hooksPath
# lookup), so there is no recursion risk. --git-common-dir keeps this
# correct from any linked worktree (docs/WORKTREES.md): hooks are shared
# repository-level state, not per-worktree.
native_hook="$(git rev-parse --path-format=absolute --git-common-dir)/hooks/$hook_name"
if [ -x "$native_hook" ]; then
  exec "$native_hook" "$@"
fi
exit 0
