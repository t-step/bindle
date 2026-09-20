#!/usr/bin/env bash
#
# git-hook-dispatch.sh — Bindle's single Git hook implementation. Installed once
# by bin/install-guardrails.sh and symlinked under every standard client-side
# hook name in a global core.hooksPath directory; $0's basename says which hook
# Git invoked.
#
# A global core.hooksPath redirects lookup for EVERY hook name, so the full
# standard name surface is symlinked: Bindle policy runs first for
# policy-bearing names, then the repository's own same-named hook is delegated
# to, so commit-msg (Cocogitto), post-commit/post-merge (projectmem), pre-push
# and repo-owned hooks are not silently dropped
# (plans/archive/2026-08-23-local-guardrail-layer.md, Decisions #1).
#
# Policy-bearing names were chosen empirically (the plan's evidence table):
# pre-commit alone misses rebase-replay, cherry-pick and --no-verify.
# prepare-commit-msg is the broadest point (commit, merge, rebase-replay,
# cherry-pick; survives --no-verify) but not `git am`, which has its own hook
# family, hence pre-applypatch. pre-commit and pre-merge-commit stay for faster
# rejection in the non-bypass case; the decision lives in one function.
#
# History guardrails (D048) live here too: a commit-msg Conventional Commit
# check (also accepts fixup!/squash!/amend!) and a pre-push history-hygiene
# report that BLOCKs pending autosquash commits and non-conforming subjects and
# only WARNs on observable churn. `--history` (also `bindle history`) prints it
# on demand. Regex, counts and Git plumbing only; never rewrites history or the
# working tree.
#
set -euo pipefail

PROTECTED_BRANCH="main"

hook_name="$(basename "$0")"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [ "${1:-}" = "--history" ]; then
    echo "bindle history: not inside a Git working tree" >&2
    exit 2
  fi
  exit 0
fi

# Empty when detached; a detached HEAD is never treated as PROTECTED_BRANCH.
current_branch() {
  git symbolic-ref --quiet --short HEAD 2>/dev/null || true
}

# pre-rebase gets the branch being rebased as $2, only if not the current one.
branch_under_mutation() {
  if [ "$hook_name" = "pre-rebase" ] && [ -n "${2:-}" ]; then
    printf '%s\n' "$2"
  else
    current_branch
  fi
}

# The ONE place the branch/override decision is made; every hook calls it.
check_protected_branch() {
  local target
  target="$(branch_under_mutation "$@")"
  [ "$target" = "$PROTECTED_BRANCH" ] || return 0
  [ -z "${ALLOW_MAIN_WRITE:-}" ] || return 0

  # Unborn branch has no history to protect; blocking it blocks repo bootstrap.
  git rev-parse --verify --quiet HEAD >/dev/null 2>&1 || return 0

  local dirty_note=""
  if [ -n "$(git status --porcelain 2>/dev/null || true)" ]; then
    dirty_note=" '$PROTECTED_BRANCH' also has uncommitted changes — consider a branch so that work isn't lost."
  fi

  cat >&2 <<MSG
bindle guardrail: '$PROTECTED_BRANCH' is protected — blocked '$hook_name'.
$dirty_note
Create a branch from '$PROTECTED_BRANCH' first:
  bindle branch <branch-name>

If this write to '$PROTECTED_BRANCH' is genuinely intentional, scope the
override to this one command (it does not persist to the next command):
  ALLOW_MAIN_WRITE=1 <your original command>
MSG
  exit 1
}

# History guardrails (D048). Bash 3.2-safe: no associative arrays, mapfile,
# or ${var,,} (macOS's system bash is 3.2).
#
# Optional configuration is plain `git config`; local config lives in the
# common git dir, so every linked worktree sees the same values (D018):
#   bindle.conventionalCommits      true|false — override the default, which
#                                   is "on iff cog.toml exists at the
#                                   worktree root"
#   bindle.historyBase              ref a branch is measured against
#                                   (default: origin/main, else main)
#   bindle.hygiene.tinyLines        "tiny commit" line threshold (default 10)
#   bindle.hygiene.repeatCommits    "repeatedly touched file" commit
#                                   threshold (default 5, minimum 2)
#   bindle.hygiene.testPattern      ERE matching test paths
#   bindle.hygiene.generatedPattern ERE matching generated/lockfile paths

