#!/usr/bin/env bash
#
# check-private-info.sh — scan committed/staged content for personal info that
# must never land in a repo: private-relay emails, local home paths, vault
# paths, pasted chat transcripts, private scratch files, and your own denylist
# terms. Offline, plain grep, deliberately boring — read it, edit it.
#
# This catches PERSONAL info (things that identify you); secret material
# (keys, tokens) is covered by detect-private-key and Gitleaks (.gitleaks.toml).
# See docs/privacy-boundaries.md for the full model.
#
# Usage:
#   bin/check-private-info.sh              # scan all tracked files
#   bin/check-private-info.sh FILE...      # scan specific files (pre-commit)
#   bin/check-private-info.sh --self-test  # prove the patterns catch fixtures
#   bin/check-private-info.sh --audit-denylist  # prove each denylist term
#                                          # has ZERO tracked hits (#271)
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
# patterns (this script, the Gitleaks config).
#
set -uo pipefail # not -e: aggregate every finding, then fail once

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# Denylist resolution. An explicit BINDLE_DENYLIST/CLAUDE_KIT_DENYLIST always
# wins; otherwise the denylist lives at the NOTES HOME ROOT, exactly where the
# session-continuity skill documents it. That home is BINDLE_NOTES_DIR when set
# (deprecated: CLAUDE_KIT_NOTES_DIR), so relocating the notes home — to an
# Obsidian vault, say — moves the denylist with it. ~/.bindle and ~/.claude-kit
# are the defaults when no notes home is configured.
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

# Where a MISSING denylist should be created. This is advertising, not
# resolution: ~/.claude-kit stays readable above but is never suggested (#289),
# because a reader who acts on it loses the denylist the moment a notes home is
# set or moved. An explicit override names itself — you asked for that path.
if [ -n "${BINDLE_DENYLIST:-}" ] || [ -n "${CLAUDE_KIT_DENYLIST:-}" ]; then
  DENYLIST_SUGGESTED="$DENYLIST"
elif [ -n "${BINDLE_NOTES_DIR:-}" ]; then
  DENYLIST_SUGGESTED="$BINDLE_NOTES_DIR/private-denylist.txt"
elif [ -n "${CLAUDE_KIT_NOTES_DIR:-}" ]; then
  DENYLIST_SUGGESTED="$CLAUDE_KIT_NOTES_DIR/private-denylist.txt"
else
  DENYLIST_SUGGESTED="$HOME/.bindle/private-denylist.txt"
fi

# Files allowed to contain the patterns below, because documenting/encoding
# them is their job. Keep this list short and literal.
SKIP_FILES=(
  ".gitleaks.toml"
  "bin/check-private-info.sh"
)

# label<TAB>extended-regex — the content patterns. Edit freely.
PATTERNS="apple-private-relay	[A-Za-z0-9._%+-]+@privaterelay\.appleid\.com
local-home-path	/Users/[A-Za-z][A-Za-z0-9._-]*
obsidian-vault-path	iCloud~md~obsidian|Mobile Documents/[^ ]*[Oo]bsidian
chat-transcript	^(Human|Assistant|USER|ASSISTANT): |^You said:|^(ChatGPT|Claude) said:"

# Tracked paths that should never be committed at all (the .gitignore patterns,
# enforced against force-adds). .env.example is the one allowed exception.
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

# scan_file FILE — run every content pattern (and the denylist) over FILE.
# Lines carrying a 'private-ok' marker are vouched-for and skipped.
scan_file() {
  local f="$1" label re hits
  [ -f "$f" ] || return 0
  is_skipped "$f" && return 0
  while IFS=$'\t' read -r label re; do
    [ -n "$label" ] || continue
    hits="$(grep -InE "$re" "$f" 2>/dev/null | grep -v 'private-ok' || true)"
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
      hits="$(grep -InFi "$term" "$f" 2>/dev/null | grep -v 'private-ok' || true)"
      if [ -n "$hits" ]; then
        while IFS= read -r line; do
          finding "$f:$line [denylist]"
        done <<<"$hits"
      fi
    done <"$DENYLIST"
  fi
}

# scan_verdict FILE — echo the fail flag scan_file would set, in isolation.
# The subshell keeps the fixture verdicts away from the real scan's fail flag.
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
  # env -u clears the operator's own denylist vars so an ambient BINDLE_DENYLIST
  # (higher precedence, line ~44) can't shadow the alias under test and produce
  # a false pass/fail depending on what happens to be exported in this shell.
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
  # The denylist follows the NOTES HOME (session-continuity's contract), not a
  # hardcoded ~/.bindle. These run the real script so the resolution chain — not
  # just scan_file — is what is under test. `env -u` clears the operator's own
  # notes-home vars so a real one can't decide a fixture's verdict.
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
  # BINDLE_DENYLIST still outranks the notes home: an empty override must win
  # over a notes-home denylist that would otherwise flag this fixture.
  if env -u CLAUDE_KIT_DENYLIST -u CLAUDE_KIT_NOTES_DIR \
    BINDLE_DENYLIST=/dev/null BINDLE_NOTES_DIR="$t/notes" \
    "$0" "$t/denylist.md" >/dev/null 2>&1; then
    pass=$((pass + 1))
  else
    printf '  ✗ self-test: BINDLE_DENYLIST no longer outranks BINDLE_NOTES_DIR\n'
    failed=1
  fi
  # A clean verdict must say whether personal terms were actually checked —
  # "no denylist loaded" and "denylist loaded, nothing matched" are different
  # facts and must not print the same line.
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
  # The path the message ADVERTISES is where a denylist should be created, not
  # the deprecated ~/.claude-kit read fallback (#289) — a reader who follows it
  # must land somewhere that survives setting or moving $BINDLE_NOTES_DIR.
  # Captured, not piped: with pipefail a `grep -q` that matches early SIGPIPEs
  # the scanner, and the pipeline then reports 141 even though the match hit.
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
  # A 0-term denylist (a freshly scaffolded comments-only template) must
  # yield a clean ONE-LINE verdict — `grep -c … || echo 0` prints "0" twice
  # when the count is 0, splitting the verdict across two lines.
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

