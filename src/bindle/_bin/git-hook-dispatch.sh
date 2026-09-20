#!/usr/bin/env bash
#
# git-hook-dispatch.sh — Bindle's single Git hook implementation. Installed
# once by bin/install-guardrails.sh and symlinked under every standard
# client-side Git hook name inside a global core.hooksPath directory, so
# this same file runs for every hook Git invokes, whichever name it was
# invoked as ($0's basename tells it).
#
# Rationale (plans/archive/2026-08-23-local-guardrail-layer.md, "Decisions"
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
# History guardrails (docs/DECISIONS.md D048) live here too, in the same
# single implementation: a commit-msg Conventional Commit check that also
# accepts Git's own fixup!/squash!/amend! control commits, and a pre-push
# "history hygiene" report that BLOCKs unpublished states (pending
# autosquash commits, non-conforming subjects) and only WARNs about
# mechanically observable churn. `git-hook-dispatch.sh --history` (also
# `bindle history`) prints the same report on demand. Everything is a regex,
# a count, or Git plumbing: no semantic judgment, no scoring, and nothing
# here ever rewrites history or touches the working tree.
#
set -euo pipefail

PROTECTED_BRANCH="main"

hook_name="$(basename "$0")"

# Nothing to protect or delegate to outside a Git working tree.
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [ "${1:-}" = "--history" ]; then
    echo "bindle history: not inside a Git working tree" >&2
    exit 2
  fi
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
  bindle branch <branch-name>

If this write to '$PROTECTED_BRANCH' is genuinely intentional, scope the
override to this one command (it does not persist to the next command):
  ALLOW_MAIN_WRITE=1 <your original command>
MSG
  exit 1
}

# ---------------------------------------------------------------------------
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
# ---------------------------------------------------------------------------

# The standard Conventional Commits / Cocogitto built-in types, unioned with
# any keys under [commit_types] in cog.toml (see commit_types below).
DEFAULT_COMMIT_TYPES="feat fix docs style refactor perf test build ci chore revert"
# Derived from this repository's own tracked layout (tests/, tests/test_*.py,
# bin/test-*.sh; the one lockfile is uv.lock) — not a guess at other stacks.
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

# cfg_int KEY DEFAULT — the configured non-negative integer, else DEFAULT.
cfg_int() {
  local v
  v="$(cfg "$1")"
  case "$v" in
  '' | *[!0-9]*) printf '%s\n' "$2" ;;
  *) printf '%s\n' "$v" ;;
  esac
}

# cfg_str KEY DEFAULT — the configured non-empty string, else DEFAULT.
cfg_str() {
  local v
  v="$(cfg "$1")"
  printf '%s\n' "${v:-$2}"
}

worktree_top() {
  git rev-parse --show-toplevel 2>/dev/null || true
}

# cog_toml_tracked — the worktree root has a cog.toml that Git tracks (in the
# index). An untracked or ignored local file must not change what a
# repository enforces.
cog_toml_tracked() {
  local top
  top="$(worktree_top)"
  [ -n "$top" ] && git -C "$top" ls-files --error-unmatch -- cog.toml >/dev/null 2>&1
}

# conventional_commits_enabled — this worktree has declared Conventional
# Commits: explicit bindle.conventionalCommits wins; otherwise a tracked
# cog.toml (Cocogitto, this repository's own commit validator) opts in.
# Repositories that declare nothing are never held to the convention.
conventional_commits_enabled() {
  case "$(git config --type=bool --get bindle.conventionalCommits 2>/dev/null || true)" in
  true) return 0 ;;
  false) return 1 ;;
  esac
  cog_toml_tracked
}

# commit_types — one accepted type per line: the defaults plus the keys of
# cog.toml's [commit_types] table, so cog.toml stays the single place a
# repository extends the list.
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

# parse_subject SUBJECT — classify a subject by pure pattern match. Sets
# SUBJ_KIND to autosquash | merge | revert | conventional | invalid, and
# SUBJ_DESC to a conventional subject's description. Requires
# load_commit_types to have run. A "merge" kind is only a prefix match: callers
# decide whether a real merge is in progress (commit-msg: MERGE_HEAD exists;
# pre-push: --no-merges already excluded every real merge).
parse_subject() {
  local s="$1" re='^((fixup|squash|amend)! )+[^[:space:]]'
  SUBJ_KIND=invalid
  SUBJ_DESC=""
  if [[ $s =~ $re ]]; then
    SUBJ_KIND=autosquash
  elif [[ $s == "Merge "* ]]; then
    SUBJ_KIND=merge
  elif re='^(Revert|Reapply) ".+"$' && [[ $s =~ $re ]]; then
    # Exactly the shape `git revert` generates (Reapply: reverting a revert).
    SUBJ_KIND=revert
  else
    re='^([A-Za-z][A-Za-z0-9_-]*)(\([^()[:space:]]+\))?!?: ([^[:space:]].*)$'
    if [[ $s =~ $re ]] && [[ "$COMMIT_TYPES" == *" ${BASH_REMATCH[1]} "* ]]; then
      SUBJ_KIND=conventional
      SUBJ_DESC="${BASH_REMATCH[3]}"
    fi
  fi
}