# Conventional Commits/Cocogitto types, unioned with cog.toml [commit_types].
DEFAULT_COMMIT_TYPES="feat fix docs style refactor perf test build ci chore revert"
# From this repo's own layout (tests/, test_*.py, test-*.sh, uv.lock).
DEFAULT_TEST_PATTERN='(^|/)tests?/|(^|/)test_[^/]*\.py$|(^|/)test-[^/]*\.sh$'
DEFAULT_GENERATED_PATTERN='(^|/)uv\.lock$'
# "Rework-shaped": the FIRST WORD of a conventional subject's description.
REWORK_WORDS=" fix cleanup lint format formatting typo tests test "

TAB="$(printf '\t')"
COMMIT_TYPES=""
SUBJ_KIND=""
SUBJ_DESC=""
PUSH_INPUT_FILE=""

cfg() { git config --get "$1" 2>/dev/null || true; }

cfg_int() {
  local v
  v="$(cfg "$1")"
  case "$v" in
  '' | *[!0-9]*) printf '%s\n' "$2" ;;
  *) printf '%s\n' "$v" ;;
  esac
}

cfg_str() {
  local v
  v="$(cfg "$1")"
  printf '%s\n' "${v:-$2}"
}

worktree_top() {
  git rev-parse --show-toplevel 2>/dev/null || true
}

# Tracked only: an untracked or ignored cog.toml must not change enforcement.
cog_toml_tracked() {
  local top
  top="$(worktree_top)"
  [ -n "$top" ] && git -C "$top" ls-files --error-unmatch -- cog.toml >/dev/null 2>&1
}

# Explicit bindle.conventionalCommits wins, else a tracked cog.toml opts in;
# repos that declare nothing are never held to the convention.
conventional_commits_enabled() {
  case "$(git config --type=bool --get bindle.conventionalCommits 2>/dev/null || true)" in
  true) return 0 ;;
  false) return 1 ;;
  esac
  cog_toml_tracked
}

# Defaults plus cog.toml [commit_types] keys: cog.toml is the extension point.
commit_types() {
  local toml
  toml="$(worktree_top)/cog.toml"
  {
    printf '%s\n' "$DEFAULT_COMMIT_TYPES" | tr ' ' '\n'
    if cog_toml_tracked && [ -f "$toml" ]; then
      awk '/^\[commit_types\]/ { s = 1; next } /^\[/ { s = 0 } s && /^[A-Za-z][A-Za-z0-9_-]*[ \t]*=/ { sub(/[ \t]*=.*/, ""); print }' "$toml"
    fi
  } | awk '!seen[$0]++'
}

load_commit_types() {
  COMMIT_TYPES=" $(commit_types | tr '\n' ' ')"
}

# Sets SUBJ_KIND (autosquash|merge|revert|conventional|invalid) and SUBJ_DESC by
# pattern match; needs load_commit_types.
# "merge" is a prefix match only: callers decide if a real merge is in progress
# (commit-msg: MERGE_HEAD; pre-push: --no-merges already excluded them).
parse_subject() {
  local s="$1" re='^((fixup|squash|amend)! )+[^[:space:]]'
  SUBJ_KIND=invalid
  SUBJ_DESC=""
  if [[ $s =~ $re ]]; then
    SUBJ_KIND=autosquash
  elif [[ $s == "Merge "* ]]; then
    SUBJ_KIND=merge
  elif re='^(Revert|Reapply) ".+"$' && [[ $s =~ $re ]]; then
    # Exactly what `git revert` generates (Reapply = reverting a revert).
    SUBJ_KIND=revert
  else
    re='^([A-Za-z][A-Za-z0-9_-]*)(\([^()[:space:]]+\))?!?: ([^[:space:]].*)$'
    if [[ $s =~ $re ]] && [[ "$COMMIT_TYPES" == *" ${BASH_REMATCH[1]} "* ]]; then
      SUBJ_KIND=conventional
      SUBJ_DESC="${BASH_REMATCH[3]}"
    fi
  fi
}

