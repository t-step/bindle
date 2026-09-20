#!/usr/bin/env bash
#
# check-private-info.sh — scan committed/staged content for personal info that
# must never land in a repo: private-relay emails, local home paths, vault
# paths, pasted chat transcripts, private scratch files, and your own denylist
# terms. Offline, plain grep, deliberately boring — read it, edit it.
#
# This catches PERSONAL info (things that identify you); secret material
# (keys, tokens, credentials) is a separate concern handled by the secrets
# rules in AGENTS.md. See docs/PRIVACY.md for the full disclosure model.
#
# Usage:
#   bin/check-private-info.sh              # scan all tracked files
#   bin/check-private-info.sh --staged     # scan the INDEX content that a
#                                          # commit would actually write —
#                                          # this is the safe pre-commit mode
#   bin/check-private-info.sh FILE...      # scan specific working-tree files
#   bin/check-private-info.sh --self-test  # prove the patterns catch fixtures
#   bin/check-private-info.sh --audit-denylist  # prove each denylist term
#                                          # has ZERO unvouched tracked hits
#                                          # (a private-ok'd occurrence does
#                                          # not count) (#271)
#
# Personal denylist: one term per line (case-insensitive fixed strings; '#'
# comments) at private-denylist.txt in the NOTES HOME ROOT — $BINDLE_NOTES_DIR
# when set, else ~/.bindle — or point BINDLE_DENYLIST at another file to
# override. Deprecated CLAUDE_KIT_DENYLIST, CLAUDE_KIT_NOTES_DIR, and
# ~/.claude-kit aliases remain supported. The denylist itself is personal —
# never commit it.
#
# A clean run reports whether a denylist was loaded: passing with none loaded
# means the PATTERNS held, not that your personal terms were checked.
#
# False positives: append 'private-ok' to the specific line to vouch for it,
# or add a path to SKIP_FILES below for files that must discuss these
# patterns (this script itself).
#
set -uo pipefail # not -e: aggregate every finding, then fail once

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# Explicit override wins; else the denylist follows the notes home (PRIVACY.md).
if [ -n "${BINDLE_DENYLIST:-}" ]; then
  DENYLIST="$BINDLE_DENYLIST"
elif [ -n "${CLAUDE_KIT_DENYLIST:-}" ]; then
  DENYLIST="$CLAUDE_KIT_DENYLIST"
elif [ -n "${BINDLE_NOTES_DIR:-}" ] && [ -f "$BINDLE_NOTES_DIR/private-denylist.txt" ]; then
  DENYLIST="$BINDLE_NOTES_DIR/private-denylist.txt"
elif [ -n "${CLAUDE_KIT_NOTES_DIR:-}" ] && [ -f "$CLAUDE_KIT_NOTES_DIR/private-denylist.txt" ]; then
  DENYLIST="$CLAUDE_KIT_NOTES_DIR/private-denylist.txt"
elif [ -f "$HOME/.bindle/private-denylist.txt" ]; then
  DENYLIST="$HOME/.bindle/private-denylist.txt"
else
  DENYLIST="$HOME/.claude-kit/private-denylist.txt"
fi

# Where to advise creating a MISSING denylist: never ~/.claude-kit (#289), which
# stops being read once a notes home is set or moved.
if [ -n "${BINDLE_DENYLIST:-}" ] || [ -n "${CLAUDE_KIT_DENYLIST:-}" ]; then
  DENYLIST_SUGGESTED="$DENYLIST"
elif [ -n "${BINDLE_NOTES_DIR:-}" ]; then
  DENYLIST_SUGGESTED="$BINDLE_NOTES_DIR/private-denylist.txt"
elif [ -n "${CLAUDE_KIT_NOTES_DIR:-}" ]; then
  DENYLIST_SUGGESTED="$CLAUDE_KIT_NOTES_DIR/private-denylist.txt"
else
  DENYLIST_SUGGESTED="$HOME/.bindle/private-denylist.txt"
fi

# Files whose job is to document/encode the patterns; keep short and literal.
SKIP_FILES=(
  ".gitleaks.toml"
  "bin/check-private-info.sh"
)

# label<TAB>extended-regex — the content patterns. Edit freely.
PATTERNS="apple-private-relay	[A-Za-z0-9._%+-]+@privaterelay\.appleid\.com
local-home-path	/Users/[A-Za-z][A-Za-z0-9._-]*
obsidian-vault-path	iCloud~md~obsidian|Mobile Documents/[^ ]*[Oo]bsidian
chat-transcript	^(Human|Assistant|USER|ASSISTANT): |^You said:|^(ChatGPT|Claude) said:"

