#!/usr/bin/env bash
#
# test-packaged-install.sh — proves `bindle init`/`bindle remove` work from
# a normally-installed Bindle package, not merely from `uv run` inside this
# source checkout. Builds the wheel via the repository's normal build path
# (`uv build`), installs it into a throwaway, fully isolated virtualenv,
# and exercises the guardrail lifecycle exactly as an end user would: an
# arbitrary cwd, no source checkout in sight.
#
# Requires `uv` on PATH and network-free wheel building (this repo has no
# runtime dependencies). Skips (exit 0, clearly reported) rather than
# failing the whole gate if `uv` is unavailable — packaging verification
# degrades gracefully in an environment that can't build/install at all,
# rather than blocking every other check.
#
# Usage: bin/test-packaged-install.sh
#
set -uo pipefail

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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

if ! command -v uv >/dev/null 2>&1; then
  printf '  - uv not found on PATH — skipping packaged-install verification\n'
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ===========================================================================
echo "building the wheel via the repository's normal build path:"

BUILD_LOG="$TMP/build.log"
check "uv build succeeds" bash -c \
  "cd '$REPO_ROOT' && uv build --out-dir '$TMP/dist' >'$BUILD_LOG' 2>&1"

WHEEL="$(find "$TMP/dist" -maxdepth 1 -name '*.whl' 2>/dev/null | head -n1)"
check "a wheel was produced" bash -c "[ -n '$WHEEL' ] && [ -f '$WHEEL' ]"

if [ -z "$WHEEL" ]; then
  printf '\n  packaged-install: %d/%d checks passed (build failed, skipping install phase)\n' "$pass" "$((pass + fail + 1))"
  exit 1
fi

check "the wheel bundles every guardrail runtime asset" bash -c \
  "unzip -l '$WHEEL' | grep -q 'bindle/_bin/install-guardrails.sh' &&
   unzip -l '$WHEEL' | grep -q 'bindle/_bin/git-hook-dispatch.sh' &&
   unzip -l '$WHEEL' | grep -q 'bindle/_bin/claude-protected-main-guard.sh' &&
   unzip -l '$WHEEL' | grep -q 'bindle/_bin/allow-main-write.sh' &&
   unzip -l '$WHEEL' | grep -q 'bindle/_bin/settings_json.py'"

# ===========================================================================
echo "installing the wheel into an isolated venv, outside this source checkout:"

VENV="$TMP/venv"
check "uv venv succeeds" bash -c "uv venv --python 3.11 '$VENV' >/dev/null 2>&1"
check "uv pip install succeeds" bash -c \
  "'$VENV/bin/python' -m ensurepip --upgrade >/dev/null 2>&1; uv pip install --python '$VENV/bin/python' '$WHEEL' >/dev/null 2>&1"

BINDLE_BIN="$VENV/bin/bindle"
check "the installed bindle entry point exists" bash -c "[ -x '$BINDLE_BIN' ]"

PKG_LOCATION="$("$VENV/bin/python" -c 'import bindle, os; print(os.path.dirname(bindle.__file__))' 2>/dev/null)"
# shellcheck disable=SC2317,SC2329
pkg_location_outside_checkout() {
  [ -n "$PKG_LOCATION" ] && [ "${PKG_LOCATION#"$REPO_ROOT"}" = "$PKG_LOCATION" ]
}
check "the installed bindle package resolves outside this source checkout" \
  pkg_location_outside_checkout

# ===========================================================================
echo "exercising bindle init/remove from the installed artifact, from an arbitrary cwd:"

export HOME="$TMP/fake-home"
mkdir -p "$HOME"
git config --global user.email test@example.com
git config --global user.name Test
git config --global init.defaultBranch main

REPO_A="$TMP/repo-a"
git init -q "$REPO_A"
git -C "$REPO_A" commit -q --allow-empty -m init
REPO_B="$TMP/repo-b"
git init -q "$REPO_B"
git -C "$REPO_B" commit -q --allow-empty -m init

# shellcheck disable=SC2317,SC2329
installed_init_repo_a() (
  cd "$REPO_A" || exit 1
  "$BINDLE_BIN" init >/dev/null 2>&1
)
check "bindle init succeeds against Repo A from the installed artifact" installed_init_repo_a
check "Repo A: local core.hooksPath is set" bash -c \
  "git -C '$REPO_A' config --local --get core.hooksPath >/dev/null 2>&1"
check "Repo A: .claude/settings.local.json has the PreToolUse guard entry" bash -c \
  "jq -e '.hooks.PreToolUse | any(.matcher == \"Edit|Write|MultiEdit|NotebookEdit\")' '$REPO_A/.claude/settings.local.json' >/dev/null"

