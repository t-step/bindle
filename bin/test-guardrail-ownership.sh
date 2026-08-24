#!/usr/bin/env bash
#
# test-guardrail-ownership.sh — regression suite for the cross-layer repo
# opt-in/opt-out contract install-guardrails.sh must satisfy as a whole:
#
#   Install Bindle on a machine -> arbitrary repositories remain untouched
#   cd some-repo; bindle init    -> that repo explicitly opts in (both layers)
#   bindle remove                -> that repo is genuinely opted back out
#
# Complements bin/test-git-hook-dispatch.sh (Git dispatcher mechanics) and
# bin/test-install-guardrails.sh (Claude-layer settings mechanics): this
# file proves the END-TO-END boundary — that opting in/out is real and
# repo-scoped for BOTH layers together, that a linked worktree resolves
# Claude settings the same way Claude Code itself does, and that a
# recognized legacy global install cannot survive an opt-out. Fully
# isolated (its own HOME) — never touches the real ~/.claude or
# ~/.local/share/bindle.
#
# Usage: bin/test-guardrail-ownership.sh
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

new_fixture() { # new_fixture DIR
  local dir="$1"
  rm -rf "$dir"
  git init -q --initial-branch=main "$dir"
  git -C "$dir" config user.email test@example.com
  git -C "$dir" config user.name Test
  git -C "$dir" commit -q --allow-empty -m init
}

claude_settings_for() { # claude_settings_for REPO
  local repo="$1" common root
  common="$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)"
  if [ "$(basename "$common")" = ".git" ]; then root="$(dirname "$common")"; else root="$common"; fi
  printf '%s' "$root/.claude/settings.local.json"
}

exclude_file_for() { # exclude_file_for REPO
  printf '%s/info/exclude' "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir)"
}

owned_exclude_file_for() { # owned_exclude_file_for REPO
  printf '%s/bindle-claude-exclude-owned' "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir)"
}

# shellcheck disable=SC2317,SC2329
commit_on_main_succeeds() (
  cd "$1" || exit 1
  echo "$2" >"$3"
  git add "$3"
  git commit -q -m attempt >/dev/null 2>&1
)
# shellcheck disable=SC2317,SC2329
commit_on_main_blocked() (
  cd "$1" || exit 1
  echo "$2" >"$3"
  git add "$3"
  ! git commit -q -m attempt >/dev/null 2>&1
)

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export BINDLE_GUARD_HOME="$TMP/legacy-guard-home"
export BINDLE_CLAUDE_HOME="$TMP/legacy-claude-home"
export HOME="$TMP/fake-home"
mkdir -p "$HOME"
git config --global user.email test@example.com
git config --global user.name Test

# ===========================================================================
echo "installing Bindle on the machine does not affect an uninitialized repository:"

UNINIT_REPO="$TMP/uninit-repo"
new_fixture "$UNINIT_REPO"
UNINIT_SETTINGS="$(claude_settings_for "$UNINIT_REPO")"

check "the never-initialized repo has no local core.hooksPath" bash -c \
  "! git -C '$UNINIT_REPO' config --local --get core.hooksPath >/dev/null 2>&1"
check "the never-initialized repo has no .claude/settings.local.json" bash -c \
  "[ ! -e '$UNINIT_SETTINGS' ]"
check "a direct commit on 'main' in the never-initialized repo succeeds" \
  commit_on_main_succeeds "$UNINIT_REPO" x f.txt

# ===========================================================================
echo "bindle init (--apply, both layers) opts one repository in, another stays untouched:"

REPO_A="$TMP/repo-a"
REPO_B="$TMP/repo-b"
new_fixture "$REPO_A"
new_fixture "$REPO_B"

"$INSTALLER" --apply --repo "$REPO_A" >/dev/null

check "Repo A: local core.hooksPath is set" bash -c \
  "git -C '$REPO_A' config --local --get core.hooksPath >/dev/null 2>&1"
check "Repo A: .claude/settings.local.json has the PreToolUse guard entry" bash -c \
  "jq -e '.hooks.PreToolUse | any(.matcher == \"Edit|Write|MultiEdit|NotebookEdit\")' '$(claude_settings_for "$REPO_A")' >/dev/null"
check "Repo A: a direct commit on 'main' is blocked" \
  commit_on_main_blocked "$REPO_A" x f.txt

check "Repo B: local core.hooksPath was never set (Repo A's init did not leak)" bash -c \
  "! git -C '$REPO_B' config --local --get core.hooksPath >/dev/null 2>&1"
check "Repo B: no .claude/settings.local.json exists" bash -c \
  "[ ! -e '$(claude_settings_for "$REPO_B")' ]"