# A "Merge …" subject is trusted only when Git really is creating/keeping a
# merge: MERGE_HEAD exists (clean or conflict-resolved), or an amend leaves an
# existing merge commit's subject unchanged (HEAD has two parents).
merge_subject_is_git_generated() {
  git rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1 && return 0
  git rev-parse -q --verify 'HEAD^2' >/dev/null 2>&1 && [ "$(git log -1 --format=%s HEAD 2>/dev/null)" = "$1" ]
}

# No-op unless the repo declared Conventional Commits. Git-generated
# fixup!/squash!/amend! and Revert "…" subjects are valid by construction and
# skip the repo's own commit-msg hook (`cog verify` cannot parse them); merge
# and conventional subjects fall through to it.
check_commit_message() {
  local file="${1:-}" subject
  conventional_commits_enabled || return 0
  load_commit_types
  # First non-blank, non-`#` line (git strips comments after this hook runs).
  subject="$(grep -v -m1 -E '^[[:space:]]*(#.*)?$' "$file" 2>/dev/null || true)"
  parse_subject "$subject"
  if [ "$SUBJ_KIND" = merge ] && ! merge_subject_is_git_generated "$subject"; then
    SUBJ_KIND=invalid
  fi
  case "$SUBJ_KIND" in
  autosquash | revert)
    exit 0
    ;;
  invalid)
    cat >&2 <<MSG
bindle guardrail: commit message rejected — not a Conventional Commit.
  subject:  $subject
  expected: type(optional-scope): description
  types:    $(printf '%s\n' "$COMMIT_TYPES" | xargs)
Revising an existing commit? Say so explicitly instead:
  git commit --fixup=<target>   (subject becomes 'fixup! …'; also squash!/amend!)
and fold it before pushing: git rebase -i --autosquash <base>
MSG
    exit 1
    ;;
  esac
}

resolve_history_base() {
  local candidate
  for candidate in "${1:-}" "$(cfg bindle.historyBase)" "origin/$PROTECTED_BRANCH" "$PROTECTED_BRANCH"; do
    [ -n "$candidate" ] || continue
    if git rev-parse --verify --quiet "$candidate^{commit}" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
}

report_line() { printf '%-5s  %s\n' "$1" "$2"; }

commits_word() {
  if [ "$1" -eq 1 ]; then printf 'commit'; else printf 'commits'; fi
}