# Paths never to commit (.gitignore's, enforced vs force-adds); .env.example ok.
PRIVATE_PATH_RE='(^|/)(\.claude-(private|local|session|scratch)|\.superpowers|notes-private|session-notes|personal-notes)(/|$)|\.private\.md$|\.local\.md$|(^|/)\.scratch\.md$|(^|/)\.env(\.[^/]*)?$'

fail=0
finding() {
  printf '  ✗ %s\n' "$1"
  fail=1
}
ok() { printf '  ✓ %s\n' "$1"; }

is_skipped() {
  local f="$1" s
  for s in "${SKIP_FILES[@]}"; do
    [ "$f" = "$s" ] && return 0
  done
  return 1
}

# scan_bytes FILE — scan stdin, labeled FILE, skipping 'private-ok' lines. Stdin
# lets callers feed the bytes about to be committed, not the working tree.
scan_bytes() {
  local f="$1" content label re hits
  is_skipped "$f" && return 0
  content="$(cat)"
  while IFS=$'\t' read -r label re; do
    [ -n "$label" ] || continue
    hits="$(grep -InE "$re" <<<"$content" 2>/dev/null | grep -v 'private-ok' || true)"
    if [ -n "$hits" ]; then
      while IFS= read -r line; do
        finding "$f:$line [$label]"
      done <<<"$hits"
    fi
  done <<<"$PATTERNS"
  if [ -f "$DENYLIST" ]; then
    local term
    while IFS= read -r term; do
      case "$term" in '' | \#*) continue ;; esac
      hits="$(grep -InFi "$term" <<<"$content" 2>/dev/null | grep -v 'private-ok' || true)"
      if [ -n "$hits" ]; then
        while IFS= read -r line; do
          finding "$f:$line [denylist]"
        done <<<"$hits"
      fi
    done <"$DENYLIST"
  fi
}

scan_file() {
  local f="$1"
  [ -f "$f" ] || return 0
  # shellcheck disable=SC2094 # read-only: scan_bytes never writes to $f
  scan_bytes "$f" <"$f"
}

# Scans the index blob, so staging private content then cleaning the working
# tree can't slip past. No index entry scans as empty, which is not a finding.
scan_staged() {
  local f="$1"
  # Not a pipe: scan_bytes in a subshell would lose finding()'s fail=1.
  scan_bytes "$f" < <(git show ":$f" 2>/dev/null)
}

# Echoes the fail flag scan_file would set; the subshell isolates it from the
# real scan's fail flag.
# shellcheck disable=SC2030,SC2031
scan_verdict() {
  (
    fail=0
    scan_file "$1" >/dev/null
    echo "$fail"
  )
}

