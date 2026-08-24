#!/usr/bin/env bash
#
# test-git-hook-dispatch.sh — regression suite for bin/git-hook-dispatch.sh
# and the git-layer half of bin/install-guardrails.sh, run against a fully
# isolated sandbox (its own HOME, guard install home, and fixture repos) so
# it never touches this machine's real ~/.claude or
# ~/.local/share/bindle (AGENTS.md "Runtime isolation").
#
# Usage: bin/test-git-hook-dispatch.sh
#
set -uo pipefail

# Same gotcha as bin/test-check-private-info.sh: under a git hook, git
# exports GIT_DIR and friends to subprocesses; a fixture git call would
# otherwise hit the real invoking repository.
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

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export BINDLE_GUARD_HOME="$TMP/guard-home"
export BINDLE_CLAUDE_HOME="$TMP/claude-home"
export HOME="$TMP/fake-home"
mkdir -p "$HOME"
git config --global user.email "test@example.com"
git config --global user.name "Test"
git config --global init.defaultBranch main

FIX="$TMP/fixture-repo"
new_fixture() {
  rm -rf "$FIX"
  git init -q --initial-branch=main "$FIX"
  git -C "$FIX" config user.email test@example.com
  git -C "$FIX" config user.name Test
  echo one >"$FIX/f.txt"
  git -C "$FIX" add f.txt
  git -C "$FIX" commit -q -m init
  "$INSTALLER" --apply --git-only --repo "$FIX" >/dev/null
}

# ===========================================================================
echo "install:"
new_fixture
check "install --apply --git-only --repo installs repo-locally" bash -c \
  "[ \"\$(git -C '$FIX' config --local --get core.hooksPath)\" = \"\$(git -C '$FIX' rev-parse --path-format=absolute --git-common-dir)/bindle-hooks\" ]"
check "install --apply is idempotent" "$INSTALLER" --apply --git-only --repo "$FIX" >/dev/null
check "the global core.hooksPath was never touched" bash -c \
  '! git config --global --get core.hooksPath >/dev/null 2>&1'

# ===========================================================================
echo "opt-in boundary: a repository that never ran the installer is unaffected:"

UNOPTED="$TMP/unopted-repo"
git init -q --initial-branch=main "$UNOPTED"
git -C "$UNOPTED" config user.email test@example.com
git -C "$UNOPTED" config user.name Test
echo one >"$UNOPTED/f.txt"
git -C "$UNOPTED" add f.txt
check "the very first commit on the never-opted-in repo succeeds" \
  git -C "$UNOPTED" commit -q -m init
check "a direct commit on 'main' in the never-opted-in repo is NOT blocked" bash -c "
  cd '$UNOPTED' &&
  echo x >second.txt &&
  git add second.txt &&
  git commit -q -m 'second, still on main'
"
check "the never-opted-in repo has no local core.hooksPath" bash -c \
  "! git -C '$UNOPTED' config --local --get core.hooksPath >/dev/null 2>&1"

# ===========================================================================
echo "protected-main boundaries:"

# shellcheck disable=SC2317,SC2329
commit_blocked() (
  cd "$FIX" || exit 1
  echo "$1" >"$2"
  git add "$2"
  ! git commit -q -m "attempt" >/dev/null 2>&1
)
# shellcheck disable=SC2317,SC2329
commit_allowed() (
  cd "$FIX" || exit 1
  echo "$1" >"$2"
  git add "$2"
  git commit -q -m "attempt" >/dev/null 2>&1
)

check "commit on main is blocked" commit_blocked x blocked1.txt

git -C "$FIX" switch -q -c feature
check "commit on a feature branch is allowed" commit_allowed x feature1.txt
git -C "$FIX" switch -q main

# shellcheck disable=SC2317,SC2329
override_allows() (
  cd "$FIX" || exit 1
  echo "$1" >"$2"
  git add "$2"
  ALLOW_MAIN_WRITE=1 git commit -q -m "authorized" >/dev/null 2>&1
)
check "ALLOW_MAIN_WRITE=1 permits the commit on main" override_allows x override1.txt
check "the override does not persist to the next command" commit_blocked x noleak.txt