# Prints the hygiene report for commits reachable from TIP but not BASE; returns
# 1 iff it printed a BLOCK line. Read-only.
# REBASE_BRANCH is the local branch appended to the fold hint (empty for HEAD or
# a raw sha, where the checked-out branch is right).
history_report() {
  local tip="$1" label="$2" base range mb mb_short
  local total merges nonmerge tiny repeat testre genre cc_on=0 blocked=0
  local subjects sha subj n_auto=0 n_bad=0 auto_list="" bad_list="" descs=""
  local stats kind cnt path n_tiny=0 n_test=0 files_out="" gen_out=""
  local n_rework n_revert pids dups rebase_target fold_flags shown

  base="$(resolve_history_base "${3:-}")"
  if [ -z "$base" ]; then
    printf 'History hygiene: %s\n' "$label"
    report_line INFO "skipped: no base ref found (git config bindle.historyBase <ref>)"
    return 0
  fi
  range="$base..$tip"

  # `set -e` is off here (called in an ||/if context): fail CLOSED, never PASS.
  if ! total="$(git rev-list --count "$range" 2>/dev/null)" ||
    ! merges="$(git rev-list --merges --count "$range" 2>/dev/null)" ||
    ! subjects="$(git log --no-merges --format='%H%x09%s' "$range" 2>/dev/null)"; then
    printf 'History hygiene: %s vs %s\n' "$label" "$base"
    report_line BLOCK "cannot read the history of $range (git failed); refusing to report PASS"
    return 1
  fi
  nonmerge=$((total - merges))
  printf 'History hygiene: %s vs %s (%d %s, %d merge)\n' "$label" "$base" "$total" "$(commits_word "$total")" "$merges"
  if [ "$total" -eq 0 ]; then
    report_line PASS "no commits ahead of $base"
    return 0
  fi

  tiny="$(cfg_int bindle.hygiene.tinyLines 10)"
  repeat="$(cfg_int bindle.hygiene.repeatCommits 5)"
  [ "$repeat" -ge 2 ] || repeat=2
  testre="$(cfg_str bindle.hygiene.testPattern "$DEFAULT_TEST_PATTERN")"
  genre="$(cfg_str bindle.hygiene.generatedPattern "$DEFAULT_GENERATED_PATTERN")"
  if conventional_commits_enabled; then cc_on=1; fi
  load_commit_types

  while IFS=$'\t' read -r sha subj; do
    [ -n "$sha" ] || continue
    parse_subject "$subj"
    case "$SUBJ_KIND" in
    autosquash)
      n_auto=$((n_auto + 1))
      [ "$n_auto" -gt 5 ] || auto_list="$auto_list$(printf '       %.7s %s' "$sha" "$subj")"$'\n'
      ;;
    invalid | merge) # a NON-merge commit that merely says "Merge …" is not Git-generated
      n_bad=$((n_bad + 1))
      [ "$n_bad" -gt 5 ] || bad_list="$bad_list$(printf '       %.7s %s' "$sha" "$subj")"$'\n'
      ;;
    conventional)
      descs="$descs$SUBJ_DESC"$'\n'
      ;;
    esac
  done <<<"$subjects"

  mb="$(git merge-base "$base" "$tip" 2>/dev/null || true)"
  mb_short="$base"
  [ -z "$mb" ] || mb_short="$(git rev-parse --short "$mb")"

  if [ "$n_auto" -gt 0 ]; then
    blocked=1
    report_line BLOCK "$n_auto pending fixup!/squash!/amend! $(commits_word "$n_auto")"
    printf '%s' "$auto_list"
    # Name a branch only if the pushed ref is a local branch other than HEAD's.
    rebase_target=""
    if [ -n "${4:-}" ] && [ "$4" != "$(current_branch)" ] && git show-ref --verify --quiet "refs/heads/$4"; then
      rebase_target=" $4"
    fi
    # Without --rebase-merges, rebase flattens and replays upstream merges.
    fold_flags="--autosquash"
    if [ "$merges" -gt 0 ]; then fold_flags="--autosquash --rebase-merges"; fi
    printf '       fold them: GIT_SEQUENCE_EDITOR=true git rebase -i %s %s%s\n' "$fold_flags" "$mb_short" "$rebase_target"
  else
    report_line PASS "no pending fixup!/squash!/amend! commits"
  fi

  if [ "$cc_on" -eq 1 ]; then
    if [ "$n_bad" -gt 0 ]; then
      blocked=1
      report_line BLOCK "$n_bad $(commits_word "$n_bad") without a Conventional Commit subject"
      printf '%s' "$bad_list"
      printf '       reword them: git rebase -i %s (mark them "reword")\n' "$mb_short"
    else
      report_line PASS "Conventional Commit syntax"
    fi
  fi

  stats="$(git log --no-merges --no-renames --numstat --format='@%H' "$range" |
    H_TINY="$tiny" H_REPEAT="$repeat" H_TESTRE="$testre" H_GENRE="$genre" awk '
      BEGIN {
        FS = "\t"
        tiny = ENVIRON["H_TINY"] + 0; repeat = ENVIRON["H_REPEAT"] + 0
        testre = ENVIRON["H_TESTRE"]; genre = ENVIRON["H_GENRE"]
      }
      function finish() {
        if (!open) return
        if (!bin && lines < tiny) tinyn++
        if (nfiles > 0 && !nontest) testonly++
        open = 0
      }
      /^@/ { finish(); open = 1; lines = 0; bin = 0; nfiles = 0; nontest = 0; next }
      NF >= 3 && open {
        if ($1 == "-") bin = 1; else lines += $1 + $2
        nfiles++
        if ($3 !~ testre) nontest = 1
        touched[$3]++
      }
      END {
        finish()
        printf "TINY\t%d\nTESTONLY\t%d\n", tinyn, testonly
        for (p in touched) {
          if (p ~ genre) { if (touched[p] >= 2) printf "GEN\t%d\t%s\n", touched[p], p }
          else if (touched[p] >= repeat) printf "FILE\t%d\t%s\n", touched[p], p
        }
      }')" || stats=""
  while IFS=$'\t' read -r kind cnt path; do
    case "$kind" in
    TINY) n_tiny="$cnt" ;;
    TESTONLY) n_test="$cnt" ;;
    GEN) gen_out="$gen_out$cnt$TAB$path"$'\n' ;;
    FILE) files_out="$files_out$cnt$TAB$path"$'\n' ;;
    esac
  done <<<"$stats"

  n_rework="$(printf '%s' "$descs" | awk -v words="$REWORK_WORDS" '
    { w = tolower($1); gsub(/[^a-z]/, "", w); if (w != "" && index(words, " " w " ")) n++ }
    END { print n + 0 }')"
  n_revert="$(git log --no-merges -E --format=%H --grep='^This reverts commit [0-9a-f]{7,}' --grep='^Revert "' "$range" | wc -l | tr -d ' ')"
  # Same `git patch-id --stable` = identical patch (revert-redo, dup. pick).
  pids="$(git log --no-merges -p --format='commit %H' "$range" | git patch-id --stable | awk '{ print $1 }')" || pids=""
  dups="$(printf '%s\n' "$pids" | awk 'NF { n++; if (!seen[$1]++) u++ } END { print n - u + 0 }')"

  if [ "$n_tiny" -gt 0 ]; then
    report_line WARN "$n_tiny/$nonmerge commits change fewer than $tiny lines"
  fi
  if [ "$n_rework" -gt 0 ]; then
    report_line WARN "$n_rework $(commits_word "$n_rework") with corrective/rework-shaped subjects (description starts with $(printf '%s\n' "$REWORK_WORDS" | xargs | tr ' ' '/'))"
  fi
  if [ "$n_test" -gt 0 ]; then
    report_line WARN "$n_test/$nonmerge test-only commits"
  fi
  if [ "$merges" -gt 0 ]; then
    report_line WARN "$merges merge $(commits_word "$merges") present on feature branch"
  fi
  if [ "$n_revert" -gt 0 ]; then
    report_line WARN "$n_revert explicit revert $(commits_word "$n_revert")"
  fi
  if [ "$dups" -gt 0 ]; then
    report_line WARN "exact patch repeats (same git patch-id as an earlier commit): $dups"
  fi
  # No `head`: SIGPIPE on `sort` would abort the hook under pipefail+errexit.
  printf '%s' "$gen_out" | sort -t "$TAB" -k1,1nr -k2 | while IFS=$'\t' read -r cnt path; do
    if [ -n "$path" ]; then report_line WARN "generated/lockfile $path changed in $cnt commits"; fi
  done
  printf '%s' "$files_out" | sort -t "$TAB" -k1,1nr -k2 | {
    shown=0
    while IFS=$'\t' read -r cnt path; do
      shown=$((shown + 1))
      if [ -n "$path" ] && [ "$shown" -le 3 ]; then report_line INFO "$path changed in $cnt commits"; fi
    done
  }

  [ "$blocked" -eq 0 ]
}