# --- denylist audit (#271) --------------------------------------------------
#
# The selection rule (docs/privacy-boundaries.md): a term belongs on the
# denylist only if it should appear ZERO times in tracked content, forever —
# a term that legitimately appears floods every commit with findings. This
# mode proves each term BEFORE it starts doing that. Raw truth on purpose:
# no SKIP_FILES, no private-ok vouching — a vouched line still proves the
# term lives in the repo.
if [ "${1:-}" = "--audit-denylist" ]; then
  echo "denylist audit:"
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "  ✗ not inside a git repository — nothing tracked to audit against"
    exit 1
  fi
  if [ ! -f "$DENYLIST" ]; then
    echo "  - no denylist at $DENYLIST_SUGGESTED — nothing to audit"
    echo "    scaffold one: bin/notes-home.sh init-denylist"
    exit 0
  fi
  audit_terms=0
  while IFS= read -r term; do
    case "$term" in '' | \#*) continue ;; esac
    audit_terms=$((audit_terms + 1))
    if [ "${#term}" -lt 4 ]; then
      echo "  - warning: \"$term\" is only ${#term} chars — short terms over-match inside ordinary words"
    fi
    hits="$(git grep -Iin --fixed-strings -- "$term" 2>/dev/null || true)"
    if [ -n "$hits" ]; then
      hit_count="$(grep -c . <<<"$hits")"
      finding "\"$term\" matches tracked content ($hit_count line(s)) — it would flag every commit:"
      head -n 3 <<<"$hits" | sed 's/^/      /'
      [ "$hit_count" -gt 3 ] && echo "      … and $((hit_count - 3)) more"
    fi
  done <"$DENYLIST"
  echo
  # shellcheck disable=SC2031 # only the audit loop above touches fail here
  if [ "$fail" -eq 0 ]; then
    ok "$audit_terms term(s) audited — zero tracked hits"
    exit 0
  fi
  echo "Terms above already appear in tracked content — per the selection rule"
  echo "(docs/privacy-boundaries.md) remove or narrow them before relying on the denylist."
  exit 1
fi

echo "private-info scan:"

# --- 1. no private-by-path files are tracked/staged ------------------------
if [ $# -gt 0 ]; then
  path_hits="$(printf '%s\n' "$@" | grep -E "$PRIVATE_PATH_RE" | grep -v '\.env\.example$' || true)"
else
  path_hits="$(git ls-files | grep -E "$PRIVATE_PATH_RE" | grep -v '\.env\.example$' || true)"
fi
if [ -n "$path_hits" ]; then
  while IFS= read -r p; do
    finding "$p [private file committed — belongs outside the repo or in .gitignore]"
  done <<<"$path_hits"
fi

# --- 2. content patterns + denylist ----------------------------------------
#
# SCOPE, not just verdict (#347). Both enumerations above are `git ls-files`,
# so an UNTRACKED file is outside this scan entirely — and "no private info
# found" reads identically whether the tree was clean or the files under test
# were simply invisible. PR #345 shipped three home-path hits through exactly
# that gap: green before `git add`, red after. Ignored files are out of scope
# by intent and are not counted; a banner that is always on is never read.
scanned=0
if [ $# -gt 0 ]; then
  for f in "$@"; do
    scan_file "$f"
    scanned=$((scanned + 1))
  done
  # Explicit-file mode (pre-commit): the scope IS the argument list, so there
  # is nothing undisclosed to report.
  SKIPPED=""
else
  while IFS= read -r f; do
    scan_file "$f"
    scanned=$((scanned + 1))
  done < <(git ls-files)
  SKIPPED="$(git ls-files --others --exclude-standard)"
fi

# Whether personal terms were checked at all is part of the verdict: a clean
# run with no denylist proves the PATTERNS held, not that your personal terms
# were absent. Never let those two print the same line.
if [ -f "$DENYLIST" ]; then
  # Not `|| echo 0`: grep -c already prints 0 (and exits 1) on no match, so
  # the fallback would print a SECOND 0 and split the verdict across lines.
  denylist_terms="$(grep -cvE '^[[:space:]]*(#|$)' "$DENYLIST" 2>/dev/null)"
  [ -n "$denylist_terms" ] || denylist_terms=0
  DENYLIST_VERDICT="$denylist_terms denylist terms checked"
else
  DENYLIST_VERDICT="pattern rules only — NO personal denylist loaded"
  echo "  - no personal denylist at $DENYLIST_SUGGESTED (optional; one term per line)"
  echo "    it belongs at the notes home root — \$BINDLE_NOTES_DIR when set,"
  echo "    else ~/.bindle — or point \$BINDLE_DENYLIST at it directly"
fi

# Scope banner. Prints on a red run too: fixing the findings must not silently
# promote a partial scan into an unqualified pass.
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
  ok "no private info found — $scanned files scanned ($DENYLIST_VERDICT)"
else
  echo "Private info found — fix, or mark a false positive with 'private-ok'."
fi
# shellcheck disable=SC2031
exit "$fail"