check "Repo B: a direct commit on 'main' succeeds" \
  commit_on_main_succeeds "$REPO_B" x f.txt

# ===========================================================================
echo "bindle remove genuinely removes both layers — the repo is truly unprotected afterward:"

"$INSTALLER" --uninstall --repo "$REPO_A" >/dev/null

check "Repo A: local core.hooksPath is gone" bash -c \
  "! git -C '$REPO_A' config --local --get core.hooksPath >/dev/null 2>&1"
check "Repo A: the PreToolUse guard entry is gone" bash -c \
  "! jq -e '.hooks.PreToolUse | any(.matcher == \"Edit|Write|MultiEdit|NotebookEdit\")' '$(claude_settings_for "$REPO_A")' >/dev/null 2>&1"
check "Repo A: a direct commit on 'main' now succeeds (genuinely unprotected, no fallback)" \
  commit_on_main_succeeds "$REPO_A" y g.txt
check "Repo A: settings.local.json itself is gone (empty once Bindle's own content was removed)" bash -c \
  "[ ! -e '$(claude_settings_for "$REPO_A")' ]"
check "Repo A: the Bindle-owned info/exclude entry it added is gone too" bash -c \
  "! grep -qxF '.claude/settings.local.json' '$(exclude_file_for "$REPO_A")' 2>/dev/null"
check "Repo A: the info/exclude ownership marker is gone" bash -c \
  "[ ! -e '$(owned_exclude_file_for "$REPO_A")' ]"

# ===========================================================================
echo "a recognized legacy global install blocks (never silently migrates) a normal init/remove, for any repository (Git + Claude):"

TEMPLATE_REPO="$TMP/legacy-template-repo"
new_fixture "$TEMPLATE_REPO"
"$INSTALLER" --apply --repo "$TEMPLATE_REPO" >/dev/null
LEGACY_GIT_DIR="$TMP/legacy-global-git-hooks"
mv "$(git -C "$TEMPLATE_REPO" config --local --get core.hooksPath)" "$LEGACY_GIT_DIR"
git -C "$TEMPLATE_REPO" config --local --unset core.hooksPath
git config --global core.hooksPath "$LEGACY_GIT_DIR"

LEGACY_CLAUDE_DIR="$(git -C "$TEMPLATE_REPO" rev-parse --path-format=absolute --git-common-dir)/bindle-claude"
mkdir -p "$BINDLE_CLAUDE_HOME/hooks" "$BINDLE_GUARD_HOME/bin"
cp "$LEGACY_CLAUDE_DIR/claude-protected-main-guard" "$BINDLE_CLAUDE_HOME/hooks/bindle-protected-main-guard"
cp "$LEGACY_CLAUDE_DIR/allow-main-write.sh" "$BINDLE_GUARD_HOME/bin/allow-main-write.sh"
LEGACY_CMD="$BINDLE_CLAUDE_HOME/hooks/bindle-protected-main-guard $BINDLE_GUARD_HOME/bin/allow-main-write.sh"
cat >"$BINDLE_CLAUDE_HOME/settings.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [{"type": "command", "command": "$LEGACY_CMD", "timeout": 5}]}
    ]
  }
}
EOF

REPO_D="$TMP/repo-d"
REPO_E="$TMP/repo-e"
new_fixture "$REPO_D"
new_fixture "$REPO_E"

# bindle init on Repo E is repository-scoped: it must refuse to run (not
# silently migrate, and not silently proceed) while recognized legacy
# global state exists, and must leave that global state — and Repo E
# itself — completely untouched.
check "bindle init on Repo E fails while recognized legacy global state exists" bash -c \
  "! '$INSTALLER' --apply --repo '$REPO_E' >/dev/null 2>&1"
check "legacy global core.hooksPath was NOT migrated away by a normal init" bash -c \
  "[ \"\$(git config --global --get core.hooksPath)\" = '$LEGACY_GIT_DIR' ]"
check "legacy global Claude PreToolUse entry was NOT migrated away by a normal init" bash -c \
  "[ \"\$(jq '.hooks.PreToolUse | length' '$BINDLE_CLAUDE_HOME/settings.json')\" = 1 ]"
check "Repo E: no repo-local core.hooksPath was installed by the failed init" bash -c \
  "! git -C '$REPO_E' config --local --get core.hooksPath >/dev/null 2>&1"
check "Repo E: no .claude/settings.local.json was created by the failed init" bash -c \
  "[ ! -e '$(claude_settings_for "$REPO_E")' ]"