# shellcheck disable=SC2317,SC2329
commit_on_main_blocked() (
  cd "$1" || exit 1
  echo x >f.txt
  git add f.txt
  ! git commit -q -m attempt >/dev/null 2>&1
)
# shellcheck disable=SC2317,SC2329
commit_on_main_succeeds() (
  cd "$1" || exit 1
  echo x >f.txt
  git add f.txt
  git commit -q -m attempt >/dev/null 2>&1
)
check "Repo A: a direct commit on 'main' is blocked" commit_on_main_blocked "$REPO_A"
check "Repo B (never initialized): a direct commit on 'main' succeeds" commit_on_main_succeeds "$REPO_B"

# shellcheck disable=SC2317,SC2329
installed_remove_repo_a() (
  cd "$REPO_A" || exit 1
  "$BINDLE_BIN" remove >/dev/null 2>&1
)
check "bindle remove succeeds against Repo A from the installed artifact" installed_remove_repo_a
check "Repo A: local core.hooksPath is gone after remove" bash -c \
  "! git -C '$REPO_A' config --local --get core.hooksPath >/dev/null 2>&1"
check "Repo A: a direct commit on 'main' succeeds after remove" commit_on_main_succeeds "$REPO_A"

NOT_A_REPO="$TMP/not-a-repo"
mkdir -p "$NOT_A_REPO"
# shellcheck disable=SC2317,SC2329
installed_init_outside_repo_fails() (
  cd "$NOT_A_REPO" || exit 1
  ! "$BINDLE_BIN" init >/dev/null 2>&1
)
check "bindle init outside a Git repository fails clearly (installed artifact)" \
  installed_init_outside_repo_fails
check "global core.hooksPath was never touched by any of this" bash -c \
  '! git config --global --get core.hooksPath >/dev/null 2>&1'

# ===========================================================================
echo "bindle migrate-legacy-global from the installed artifact:"

# A recognized legacy global install (built by reusing the installed
# artifact itself, then relocated the way the pre-rework installer would
# have left it) must block a normal installed `bindle init`, and only
# `bindle migrate-legacy-global` (not init/remove) may clear it.
LEGACY_TEMPLATE="$TMP/legacy-template"
git init -q "$LEGACY_TEMPLATE"
git -C "$LEGACY_TEMPLATE" commit -q --allow-empty -m init
# shellcheck disable=SC2317,SC2329
installed_init_legacy_template() (
  cd "$LEGACY_TEMPLATE" || exit 1
  "$BINDLE_BIN" init >/dev/null 2>&1
)
check "bindle init succeeds against the legacy-template repo (installed artifact)" \
  installed_init_legacy_template

LEGACY_GLOBAL_GIT_DIR="$TMP/legacy-global-git-hooks"
mv "$(git -C "$LEGACY_TEMPLATE" config --local --get core.hooksPath)" "$LEGACY_GLOBAL_GIT_DIR"
git -C "$LEGACY_TEMPLATE" config --local --unset core.hooksPath
git config --global core.hooksPath "$LEGACY_GLOBAL_GIT_DIR"

REPO_C="$TMP/repo-c"
git init -q "$REPO_C"
git -C "$REPO_C" commit -q --allow-empty -m init
# shellcheck disable=SC2317,SC2329
installed_init_repo_c_blocked_by_legacy() (
  cd "$REPO_C" || exit 1
  ! "$BINDLE_BIN" init >/dev/null 2>&1
)
check "bindle init against Repo C is blocked while recognized legacy global state exists (installed artifact)" \
  installed_init_repo_c_blocked_by_legacy
check "Repo C: no repo-local core.hooksPath was installed by the blocked init" bash -c \
  "! git -C '$REPO_C' config --local --get core.hooksPath >/dev/null 2>&1"
check "the recognized legacy global core.hooksPath was NOT migrated away by the blocked init" bash -c \
  "[ \"\$(git config --global --get core.hooksPath)\" = '$LEGACY_GLOBAL_GIT_DIR' ]"

# shellcheck disable=SC2317,SC2329
installed_migrate_legacy_global() (
  "$BINDLE_BIN" migrate-legacy-global >/dev/null 2>&1
)
check "bindle migrate-legacy-global succeeds from the installed artifact" \
  installed_migrate_legacy_global
check "the recognized legacy global core.hooksPath is gone after explicit migration" bash -c \
  '! git config --global --get core.hooksPath >/dev/null 2>&1'

# shellcheck disable=SC2317,SC2329
installed_init_repo_c_now_succeeds() (
  cd "$REPO_C" || exit 1
  "$BINDLE_BIN" init >/dev/null 2>&1
)
check "bindle init against Repo C now succeeds once the legacy state is migrated away" \
  installed_init_repo_c_now_succeeds
check "Repo C: repo-local core.hooksPath is now set" bash -c \
  "git -C '$REPO_C' config --local --get core.hooksPath >/dev/null 2>&1"

# ===========================================================================
echo "bindle init/remove/migrate-legacy-global work with no jq on PATH:"