check "branch creation from main is allowed" git -C "$FIX" switch -q -c another-branch main
git -C "$FIX" switch -q main

check "read-only ops on main are allowed" bash -c "
  git -C '$FIX' log --oneline >/dev/null &&
  git -C '$FIX' status >/dev/null &&
  git -C '$FIX' fetch --all >/dev/null 2>&1
"

git -C "$FIX" switch -q -c ff-src main
echo x >"$FIX/ff.txt"
git -C "$FIX" add ff.txt
git -C "$FIX" commit -q -m "ff commit"
git -C "$FIX" switch -q main
check "fast-forward sync of main is allowed" git -C "$FIX" merge -q --ff-only ff-src

# ===========================================================================
echo "mutation-path coverage (verified, not assumed):"

git -C "$FIX" switch -q -c cp-src main
echo x >"$FIX/cp.txt"
git -C "$FIX" add cp.txt
git -C "$FIX" commit -q -m "to cherry-pick"
CP_SHA="$(git -C "$FIX" rev-parse HEAD)"
git -C "$FIX" switch -q main
# shellcheck disable=SC2317,SC2329
cherry_pick_blocked() (
  cd "$FIX" || exit 1
  ! git cherry-pick "$CP_SHA" >/dev/null 2>&1
)
check "cherry-pick onto main is blocked" cherry_pick_blocked
git -C "$FIX" cherry-pick --abort >/dev/null 2>&1 || true

git -C "$FIX" switch -q -c am-src main
echo x >"$FIX/am.txt"
git -C "$FIX" add am.txt
git -C "$FIX" commit -q -m "for am"
git -C "$FIX" format-patch -1 --stdout HEAD >"$TMP/am.patch"
git -C "$FIX" switch -q main
# shellcheck disable=SC2317,SC2329
am_blocked() (
  cd "$FIX" || exit 1
  ! git am "$TMP/am.patch" >/dev/null 2>&1
)
check "git am onto main is blocked" am_blocked
git -C "$FIX" am --abort >/dev/null 2>&1 || true

git -C "$FIX" switch -q -c rb-onto main
echo x >"$FIX/rb.txt"
git -C "$FIX" add rb.txt
git -C "$FIX" commit -q -m "rebase target"
git -C "$FIX" switch -q main
# shellcheck disable=SC2317,SC2329
rebase_blocked() (
  cd "$FIX" || exit 1
  ! git rebase rb-onto >/dev/null 2>&1
)
check "rebase of main is blocked" rebase_blocked
git -C "$FIX" rebase --abort >/dev/null 2>&1 || true

# shellcheck disable=SC2317,SC2329
noverify_blocked() (
  cd "$FIX" || exit 1
  echo x >noverify.txt
  git add noverify.txt
  ! git commit --no-verify -q -m "attempt" >/dev/null 2>&1
)
check "'git commit --no-verify' does not bypass the guard on main" noverify_blocked

# ===========================================================================
echo "a brand-new repository's first commit is not blocked (unborn main):"

NEWREPO="$TMP/brand-new-repo"
git init -q --initial-branch=main "$NEWREPO"
git -C "$NEWREPO" config user.email test@example.com
git -C "$NEWREPO" config user.name Test
echo one >"$NEWREPO/f.txt"
git -C "$NEWREPO" add f.txt
check "the very first commit on a fresh 'main' is allowed" git -C "$NEWREPO" commit -q -m init

# ===========================================================================
echo "composition: repository-local hooks still fire through Bindle's repo-local layer:"

COMPOSE_LOG="$TMP/native-hooks-fired.log"
install_native_logger() {
  local name="$1"
  cat >"$FIX/.git/hooks/$name" <<EOF
#!/bin/sh
echo "FIRED:$name args=[\$*]" >>"$COMPOSE_LOG"
exit 0
EOF
  chmod +x "$FIX/.git/hooks/$name"
}
for h in commit-msg post-commit post-merge pre-commit; do
  install_native_logger "$h"
