#!/usr/bin/env bash
#
# test-guardrail-status.sh — regression suite for install-guardrails.sh's
# `--status` mode (the read-only inspection seam `bindle status` drives via
# detect_git_guardrails/detect_claude_guardrails, src/bindle/guardrails.py).
#
# Proves the five-state contract — installed / not-installed / partial /
# conflict / invalid — against REAL repository/configuration state, using
# the exact fixtures a developer's repo could actually be in, rather than
# mocking the filesystem away. Complements bin/test-guardrail-ownership.sh
# (the opt-in/opt-out end-to-end contract) and bin/test-install-guardrails.sh
# (Claude-layer settings mechanics): this file is specifically about
# read-only detection never drifting from what --apply/--uninstall already
# enforce, and never mutating anything itself. Fully isolated (its own
# HOME) — never touches the real ~/.claude or ~/.local/share/bindle.
#
# Usage: bin/test-guardrail-status.sh
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

# shellcheck disable=SC2317,SC2329
git_status_for() { # git_status_for REPO
  "$INSTALLER" --status --git-only --repo "$1" 2>/dev/null | sed -n 's/^GIT_STATUS=//p'
}

# shellcheck disable=SC2317,SC2329
claude_status_for() { # claude_status_for REPO
  "$INSTALLER" --status --claude-only --repo "$1" 2>/dev/null | sed -n 's/^CLAUDE_STATUS=//p'
}

# shellcheck disable=SC2317,SC2329
assert_git_status() { # assert_git_status REPO EXPECTED
  [ "$(git_status_for "$1")" = "$2" ]
}
# shellcheck disable=SC2317,SC2329
assert_claude_status() { # assert_claude_status REPO EXPECTED
  [ "$(claude_status_for "$1")" = "$2" ]
}

hooks_dir_for() { # hooks_dir_for REPO
  printf '%s/bindle-hooks' "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir)"
}

claude_dir_for() { # claude_dir_for REPO
  printf '%s/bindle-claude' "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir)"
}

claude_settings_for() { # claude_settings_for REPO
  local repo="$1" common root
  common="$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)"
  if [ "$(basename "$common")" = ".git" ]; then root="$(dirname "$common")"; else root="$common"; fi
  printf '%s' "$root/.claude/settings.local.json"
}

owned_deny_file_for() { # owned_deny_file_for REPO
  printf '%s/bindle-claude-deny-owned.json' "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir)"
}

exclude_owned_file_for() { # exclude_owned_file_for REPO
  printf '%s/bindle-claude-exclude-owned' "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir)"
}

exclude_file_for() { # exclude_file_for REPO
  printf '%s/info/exclude' "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir)"
}

# repo_local_config_snapshot REPO — a deterministic snapshot of every piece
# of state --status is allowed to READ but never WRITE: local git config,
# the guardrail-owned files/directories under .git, and
# .claude/settings.local.json. Used to prove repeated --status calls (and
# `bindle status` itself) are genuinely no-ops.
# shellcheck disable=SC2317,SC2329
repo_local_config_snapshot() { # repo_local_config_snapshot REPO
  local repo="$1"
  git -C "$repo" config --local --list
  find "$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)" \
    -maxdepth 1 -name 'bindle-*' -exec ls -la {} \; 2>/dev/null
  local settings
  settings="$(claude_settings_for "$repo")"
  [ -f "$settings" ] && cat "$settings"
  return 0
}