# The same recognized legacy global state blocks a DIFFERENT repository's
# init identically — it's genuinely machine-global, not consumed or
# otherwise changed by the first blocked attempt.
check "bindle init on a different repository (Repo D) is blocked identically" bash -c \
  "! '$INSTALLER' --apply --repo '$REPO_D' >/dev/null 2>&1"
check "Repo D: no repo-local core.hooksPath was installed either" bash -c \
  "! git -C '$REPO_D' config --local --get core.hooksPath >/dev/null 2>&1"

# Only the explicit, repo-independent migration command actually removes
# the recognized legacy global state.
"$INSTALLER" --remove-legacy-global >/dev/null
check "legacy global core.hooksPath was migrated away by the explicit migration command" bash -c \
  '! git config --global --get core.hooksPath >/dev/null 2>&1'
check "legacy global Claude PreToolUse entry was migrated away by the explicit migration command" bash -c \
  "[ \"\$(jq '.hooks.PreToolUse | length' '$BINDLE_CLAUDE_HOME/settings.json')\" = 0 ]"

"$INSTALLER" --apply --repo "$REPO_E" >/dev/null
check "bindle init on Repo E now succeeds once the legacy state is migrated away explicitly" bash -c \
  "git -C '$REPO_E' config --local --get core.hooksPath >/dev/null 2>&1"

"$INSTALLER" --uninstall --repo "$REPO_E" >/dev/null
check "Repo E: local core.hooksPath is gone after remove" bash -c \
  "! git -C '$REPO_E' config --local --get core.hooksPath >/dev/null 2>&1"
check "Repo E: global core.hooksPath did not reappear after remove" bash -c \
  '! git config --global --get core.hooksPath >/dev/null 2>&1'
check "Repo E: a direct commit on 'main' succeeds after remove (no legacy fallback)" \
  commit_on_main_succeeds "$REPO_E" z h.txt

# ===========================================================================
echo "linked worktrees: Claude settings resolve to the MAIN checkout, matching Claude Code's own behavior:"

# Claude Code documents that project settings are "resolved through
# worktrees to the main checkout" — install-guardrails.sh must write to
# the same place Claude Code will actually read, regardless of which
# worktree bindle was run from.
WT_REPO="$TMP/wt-repo"
new_fixture "$WT_REPO"
git -C "$WT_REPO" switch -q -c side-branch
WT_LINKED="$TMP/wt-repo-linked"
git -C "$WT_REPO" worktree add -q "$WT_LINKED" main

"$INSTALLER" --apply --repo "$WT_LINKED" >/dev/null

MAIN_SETTINGS="$(claude_settings_for "$WT_REPO")"
LINKED_SETTINGS="$(claude_settings_for "$WT_LINKED")"
check "the settings path resolved from the linked worktree matches the main checkout's own path" bash -c \
  "[ '$MAIN_SETTINGS' = '$LINKED_SETTINGS' ]"
check "settings.local.json was written under the MAIN checkout's .claude/, not the linked worktree's own" bash -c \
  "[ -f '$WT_REPO/.claude/settings.local.json' ] && [ ! -e '$WT_LINKED/.claude/settings.local.json' ]"
check "the PreToolUse guard entry is present at the resolved (main-checkout) settings path" bash -c \
  "jq -e '.hooks.PreToolUse | any(.matcher == \"Edit|Write|MultiEdit|NotebookEdit\")' '$MAIN_SETTINGS' >/dev/null"
check "a direct commit on 'main' from the linked worktree is blocked (Git layer, already proven worktree-shared)" \
  commit_on_main_blocked "$WT_LINKED" x wtf.txt
check "the info/exclude ownership marker lives in the shared common dir, reachable from the linked worktree" bash -c \
  "[ -f '$(owned_exclude_file_for "$WT_LINKED")' ]"

"$INSTALLER" --uninstall --repo "$WT_LINKED" >/dev/null
check "bindle remove run from the linked worktree cleans up the MAIN checkout's settings.local.json" bash -c \
  "[ ! -e '$MAIN_SETTINGS' ]"
check "bindle remove run from the linked worktree cleans up the Bindle-owned info/exclude entry" bash -c \
  "! grep -qxF '.claude/settings.local.json' '$(exclude_file_for "$WT_LINKED")' 2>/dev/null"
check "the info/exclude ownership marker is gone after remove from the linked worktree" bash -c \
  "[ ! -e '$(owned_exclude_file_for "$WT_LINKED")' ]"

git -C "$WT_REPO" worktree remove -f "$WT_LINKED"

# ===========================================================================
printf '\n  guardrail-ownership: %d/%d checks passed\n' "$pass" "$((pass + fail))"
exit "$fail"