done

git -C "$FIX" switch -q -c compose-test main
: >"$COMPOSE_LOG"
echo x >"$FIX/compose.txt"
git -C "$FIX" add compose.txt
git -C "$FIX" commit -q -m "compose test"

check "repository's own commit-msg still fires through the repo-local layer" \
  grep -q "^FIRED:commit-msg" "$COMPOSE_LOG"
check "repository's own post-commit still fires through the repo-local layer" \
  grep -q "^FIRED:post-commit" "$COMPOSE_LOG"
check "repository's own pre-commit still fires through the repo-local layer" \
  grep -q "^FIRED:pre-commit" "$COMPOSE_LOG"

# Exit-code preservation: a rejecting native hook must still block the commit.
cat >"$FIX/.git/hooks/pre-commit" <<'EOF'
#!/bin/sh
exit 7
EOF
chmod +x "$FIX/.git/hooks/pre-commit"
# shellcheck disable=SC2317,SC2329
native_rejection_propagates() (
  cd "$FIX" || exit 1
  echo x >native-reject.txt
  git add native-reject.txt
  ! git commit -q -m "attempt" >/dev/null 2>&1
)
check "a rejecting repository-local pre-commit hook still blocks the commit" native_rejection_propagates
rm -f "$FIX/.git/hooks/pre-commit" "$FIX/.git/hooks/commit-msg" "$FIX/.git/hooks/post-commit" "$FIX/.git/hooks/post-merge"

# ===========================================================================
echo "installer safety:"

git -C "$FIX" config --local core.hooksPath /some/other/hook/manager
# shellcheck disable=SC2317,SC2329
apply_refuses_conflict() { ! "$INSTALLER" --apply --git-only --repo "$FIX" >/dev/null 2>&1; }
check "installer refuses to replace a pre-existing, different repo-local core.hooksPath" apply_refuses_conflict
check "the conflicting repo-local core.hooksPath is left untouched" bash -c \
  "[ \"\$(git -C '$FIX' config --local --get core.hooksPath)\" = /some/other/hook/manager ]"
git -C "$FIX" config --local --unset core.hooksPath
"$INSTALLER" --apply --git-only --repo "$FIX" >/dev/null

# ===========================================================================
echo "linked worktree: repo-local config is shared through the common directory:"

git -C "$FIX" switch -q -c side-branch main
WT="$TMP/fixture-repo-worktree"
git -C "$FIX" worktree add -q "$WT" main
check "the linked worktree inherits the SAME repo-local core.hooksPath (shared common-dir config)" bash -c \
  "[ \"\$(git -C '$WT' config --local --get core.hooksPath)\" = \"\$(git -C '$FIX' config --local --get core.hooksPath)\" ]"
# shellcheck disable=SC2317,SC2329
wt_commit_blocked() (
  cd "$WT" || exit 1
  echo x >wt-blocked.txt
  git add wt-blocked.txt
  ! git commit -q -m "attempt from worktree" >/dev/null 2>&1
)
check "a direct commit on 'main' from the linked worktree is blocked, without a separate install" wt_commit_blocked
git -C "$FIX" worktree remove -f "$WT"
git -C "$FIX" switch -q main
git -C "$FIX" branch -D side-branch >/dev/null

# ===========================================================================
echo "uninstall:"

"$INSTALLER" --uninstall --git-only --repo "$FIX" >/dev/null
check "uninstall clears the repo-local core.hooksPath" bash -c \
  "! git -C '$FIX' config --local --get core.hooksPath >/dev/null 2>&1"
check "uninstall removes the installed bindle-hooks directory" bash -c \
  "[ ! -d '$FIX/.git/bindle-hooks' ]"
check "uninstall never touched the global core.hooksPath" bash -c \
  '! git config --global --get core.hooksPath >/dev/null 2>&1'
"$INSTALLER" --apply --git-only --repo "$FIX" >/dev/null

# ===========================================================================
printf '\n  git-hook-dispatch: %d/%d checks passed\n' "$pass" "$((pass + fail))"
exit "$fail"