self_test() {
  local t pass=0 failed=0 f advice
  t="$(mktemp -d)"
  # each fixture must be FLAGGED
  printf 'contact me: abc.123@privaterelay.appleid.com\n' >"$t/relay.md"
  printf 'clone into /Users/jane/Developer/proj\n' >"$t/homepath.md"
  printf 'vault: ~/Library/Mobile Documents/iCloud~md~obsidian/Documents/v\n' >"$t/vault.md"
  printf 'Human: please fix this\nAssistant: sure\n' >"$t/transcript.md"
  printf 'my secret term: xyzzy-internal\n' >"$t/denylist.md"
  # denylist matching is case-insensitive: term 'Dana' must catch dana/DANA
  printf 'lower dana, upper DANA, mixed dAnA\n' >"$t/casefold.md"
  # these must PASS
  printf 'normal doc, mentions ~/.claude and docs/foo.md\n' >"$t/clean.md"
  printf 'example: /Users/jane/x is bad  <- private-ok\n' >"$t/vouched.md"
  printf 'xyzzy-internal\n' >"$t/deny.txt"
  printf 'Dana\n' >"$t/deny-name.txt"

  # DENYLIST=/dev/null keeps your real denylist out of the fixtures' verdicts.
  for f in relay homepath vault transcript; do
    if [ "$(DENYLIST=/dev/null scan_verdict "$t/$f.md")" = 1 ]; then
      pass=$((pass + 1))
    else
      printf '  ✗ self-test: %s.md NOT flagged\n' "$f"
      failed=1
    fi
  done
  if [ "$(DENYLIST="$t/deny.txt" scan_verdict "$t/denylist.md")" = 1 ]; then
    pass=$((pass + 1))
  else
    printf '  ✗ self-test: denylist.md NOT flagged\n'
    failed=1
  fi
  # env -u: an ambient BINDLE_DENYLIST outranks the alias under test.
  if env -u CLAUDE_KIT_DENYLIST BINDLE_DENYLIST="$t/deny.txt" "$0" "$t/denylist.md" >/dev/null 2>&1; then
    printf '  ✗ self-test: BINDLE_DENYLIST alias NOT honored\n'
    failed=1
  else
    pass=$((pass + 1))
  fi
  if env -u BINDLE_DENYLIST CLAUDE_KIT_DENYLIST="$t/deny.txt" "$0" "$t/denylist.md" >/dev/null 2>&1; then
    printf '  ✗ self-test: CLAUDE_KIT_DENYLIST alias NOT honored\n'
    failed=1
  else
    pass=$((pass + 1))
  fi
  if [ "$(DENYLIST="$t/deny-name.txt" scan_verdict "$t/casefold.md")" = 1 ]; then
    pass=$((pass + 1))
  else
    printf '  ✗ self-test: casefold.md NOT flagged (denylist not case-insensitive)\n'
    failed=1
  fi
  for f in clean vouched; do
    if [ "$(DENYLIST=/dev/null scan_verdict "$t/$f.md")" = 0 ]; then
      pass=$((pass + 1))
    else
      printf '  ✗ self-test: %s.md wrongly flagged\n' "$f"
      failed=1
    fi
  done
  # a private-by-path filename must be refused even as an explicit argument
  if "$0" "$t/session-notes/leak.md" >/dev/null 2>&1; then
    printf '  ✗ self-test: private path session-notes/ NOT flagged\n'
    failed=1
  else
    pass=$((pass + 1))
  fi
  # Denylist follows the notes home (session-continuity contract); run the real
  # script so the resolution chain is under test, env -u drops the operator's.
  mkdir -p "$t/notes" "$t/kitnotes" "$t/nohome"
  cp "$t/deny.txt" "$t/notes/private-denylist.txt"
  cp "$t/deny.txt" "$t/kitnotes/private-denylist.txt"
  if env -u BINDLE_DENYLIST -u CLAUDE_KIT_DENYLIST -u CLAUDE_KIT_NOTES_DIR \
    BINDLE_NOTES_DIR="$t/notes" "$0" "$t/denylist.md" >/dev/null 2>&1; then
    printf '  ✗ self-test: BINDLE_NOTES_DIR denylist NOT resolved\n'
    failed=1
  else
    pass=$((pass + 1))
  fi
  if env -u BINDLE_DENYLIST -u CLAUDE_KIT_DENYLIST -u BINDLE_NOTES_DIR \
    CLAUDE_KIT_NOTES_DIR="$t/kitnotes" "$0" "$t/denylist.md" >/dev/null 2>&1; then
    printf '  ✗ self-test: deprecated CLAUDE_KIT_NOTES_DIR denylist NOT resolved\n'
    failed=1
  else
    pass=$((pass + 1))
  fi
  # An empty BINDLE_DENYLIST must outrank a notes-home denylist that would flag.
  if env -u CLAUDE_KIT_DENYLIST -u CLAUDE_KIT_NOTES_DIR \
    BINDLE_DENYLIST=/dev/null BINDLE_NOTES_DIR="$t/notes" \
    "$0" "$t/denylist.md" >/dev/null 2>&1; then
    pass=$((pass + 1))
  else
    printf '  ✗ self-test: BINDLE_DENYLIST no longer outranks BINDLE_NOTES_DIR\n'
    failed=1
  fi
  # A clean verdict must tell "no denylist loaded" from "nothing matched".
  if env -u BINDLE_DENYLIST -u CLAUDE_KIT_DENYLIST -u BINDLE_NOTES_DIR \
    -u CLAUDE_KIT_NOTES_DIR HOME="$t/nohome" "$0" "$t/clean.md" 2>&1 |
    grep -q 'pattern rules only'; then
    pass=$((pass + 1))
  else
    printf '  ✗ self-test: clean verdict does not disclose that NO denylist was loaded\n'
    failed=1
  fi
  if env -u BINDLE_DENYLIST -u CLAUDE_KIT_DENYLIST -u CLAUDE_KIT_NOTES_DIR \
    BINDLE_NOTES_DIR="$t/notes" "$0" "$t/clean.md" 2>&1 |
    grep -q 'denylist terms checked'; then
    pass=$((pass + 1))
  else
    printf '  ✗ self-test: clean verdict does not disclose that a denylist WAS loaded\n'
    failed=1
  fi
  # The advertised path must not be the deprecated ~/.claude-kit (#289).
  # Captured, not piped: under pipefail an early `grep -q` match SIGPIPEs the
  # scanner and the pipeline reports 141.
  advice="$(env -u BINDLE_DENYLIST -u CLAUDE_KIT_DENYLIST -u CLAUDE_KIT_NOTES_DIR \
    BINDLE_NOTES_DIR="$t/nohome" HOME="$t/nohome" "$0" "$t/clean.md" 2>&1)"
  if grep -qF "no personal denylist at $t/nohome/private-denylist.txt" <<<"$advice"; then
    pass=$((pass + 1))
  else
    printf '  ✗ self-test: missing-denylist message does not name the notes home\n'
    failed=1
  fi
  advice="$(env -u BINDLE_DENYLIST -u CLAUDE_KIT_DENYLIST -u CLAUDE_KIT_NOTES_DIR \
    -u BINDLE_NOTES_DIR HOME="$t/nohome" "$0" "$t/clean.md" 2>&1)"
  if grep -qF "no personal denylist at $t/nohome/.bindle/private-denylist.txt" <<<"$advice"; then
    pass=$((pass + 1))
  else
    printf '  ✗ self-test: missing-denylist message does not default to ~/.bindle\n'
    failed=1
  fi
  # A comments-only denylist must give a ONE-LINE verdict (`grep -c || echo 0`
  # prints "0" twice on no match).
  printf '# only comments, no terms yet\n' >"$t/deny-empty.txt"
  advice="$(env -u CLAUDE_KIT_DENYLIST -u BINDLE_NOTES_DIR -u CLAUDE_KIT_NOTES_DIR \
    BINDLE_DENYLIST="$t/deny-empty.txt" "$0" "$t/clean.md" 2>&1)"
  if grep -qF '(0 denylist terms checked)' <<<"$advice"; then
    pass=$((pass + 1))
  else
    printf '  ✗ self-test: 0-term denylist verdict is mangled\n'
    failed=1
  fi
  # ...and the deprecated location stays READABLE while never being advertised.
  mkdir -p "$t/kithome/.claude-kit"
  cp "$t/deny.txt" "$t/kithome/.claude-kit/private-denylist.txt"
  if env -u BINDLE_DENYLIST -u CLAUDE_KIT_DENYLIST -u CLAUDE_KIT_NOTES_DIR \
    -u BINDLE_NOTES_DIR HOME="$t/kithome" "$0" "$t/denylist.md" >/dev/null 2>&1; then
    printf '  ✗ self-test: deprecated ~/.claude-kit denylist NOT resolved\n'
    failed=1
  else
    pass=$((pass + 1))
  fi
  rm -rf "$t"
  printf '  self-test: %d/20 fixtures behaved\n' "$pass"
  return "$failed"
}