# shellcheck disable=SC2317,SC2329
assert_no_mutation_from_repeated_status() { # assert_no_mutation_from_repeated_status REPO
  local repo="$1" before after
  before="$(repo_local_config_snapshot "$repo")"
  "$INSTALLER" --status --repo "$repo" >/dev/null 2>&1
  "$INSTALLER" --status --repo "$repo" >/dev/null 2>&1
  after="$(repo_local_config_snapshot "$repo")"
  [ "$before" = "$after" ]
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export BINDLE_GUARD_HOME="$TMP/legacy-guard-home"
export BINDLE_CLAUDE_HOME="$TMP/legacy-claude-home"
export HOME="$TMP/fake-home"
mkdir -p "$HOME"
git config --global user.email test@example.com
git config --global user.name Test

# ===========================================================================
echo "not-installed: a never-initialized repository reports not-installed for both layers:"

UNINIT="$TMP/uninit-repo"
new_fixture "$UNINIT"
check "Git: not-installed" assert_git_status "$UNINIT" not-installed
check "Claude: not-installed" assert_claude_status "$UNINIT" not-installed

# ===========================================================================
echo "installed: a clean 'bindle init' reports installed for both layers:"

INSTALLED="$TMP/installed-repo"
new_fixture "$INSTALLED"
"$INSTALLER" --apply --repo "$INSTALLED" >/dev/null
check "Git: installed" assert_git_status "$INSTALLED" installed
check "Claude: installed" assert_claude_status "$INSTALLED" installed

# ===========================================================================
echo "partial: recognizable Bindle ownership, incomplete installation (Git):"

GIT_PARTIAL_UNWIRED="$TMP/git-partial-unwired"
new_fixture "$GIT_PARTIAL_UNWIRED"
"$INSTALLER" --apply --repo "$GIT_PARTIAL_UNWIRED" >/dev/null
git -C "$GIT_PARTIAL_UNWIRED" config --local --unset core.hooksPath
check "Git: partial when the intact hook dir exists but core.hooksPath isn't wired to it" \
  assert_git_status "$GIT_PARTIAL_UNWIRED" partial

GIT_PARTIAL_BROKEN="$TMP/git-partial-broken"
new_fixture "$GIT_PARTIAL_BROKEN"
"$INSTALLER" --apply --repo "$GIT_PARTIAL_BROKEN" >/dev/null
rm -f "$(hooks_dir_for "$GIT_PARTIAL_BROKEN")/pre-commit"
check "Git: partial when core.hooksPath is wired but a hook symlink is missing" \
  assert_git_status "$GIT_PARTIAL_BROKEN" partial

echo "partial: recognizable Bindle ownership, incomplete installation (Claude):"

CLAUDE_PARTIAL="$TMP/claude-partial"
new_fixture "$CLAUDE_PARTIAL"
"$INSTALLER" --apply --repo "$CLAUDE_PARTIAL" >/dev/null
rm -f "$(claude_dir_for "$CLAUDE_PARTIAL")/claude-protected-main-guard"
check "Claude: partial when the PreToolUse entry is registered but the guard script is gone" \
  assert_claude_status "$CLAUDE_PARTIAL" partial

CLAUDE_PARTIAL_DENY="$TMP/claude-partial-deny"
new_fixture "$CLAUDE_PARTIAL_DENY"
"$INSTALLER" --apply --repo "$CLAUDE_PARTIAL_DENY" >/dev/null
python3 - "$(claude_settings_for "$CLAUDE_PARTIAL_DENY")" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    doc = json.load(f)
doc["permissions"]["deny"] = [x for x in doc["permissions"]["deny"] if x != "Read(.env)"]
with open(path, "w") as f:
    json.dump(doc, f)
PY
check "Claude: partial when an owned deny entry is missing from permissions.deny" \
  assert_claude_status "$CLAUDE_PARTIAL_DENY" partial

echo "partial: the two ownership-record artifacts (OWNED_DENY_FILE, CLAUDE_EXCLUDE_OWNED_FILE) are themselves required for 'installed':"

CLAUDE_PARTIAL_NO_DENY_RECORD="$TMP/claude-partial-no-deny-record"
new_fixture "$CLAUDE_PARTIAL_NO_DENY_RECORD"
"$INSTALLER" --apply --repo "$CLAUDE_PARTIAL_NO_DENY_RECORD" >/dev/null
rm -f "$(owned_deny_file_for "$CLAUDE_PARTIAL_NO_DENY_RECORD")"
check "Claude: partial (not installed) when the deny ownership record is deleted after a clean init — reversal information is gone" \
  assert_claude_status "$CLAUDE_PARTIAL_NO_DENY_RECORD" partial

CLAUDE_PARTIAL_EXCLUDE_LINE_GONE="$TMP/claude-partial-exclude-line-gone"
new_fixture "$CLAUDE_PARTIAL_EXCLUDE_LINE_GONE"
"$INSTALLER" --apply --repo "$CLAUDE_PARTIAL_EXCLUDE_LINE_GONE" >/dev/null
check "(precondition) the exclude-ownership marker was actually created by this init" \
  bash -c "[ -f '$(exclude_owned_file_for "$CLAUDE_PARTIAL_EXCLUDE_LINE_GONE")' ]"
grep -vxF ".claude/settings.local.json" "$(exclude_file_for "$CLAUDE_PARTIAL_EXCLUDE_LINE_GONE")" \
  >"$(exclude_file_for "$CLAUDE_PARTIAL_EXCLUDE_LINE_GONE").tmp" || true
mv "$(exclude_file_for "$CLAUDE_PARTIAL_EXCLUDE_LINE_GONE").tmp" "$(exclude_file_for "$CLAUDE_PARTIAL_EXCLUDE_LINE_GONE")"
check "Claude: partial when the exclude-ownership marker claims a line that's no longer in info/exclude" \
  assert_claude_status "$CLAUDE_PARTIAL_EXCLUDE_LINE_GONE" partial

CLAUDE_RESIDUAL_EXCLUDE_MARKER="$TMP/claude-residual-exclude-marker"
new_fixture "$CLAUDE_RESIDUAL_EXCLUDE_MARKER"
"$INSTALLER" --apply --repo "$CLAUDE_RESIDUAL_EXCLUDE_MARKER" >/dev/null
"$INSTALLER" --uninstall --repo "$CLAUDE_RESIDUAL_EXCLUDE_MARKER" >/dev/null
: >"$(exclude_owned_file_for "$CLAUDE_RESIDUAL_EXCLUDE_MARKER")"
check "Claude: partial (not not-installed) when the exclude-ownership marker is the ONLY remaining Bindle artifact" \
  assert_claude_status "$CLAUDE_RESIDUAL_EXCLUDE_MARKER" partial

echo "installed: a repository that already ignored settings.local.json before init stays installed with no exclude marker:"

CLAUDE_PREEXISTING_IGNORE="$TMP/claude-preexisting-ignore"
new_fixture "$CLAUDE_PREEXISTING_IGNORE"
mkdir -p "$(dirname "$(exclude_file_for "$CLAUDE_PREEXISTING_IGNORE")")"
printf '.claude/settings.local.json\n' >>"$(exclude_file_for "$CLAUDE_PREEXISTING_IGNORE")"
"$INSTALLER" --apply --repo "$CLAUDE_PREEXISTING_IGNORE" >/dev/null
check "(precondition) Bindle did NOT create its own exclude-ownership marker (the repo already owned the ignore rule)" \
  bash -c "[ ! -f '$(exclude_owned_file_for "$CLAUDE_PREEXISTING_IGNORE")' ]"
check "Claude: installed even though no exclude-ownership marker exists, because Bindle never needed to claim one" \
  assert_claude_status "$CLAUDE_PREEXISTING_IGNORE" installed

# ===========================================================================
echo "conflict: the integration point is occupied by something that isn't Bindle's own:"

GIT_CONFLICT="$TMP/git-conflict"
new_fixture "$GIT_CONFLICT"
mkdir -p "$TMP/foreign-hooks"
git -C "$GIT_CONFLICT" config --local core.hooksPath "$TMP/foreign-hooks"
check "Git: conflict when a foreign core.hooksPath is already set" \
  assert_git_status "$GIT_CONFLICT" conflict

CLAUDE_CONFLICT="$TMP/claude-conflict"
new_fixture "$CLAUDE_CONFLICT"
mkdir -p "$CLAUDE_CONFLICT/.claude"
echo '{}' >"$CLAUDE_CONFLICT/.claude/settings.local.json"
git -C "$CLAUDE_CONFLICT" add .claude/settings.local.json
git -C "$CLAUDE_CONFLICT" commit -q -m "chore: track settings"
check "Claude: conflict when settings.local.json is tracked (team-owned) in Git" \
  assert_claude_status "$CLAUDE_CONFLICT" conflict

# ===========================================================================
echo "invalid: Bindle-owned-looking state that is malformed enough that ownership can't safely be established:"

CLAUDE_INVALID="$TMP/claude-invalid"
new_fixture "$CLAUDE_INVALID"
"$INSTALLER" --apply --repo "$CLAUDE_INVALID" >/dev/null
printf 'not valid json {{{' >"$(claude_settings_for "$CLAUDE_INVALID")"
check "Claude: invalid when settings.local.json is corrupted after a real install" \
  assert_claude_status "$CLAUDE_INVALID" invalid

CLAUDE_INVALID_DENY="$TMP/claude-invalid-deny"
new_fixture "$CLAUDE_INVALID_DENY"
"$INSTALLER" --apply --repo "$CLAUDE_INVALID_DENY" >/dev/null
printf 'not an array' >"$(owned_deny_file_for "$CLAUDE_INVALID_DENY")"
check "Claude: invalid when the owned-deny bookkeeping file is unreadable as a JSON array" \
  assert_claude_status "$CLAUDE_INVALID_DENY" invalid

CLAUDE_UNRELATED_BROKEN="$TMP/claude-unrelated-broken"
new_fixture "$CLAUDE_UNRELATED_BROKEN"
mkdir -p "$CLAUDE_UNRELATED_BROKEN/.claude"
printf 'not valid json' >"$CLAUDE_UNRELATED_BROKEN/.claude/settings.local.json"
check "Claude: a broken settings.local.json with NO Bindle artifacts alongside it reports not-installed, not invalid (it isn't Bindle's to diagnose)" \
  assert_claude_status "$CLAUDE_UNRELATED_BROKEN" not-installed

# ===========================================================================
echo "mixed Git/Claude states in one repository are detected independently:"

MIXED="$TMP/mixed-repo"
new_fixture "$MIXED"
"$INSTALLER" --apply --repo "$MIXED" >/dev/null
mkdir -p "$TMP/mixed-foreign-hooks"
git -C "$MIXED" config --local --unset core.hooksPath
git -C "$MIXED" config --local core.hooksPath "$TMP/mixed-foreign-hooks"
rm -f "$(claude_dir_for "$MIXED")/allow-main-write.sh"
check "mixed repo: Git reports conflict" assert_git_status "$MIXED" conflict
check "mixed repo: Claude independently reports partial" assert_claude_status "$MIXED" partial

# ===========================================================================
echo "repeated --status calls cause no mutation, for every state above:"

for repo in "$UNINIT" "$INSTALLED" "$GIT_PARTIAL_UNWIRED" "$CLAUDE_PARTIAL" \
  "$CLAUDE_PARTIAL_NO_DENY_RECORD" "$CLAUDE_PARTIAL_EXCLUDE_LINE_GONE" "$CLAUDE_RESIDUAL_EXCLUDE_MARKER" \
  "$CLAUDE_PREEXISTING_IGNORE" "$GIT_CONFLICT" "$CLAUDE_CONFLICT" "$CLAUDE_INVALID" "$MIXED"; do
  check "no mutation from repeated --status: $(basename "$repo")" \
    assert_no_mutation_from_repeated_status "$repo"
done

# ===========================================================================
echo "--status never gates on or migrates recognized legacy global state:"

LEGACY_TEMPLATE="$TMP/legacy-template"
new_fixture "$LEGACY_TEMPLATE"
"$INSTALLER" --apply --repo "$LEGACY_TEMPLATE" >/dev/null
LEGACY_GIT_DIR="$TMP/legacy-global-git-hooks"
mv "$(git -C "$LEGACY_TEMPLATE" config --local --get core.hooksPath)" "$LEGACY_GIT_DIR"
git -C "$LEGACY_TEMPLATE" config --local --unset core.hooksPath
git config --global core.hooksPath "$LEGACY_GIT_DIR"

STATUS_UNDER_LEGACY="$TMP/status-under-legacy"
new_fixture "$STATUS_UNDER_LEGACY"
check "status succeeds even while a recognized legacy global install exists (apply would refuse)" \
  bash -c "'$INSTALLER' --status --repo '$STATUS_UNDER_LEGACY' >/dev/null 2>&1"
check "status reports not-installed for this repo regardless of the legacy global state" \
  assert_git_status "$STATUS_UNDER_LEGACY" not-installed
check "the legacy global core.hooksPath was NOT migrated away by a status call" \
  bash -c "[ \"\$(git config --global --get core.hooksPath)\" = '$LEGACY_GIT_DIR' ]"

git config --global --unset core.hooksPath
rm -rf "$LEGACY_GIT_DIR"

# ===========================================================================
printf '\n  guardrail-status: %d/%d checks passed\n' "$pass" "$((pass + fail))"
exit "$fail"