# The Claude-layer JSON merge is a package-owned Python helper
# (settings_json.py, run under BINDLE_PYTHON — see src/bindle/cli.py), not
# jq. Prove it by constructing a PATH with every currently-reachable
# executable EXCEPT jq (flattened into one directory, first-found-wins, so
# PATH precedence for duplicate names is preserved) and exercising the
# installed artifact against it.
NOJQ_PATH_DIR="$TMP/path-without-jq"
mkdir -p "$NOJQ_PATH_DIR"
_old_ifs="$IFS"
IFS=':'
for d in $PATH; do
  [ -d "$d" ] || continue
  for f in "$d"/*; do
    [ -e "$f" ] || continue
    b="$(basename "$f")"
    [ "$b" = "jq" ] && continue
    [ -e "$NOJQ_PATH_DIR/$b" ] && continue
    ln -s "$f" "$NOJQ_PATH_DIR/$b" 2>/dev/null || true
  done
done
IFS="$_old_ifs"
check "jq is genuinely absent from the constructed PATH" bash -c \
  "! PATH='$NOJQ_PATH_DIR' command -v jq >/dev/null 2>&1"

REPO_D="$TMP/repo-d"
git init -q "$REPO_D"
git -C "$REPO_D" commit -q --allow-empty -m init
# shellcheck disable=SC2317,SC2329
nojq_init_repo_d() (
  cd "$REPO_D" || exit 1
  PATH="$NOJQ_PATH_DIR" "$BINDLE_BIN" init >/dev/null 2>&1
)
check "bindle init succeeds against Repo D with no jq on PATH" nojq_init_repo_d
check "Repo D: local core.hooksPath is set (no jq)" bash -c \
  "git -C '$REPO_D' config --local --get core.hooksPath >/dev/null 2>&1"
check "Repo D: .claude/settings.local.json has the PreToolUse guard entry (no jq)" \
  "$VENV/bin/python" -c "
import json, sys
d = json.load(open('$REPO_D/.claude/settings.local.json'))
entries = d.get('hooks', {}).get('PreToolUse', [])
sys.exit(0 if any(e.get('matcher') == 'Edit|Write|MultiEdit|NotebookEdit' for e in entries) else 1)
"

# shellcheck disable=SC2317,SC2329
nojq_remove_repo_d() (
  cd "$REPO_D" || exit 1
  PATH="$NOJQ_PATH_DIR" "$BINDLE_BIN" remove >/dev/null 2>&1
)
check "bindle remove succeeds against Repo D with no jq on PATH" nojq_remove_repo_d
check "Repo D: local core.hooksPath is gone after remove (no jq)" bash -c \
  "! git -C '$REPO_D' config --local --get core.hooksPath >/dev/null 2>&1"

LEGACY_TEMPLATE_2="$TMP/legacy-template-2"
git init -q "$LEGACY_TEMPLATE_2"
git -C "$LEGACY_TEMPLATE_2" commit -q --allow-empty -m init
# shellcheck disable=SC2317,SC2329
init_legacy_template_2() (
  cd "$LEGACY_TEMPLATE_2" || exit 1
  "$BINDLE_BIN" init >/dev/null 2>&1
)
check "bindle init succeeds against the no-jq legacy-template repo" init_legacy_template_2

LEGACY_GLOBAL_GIT_DIR_2="$TMP/legacy-global-git-hooks-2"
mv "$(git -C "$LEGACY_TEMPLATE_2" config --local --get core.hooksPath)" "$LEGACY_GLOBAL_GIT_DIR_2"
git -C "$LEGACY_TEMPLATE_2" config --local --unset core.hooksPath
git config --global core.hooksPath "$LEGACY_GLOBAL_GIT_DIR_2"

REPO_E="$TMP/repo-e"
git init -q "$REPO_E"
git -C "$REPO_E" commit -q --allow-empty -m init
# shellcheck disable=SC2317,SC2329
nojq_init_repo_e_blocked_by_legacy() (
  cd "$REPO_E" || exit 1
  ! PATH="$NOJQ_PATH_DIR" "$BINDLE_BIN" init >/dev/null 2>&1
)
check "bindle init against Repo E is blocked by recognized legacy global state (no jq)" \
  nojq_init_repo_e_blocked_by_legacy

# shellcheck disable=SC2317,SC2329
nojq_migrate_legacy_global() (
  PATH="$NOJQ_PATH_DIR" "$BINDLE_BIN" migrate-legacy-global >/dev/null 2>&1
)
check "bindle migrate-legacy-global succeeds with no jq on PATH" nojq_migrate_legacy_global
check "the recognized legacy global core.hooksPath is gone after migration (no jq)" bash -c \
  '! git config --global --get core.hooksPath >/dev/null 2>&1'

# shellcheck disable=SC2317,SC2329
nojq_init_repo_e_now_succeeds() (
  cd "$REPO_E" || exit 1
  PATH="$NOJQ_PATH_DIR" "$BINDLE_BIN" init >/dev/null 2>&1
)
check "bindle init against Repo E now succeeds once legacy state is migrated away (no jq)" \
  nojq_init_repo_e_now_succeeds

# ===========================================================================
printf '\n  packaged-install: %d/%d checks passed\n' "$pass" "$((pass + fail))"
exit "$fail"