# merge_subject_is_git_generated SUBJECT — a "Merge …" subject is only taken
# on faith when Git is really creating/keeping a merge: a merge is in progress
# (MERGE_HEAD exists — true for clean and conflict-resolved merges alike), or
# this is an amend that leaves an existing merge commit's own subject as it is
# (HEAD has two parents and the subject is unchanged). A different "Merge …"
# subject on an ordinary commit is not Git-generated.
merge_subject_is_git_generated() {
  git rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1 && return 0
  git rev-parse -q --verify 'HEAD^2' >/dev/null 2>&1 && [ "$(git log -1 --format=%s HEAD 2>/dev/null)" = "$1" ]
}

# check_commit_message FILE — the commit-msg policy. A no-op unless the
# repository has declared Conventional Commits. Git-generated subjects
# (fixup!/squash!/amend! from `git commit --fixup/--squash`, `Revert "…"`
# from `git revert`) are valid by construction and skip the repository's
# own commit-msg hook, since `cog verify` cannot parse them. Merge subjects
# and conventional subjects fall through to that hook as before.
check_commit_message() {
  local file="${1:-}" subject
  conventional_commits_enabled || return 0
  load_commit_types
  # First line that is neither blank nor a `#` comment (git strips those
  # after this hook runs, not before).
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

# resolve_history_base [EXPLICIT] — the first resolvable ref out of: the
# explicit argument, bindle.historyBase, origin/main, main. Prints nothing
# if none resolves.
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

# history_report TIP LABEL [BASE] [REBASE_BRANCH] — print the history-hygiene
# report for the commits reachable from TIP but not from BASE. LABEL is
# display-only; REBASE_BRANCH is the LOCAL branch whose name may be appended
# to the fold hint (empty when what is pushed is HEAD or a raw sha, where the
# right thing to rebase is simply the checked-out branch). Returns 1 iff it
# printed a BLOCK line. Read-only: only `git log`/`rev-list`/`merge-base`/
# `patch-id`.
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

  # `set -e` does not apply inside a function that is called in an `||`/`if`
  # context, so failures of the calls this report depends on are handled
  # explicitly, and fail CLOSED: a report that could not read the history must
  # not print PASS lines.
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

  # --- subjects (BLOCK: autosquash, non-conforming; WARN: rework-shaped) ----
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
    # Name a branch only when the pushed local ref IS a local branch other than
    # the checked-out one (`git push origin other-branch`).
    rebase_target=""
    if [ -n "${4:-}" ] && [ "$4" != "$(current_branch)" ] && git show-ref --verify --quiet "refs/heads/$4"; then
      rebase_target=" $4"
    fi
    # Without --rebase-merges a rebase flattens the branch and replays every
    # upstream commit that came in through a merge.
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

  # --- per-commit size / test-only / file churn (one git log pass) ---------
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
  # Exact re-application: two commits on the branch with the same
  # `git patch-id --stable` carry the identical patch (revert-and-redo,
  # duplicated cherry-pick). No similarity scoring.
  pids="$(git log --no-merges -p --format='commit %H' "$range" | git patch-id --stable | awk '{ print $1 }')" || pids=""
  dups="$(printf '%s\n' "$pids" | awk 'NF { n++; if (!seen[$1]++) u++ } END { print n - u + 0 }')"

  # --- advisory signals: facts only, never a blocker ------------------------
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
  # Loops read their pipe to the end (no `head`): an early-closed pipe would
  # SIGPIPE `sort` and, under pipefail + errexit, abort the whole hook.
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

# check_push_history — the pre-push policy: run the report for every branch
# update being pushed (from the ref list git feeds on stdin, never from the
# checked-out HEAD) and refuse the push if any report has a BLOCK line. Never
# rewrites anything.
#
# Which updates count: any update whose LOCAL ref or REMOTE ref is a branch.
# `git push origin HEAD`, `HEAD:refs/heads/x`, and `<sha>:refs/heads/x` all
# arrive with a local ref that is not refs/heads/… (literally "HEAD", or the
# raw expression), so the remote ref supplies the branch name. Deletions
# (all-zero local sha) and tag/notes/other-ref updates are not inspected.
check_push_history() {
  local local_ref local_sha remote_ref label rebase_branch rc=0
  # stdin is consumed here; keep a byte-exact copy so a repository-native
  # pre-push hook still receives exactly what git sent (see delegation below).
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

# history_main ARGS... — `--history [--base REF] [REF]`: print the report on
# demand (stdout) for REF (default HEAD, which may be detached). Exits 1 on
# a BLOCK line, 2 on bad usage.
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

# Transparent delegation: run the repository's OWN hook of this name, if it
# has one, with the original args/stdin, and let its exit status become
# ours. Resolved as a direct filesystem path (not another core.hooksPath
# lookup), so there is no recursion risk. --git-common-dir keeps this
# correct from any linked worktree (docs/WORKTREES.md): hooks are shared
# repository-level state, not per-worktree.
native_hook="$(git rev-parse --path-format=absolute --git-common-dir)/hooks/$hook_name"
if [ -x "$native_hook" ]; then
  if [ "$hook_name" = "pre-push" ]; then
    # check_push_history already drained stdin; replay the saved bytes. Not
    # `exec`, so the EXIT trap can still remove the temp file.
    if "$native_hook" "$@" <"$PUSH_INPUT_FILE"; then exit 0; else exit "$?"; fi
  fi
  exec "$native_hook" "$@"
fi
exit 0