if [ "${1:-}" = "--self-test" ]; then
  echo "private-info self-test:"
  if self_test; then
    ok "scanner catches all fixtures, passes clean files"
    exit 0
  else
    echo "private-info self-test FAILED."
    exit 1
  fi
fi

# Denylist audit (#271): a term needs ZERO unvouched tracked hits (PRIVACY.md).
# SKIP_FILES doesn't apply: a skipped file's content is still tracked content.
if [ "${1:-}" = "--audit-denylist" ]; then
  echo "denylist audit:"
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "  ✗ not inside a git repository — nothing tracked to audit against"
    exit 1
  fi
  if [ ! -f "$DENYLIST" ]; then
    echo "  - no denylist at $DENYLIST_SUGGESTED — nothing to audit"
    echo "    create one manually — one term per line, '#' comments"
    exit 0
  fi
  audit_terms=0
  while IFS= read -r term; do
    case "$term" in '' | \#*) continue ;; esac
    audit_terms=$((audit_terms + 1))
    if [ "${#term}" -lt 4 ]; then
      echo "  - warning: \"$term\" is only ${#term} chars — short terms over-match inside ordinary words"
    fi
    hits="$(git grep -Iin --fixed-strings -- "$term" 2>/dev/null | grep -v 'private-ok' || true)"
    if [ -n "$hits" ]; then
      hit_count="$(grep -c . <<<"$hits")"
      finding "\"$term\" has $hit_count unvouched tracked occurrence(s) — it would flag every commit:"
      head -n 3 <<<"$hits" | sed 's/^/      /'
      [ "$hit_count" -gt 3 ] && echo "      … and $((hit_count - 3)) more"
    fi
  done <"$DENYLIST"
  echo
  # shellcheck disable=SC2031 # only the audit loop above touches fail here
  if [ "$fail" -eq 0 ]; then
    ok "$audit_terms term(s) audited — zero unvouched tracked hits"
    exit 0
  fi
  echo "Terms above have unvouched hits in tracked content — per the selection"
  echo "rule (docs/PRIVACY.md) narrow them, remove them, or add 'private-ok' to"
  echo "the specific legitimate occurrence before relying on the denylist."
  exit 1