# Pre-push policy: report every branch update from the ref list git feeds on
# stdin (never the checked-out HEAD) and refuse the push on any BLOCK. Never
# rewrites anything.
#
# Counted: updates whose LOCAL or REMOTE ref is a branch. `git push origin
# HEAD`, `HEAD:refs/heads/x` and `<sha>:refs/heads/x` arrive with a
# non-refs/heads local ref, so the remote ref names the branch. Deletions and
# tag/notes/other-ref updates are skipped.
check_push_history() {
  local local_ref local_sha remote_ref label rebase_branch rc=0
  # stdin is consumed here; keep exact bytes for a repo-native pre-push hook.
  PUSH_INPUT_FILE="$(mktemp)"
  trap 'rm -f "$PUSH_INPUT_FILE"' EXIT
  cat >"$PUSH_INPUT_FILE"
  while read -r local_ref local_sha remote_ref _; do
    label="" rebase_branch=""
    case "$local_ref" in
    refs/heads/*)
      label="${local_ref#refs/heads/}"
      rebase_branch="$label"
      ;;
    esac
    if [ -z "$label" ]; then
      case "$remote_ref" in
      refs/heads/*) label="${remote_ref#refs/heads/}" ;;
      *) continue ;;
      esac
    fi
    case "$local_sha" in
    *[!0]*) ;;
    *) continue ;; # all zeros: branch deletion
    esac
    history_report "$local_sha" "$label" "" "$rebase_branch" >&2 || rc=1
  done <"$PUSH_INPUT_FILE"
  if [ "$rc" -ne 0 ]; then
    echo "bindle guardrail: push blocked — resolve the BLOCK items above, then push again." >&2
    exit 1
  fi
}

# `--history [--base REF] [REF]`: print the report on demand (stdout) for REF
# (default HEAD, may be detached); exits 1 on BLOCK, 2 on bad usage.
history_main() {
  local base="" tip="HEAD" label tip_sha rebase_branch
  shift
  while [ $# -gt 0 ]; do
    case "$1" in
    --base)
      [ $# -ge 2 ] || {
        echo "bindle history: --base needs a ref" >&2
        exit 2
      }
      base="$2"
      shift 2
      ;;
    --base=*)
      base="${1#--base=}"
      shift
      ;;
    -*)
      echo "bindle history: unknown option '$1'" >&2
      exit 2
      ;;
    *)
      tip="$1"
      shift
      ;;
    esac
  done
  tip_sha="$(git rev-parse --verify --quiet "$tip^{commit}" 2>/dev/null || true)"
  if [ -z "$tip_sha" ]; then
    echo "bindle history: cannot resolve '$tip' to a commit" >&2
    exit 2
  fi
  label="$tip"
  if [ "$tip" = "HEAD" ]; then
    label="$(current_branch)"
    [ -n "$label" ] || label="detached HEAD ($(git rev-parse --short "$tip_sha"))"
  fi
  rebase_branch=""
  if [ "$tip" != "HEAD" ] && git show-ref --verify --quiet "refs/heads/$tip"; then rebase_branch="$tip"; fi
  if history_report "$tip_sha" "$label" "$base" "$rebase_branch"; then exit 0; else exit 1; fi
}

if [ "${1:-}" = "--history" ]; then
  history_main "$@"
fi

case "$hook_name" in
pre-commit | pre-merge-commit | prepare-commit-msg | pre-rebase | pre-applypatch)
  check_protected_branch "$@"
  ;;
commit-msg)
  check_commit_message "$@"
  ;;
pre-push)
  check_push_history
  ;;
esac

# Delegate to the repo's OWN same-named hook with the original args/stdin; its
# exit status becomes ours. A direct path (not another core.hooksPath lookup)
# avoids recursion; --git-common-dir keeps it correct from any linked worktree
# (docs/WORKTREES.md).
native_hook="$(git rev-parse --path-format=absolute --git-common-dir)/hooks/$hook_name"
if [ -x "$native_hook" ]; then
  if [ "$hook_name" = "pre-push" ]; then
    # Replay saved stdin; not `exec`, so the EXIT trap can remove the temp file.
    if "$native_hook" "$@" <"$PUSH_INPUT_FILE"; then exit 0; else exit "$?"; fi
  fi
  exec "$native_hook" "$@"
fi
exit 0