fi

echo "private-info scan:"

MODE="tree"
noun="files"
SCAN_FILES=()
if [ "${1:-}" = "--staged" ]; then
  MODE="staged"
  noun="staged file(s)"
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "  ✗ not inside a git repository — nothing staged to scan"
    exit 1
  fi
  # mapfile is bash 4+ but macOS system bash is 3.2: build the array by hand.
  while IFS= read -r f; do
    SCAN_FILES+=("$f")
  done < <(git diff --cached --name-only --diff-filter=ACMRT)
elif [ $# -gt 0 ]; then
  MODE="explicit"
  SCAN_FILES=("$@")
else
  while IFS= read -r f; do
    SCAN_FILES+=("$f")
  done < <(git ls-files)
fi

if [ "${#SCAN_FILES[@]}" -gt 0 ]; then
  path_hits="$(printf '%s\n' "${SCAN_FILES[@]}" | grep -E "$PRIVATE_PATH_RE" | grep -v '\.env\.example$' || true)"
else
  path_hits=""
fi
if [ -n "$path_hits" ]; then
  while IFS= read -r p; do
    finding "$p [private file committed — belongs outside the repo or in .gitignore]"
  done <<<"$path_hits"
fi

# Tree mode is `git ls-files`, so untracked files are invisible and a clean
# verdict can hide that (#347; PR #345 shipped home-path hits that way).
# Ignored files are out of scope by intent; an always-on banner is never read.
scanned=0
SKIPPED=""
# bash <4.4 treats "${arr[@]}" on an empty array as unbound under set -u; guard
# the expansion rather than drop set -u.
if [ "${#SCAN_FILES[@]}" -gt 0 ]; then
  for f in "${SCAN_FILES[@]}"; do
    if [ "$MODE" = "staged" ]; then
      scan_staged "$f"
    else
      scan_file "$f"
    fi
    scanned=$((scanned + 1))
  done
fi
if [ "$MODE" = "tree" ]; then
  # Staged/explicit modes scan exactly the enumerated list: nothing undisclosed.
  SKIPPED="$(git ls-files --others --exclude-standard)"
fi

# A clean run with no denylist proves only the PATTERNS held; never print it
# like one with a denylist loaded.
if [ -f "$DENYLIST" ]; then
  # Not `|| echo 0`: grep -c already prints 0 on no match, so it prints twice.
  denylist_terms="$(grep -cvE '^[[:space:]]*(#|$)' "$DENYLIST" 2>/dev/null)"
  [ -n "$denylist_terms" ] || denylist_terms=0
  DENYLIST_VERDICT="$denylist_terms denylist terms checked"
else
  DENYLIST_VERDICT="pattern rules only — NO personal denylist loaded"
  echo "  - no personal denylist at $DENYLIST_SUGGESTED (optional; one term per line)"
  echo "    it belongs at the notes home root — \$BINDLE_NOTES_DIR when set,"
  echo "    else ~/.bindle — or point \$BINDLE_DENYLIST at it directly"
fi

# Prints on a red run too: fixing findings must not promote a partial scan.
if [ -n "$SKIPPED" ]; then
  skipped_n="$(grep -c . <<<"$SKIPPED")"
  echo
  echo "  PARTIAL: $skipped_n untracked file(s) were NOT scanned —"
  head -n 10 <<<"$SKIPPED" | while IFS= read -r p; do echo "    $p"; done
  [ "$skipped_n" -gt 10 ] && echo "    … and $((skipped_n - 10)) more"
  echo "    stage them (git add) and re-run before quoting this result."
fi

echo
# The self-test's subshell writes to its own copy of fail on purpose (SC2031);
# by this point only the real scan above has touched this one.
# shellcheck disable=SC2031
if [ "$fail" -eq 0 ]; then
  ok "no private info found — $scanned $noun scanned ($DENYLIST_VERDICT)"
else
  echo "Private info found — fix, or mark a false positive with 'private-ok'."
fi
# shellcheck disable=SC2031
exit "$fail"
