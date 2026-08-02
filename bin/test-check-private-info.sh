#!/usr/bin/env bash
#
# test-check-private-info.sh — carry bin/check-private-info.sh's --self-test
# into the discovered-suite gate, and prove that self-test is itself failable.
#
# The scanner's self-test is what proves the pattern rules still catch a relay
# email, a home path, a vault path, a transcript, and a denylist term. Before
# #279 it ran at exactly ONE call site — bin/check.sh section 7, inside the
# `if ! $content_only` branch — so only a full local `make check` reached it.
# The `bindle-private-info` hook runs the SCAN, never the self-test; CI runs
# `pre-commit run --all-files`, which inherits exactly that. So a regression in
# the scanner's own rules landed green. Same defect class as #256/#257: a real
# test that never reached the gate because it lived inside an aggregate script
# instead of being discoverable.
#
# This suite is discovered by `bindle-test-suites` (#256, #257), so the
# self-test now reaches the commit gate and CI with no registration edit.
# check.sh section 7 still calls `--self-test` directly and this suite calls
# the same entrypoint: one code path, two callers, so they cannot silently
# diverge. Neither runs a second full-tree scan — the tree sweep stays with
# check.sh section 7 and the `bindle-private-info` hook.
#
# Usage: bin/test-check-private-info.sh
#
set -uo pipefail

# Under a git hook (pre-commit/post-merge), git exports GIT_DIR and friends to
# subprocesses; in a worktree GIT_DIR is absolute, so a fixture git call would
# hit the real repository. Scrub the hook environment.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCANNER="$REPO_ROOT/bin/check-private-info.sh"

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

# shellcheck disable=SC2329 # invoked indirectly, by name, via check
contains() { grep -qF -- "$1" <<<"$2"; } # contains NEEDLE HAYSTACK
# shellcheck disable=SC2329 # invoked indirectly, by name, via check
not_contains() { ! grep -qF -- "$1" <<<"$2"; } # not_contains NEEDLE HAYSTACK

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ===========================================================================
echo "scanner self-test reaches this gate:"

selftest_out="$("$SCANNER" --self-test 2>&1)"
selftest_rc=$?

check "bin/check-private-info.sh --self-test exits clean" [ "$selftest_rc" -eq 0 ]
check "reports the scanner catches fixtures and passes clean files" \
  contains "scanner catches all fixtures, passes clean files" "$selftest_out"

# ===========================================================================
echo "self-test coverage floor:"

# The self-test prints "  self-test: <behaved>/<total> fixtures behaved". A
# fixture deleted from the self-test lowers <total> while the exit code stays
# 0 — coverage can shrink silently. Assert every fixture behaved AND that the
# fixture count has not dropped below what #268 left in place (16), the
# three #289 message/read-fallback fixtures, and the #271 0-term-verdict
# fixture. Raise FLOOR when fixtures are added; never lower it to make a red
# suite green.
FLOOR=20
counts="$(sed -n 's|.*self-test: \([0-9]\{1,\}\)/\([0-9]\{1,\}\) fixtures behaved.*|\1 \2|p' <<<"$selftest_out")"
behaved="${counts% *}"
total="${counts#* }"

check "self-test reports a fixture count" [ -n "$counts" ]
check "every fixture behaved ($behaved/$total)" [ "$behaved" = "$total" ]
check "fixture coverage has not shrunk (>= $FLOOR)" [ "${total:-0}" -ge "$FLOOR" ]

# ===========================================================================
# The tree sweep enumerates with `git ls-files`, so an untracked file is
# invisible to it — and the clean verdict said only "no private info found".
# In PR #345 that verdict was true and useless: the three offending files were
# untracked when it ran. Same shape as the denylist disclosure directly above
# it — "nothing matched" and "nothing was checked" must never print the same
# line (#347).
echo "sweep discloses its own scope (#347):"

# scope_repo DIR — a throwaway git repo holding a copy of the scanner, so the
# sweep runs against fixture content only. The scanner derives its repo root
# from its own location, hence bin/.
scope_repo() {
  local r="$1"
  mkdir -p "$r/bin"
  cp "$SCANNER" "$r/bin/check-private-info.sh"
  chmod +x "$r/bin/check-private-info.sh"
  printf 'clean content\n' >"$r/tracked.md"
  (cd "$r" && git init -q && git symbolic-ref HEAD refs/heads/main &&
    git add -A && git -c user.email=test@example.com -c user.name=test commit -q -m init)
}

D="$TMP/scope-untracked"
scope_repo "$D"
printf 'clean content\n' >"$D/untracked.md"
out="$(cd "$D" && bin/check-private-info.sh 2>&1)"
rc=$?

check "sweep reports how many tracked files it scanned" contains "files scanned" "$out"
check "sweep flags a partial scan when files are untracked" contains "PARTIAL" "$out"
check "sweep names the untracked file" contains "untracked.md" "$out"
check "sweep tells the caller to stage first" contains "git add" "$out"
check "a partial sweep still exits 0 when nothing was found" [ "$rc" -eq 0 ]

D="$TMP/scope-clean"
scope_repo "$D"
out="$(cd "$D" && bin/check-private-info.sh 2>&1)"

check "a fully tracked tree is not called PARTIAL" not_contains "PARTIAL" "$out"
check "a fully tracked tree still reports the clean verdict" \
  contains "no private info found" "$out"

D="$TMP/scope-ignored"
scope_repo "$D"
printf 'build/\n' >"$D/.gitignore"
(cd "$D" && git add -A && git -c user.email=test@example.com -c user.name=test commit -q -m ignore)
mkdir -p "$D/build"
printf 'clean content\n' >"$D/build/out.md"
out="$(cd "$D" && bin/check-private-info.sh 2>&1)"

check "an ignored file does not make the sweep PARTIAL" not_contains "PARTIAL" "$out"

# Pre-commit passes an explicit file list: the scope IS the argument list, so
# there is nothing to disclose and a banner would fire on every commit.
D="$TMP/scope-explicit"
scope_repo "$D"
printf 'clean content\n' >"$D/untracked.md"
out="$(cd "$D" && bin/check-private-info.sh tracked.md 2>&1)"

check "explicit-file mode does not report PARTIAL" not_contains "PARTIAL" "$out"

# A red run must be as honest about scope as a green one — otherwise fixing
# the findings turns a partial scan into an unqualified pass.
D="$TMP/scope-finding"
scope_repo "$D"
# Assembled at runtime, never spelled out: a literal home path in THIS file
# would itself be a finding, needing both a `private-ok` marker and a
# `.gitleaks.toml` path allowlist (see docs/privacy-boundaries.md). The fixture
# file on disk still carries the real pattern, which is what the sweep reads.
printf 'see /Users/%s/notes\n' someone >"$D/leak.md"
(cd "$D" && git add -A && git -c user.email=test@example.com -c user.name=test commit -q -m leak)
printf 'clean content\n' >"$D/untracked.md"
out="$(cd "$D" && bin/check-private-info.sh 2>&1)"
rc=$?

check "a run with findings still fails" [ "$rc" -ne 0 ]
check "a run with findings still discloses the skipped files" contains "PARTIAL" "$out"

# ===========================================================================
# The selection rule (docs/privacy-boundaries.md): a denylist term belongs on
# the list only if it should appear ZERO times in tracked content, forever.
# --audit-denylist proves each term against the tracked tree BEFORE the term
# starts flagging every commit (#271). Raw truth: no private-ok vouching.
echo "denylist audit (--audit-denylist):"

D="$TMP/audit-clean"
scope_repo "$D"
printf '# a comment, not a term\nzz-unique-term\nzz-other-term\n' >"$TMP/audit-dl.txt"
out="$(cd "$D" && BINDLE_DENYLIST="$TMP/audit-dl.txt" bin/check-private-info.sh --audit-denylist 2>&1)"
rc=$?
check "clean audit exits 0" [ "$rc" -eq 0 ]
check "clean audit reports the audited term count" contains "2 term" "$out"

D="$TMP/audit-hot"
scope_repo "$D"
printf 'this file mentions zz-flood-term\n' >"$D/hot.md"
printf 'ZZ-FLOOD-TERM in caps  private-ok\n' >"$D/vouched.md"
(cd "$D" && git add -A && git -c user.email=test@example.com -c user.name=test commit -q -m hot)
printf 'zz-flood-term\nzz-cold-term\n' >"$TMP/audit-hot-dl.txt"
out="$(cd "$D" && BINDLE_DENYLIST="$TMP/audit-hot-dl.txt" bin/check-private-info.sh --audit-denylist 2>&1)"
rc=$?
check "a term with tracked hits fails the audit" [ "$rc" -ne 0 ]
check "the offending term is named" contains "zz-flood-term" "$out"
check "the hit location is named" contains "hot.md" "$out"
check "case-insensitive, and private-ok vouching does not hide a hit" \
  contains "vouched.md" "$out"

# short terms over-match (Ada hits adapter) — warn, never fail on the warning
D="$TMP/audit-short"
scope_repo "$D"
printf 'zzq\n' >"$TMP/audit-short-dl.txt"
out="$(cd "$D" && BINDLE_DENYLIST="$TMP/audit-short-dl.txt" bin/check-private-info.sh --audit-denylist 2>&1)"
rc=$?
check "a short term draws an over-match warning" contains "over-match" "$out"
check "a warning alone does not fail the audit" [ "$rc" -eq 0 ]

# no denylist resolves: nothing to audit — say so, point at the scaffold
D="$TMP/audit-none"
scope_repo "$D"
mkdir -p "$TMP/audit-nohome"
out="$(cd "$D" && env -u BINDLE_DENYLIST -u CLAUDE_KIT_DENYLIST -u BINDLE_NOTES_DIR \
  -u CLAUDE_KIT_NOTES_DIR HOME="$TMP/audit-nohome" bin/check-private-info.sh --audit-denylist 2>&1)"
rc=$?
check "no denylist: audit exits 0" [ "$rc" -eq 0 ]
check "no denylist: says nothing to audit" contains "nothing to audit" "$out"
check "no denylist: points at the scaffold" contains "init-denylist" "$out"

# The audit's case-insensitivity is load-bearing: a case-sensitive mutant must
# MISS a caps-only hit the real audit catches — proving the -i flag is what
# catches it, not an accident of the fixture.
D="$TMP/audit-caps"
scope_repo "$D"
printf 'only ZZ-CAPS-TERM here\n' >"$D/caps.md"
(cd "$D" && git add -A && git -c user.email=test@example.com -c user.name=test commit -q -m caps)
printf 'zz-caps-term\n' >"$TMP/audit-caps-dl.txt"
out="$(cd "$D" && BINDLE_DENYLIST="$TMP/audit-caps-dl.txt" bin/check-private-info.sh --audit-denylist 2>&1)"
rc=$?
check "real audit catches a caps-only hit" [ "$rc" -ne 0 ]

D="$TMP/audit-caps-mutant"
scope_repo "$D"
printf 'only ZZ-CAPS-TERM here\n' >"$D/caps.md"
(cd "$D" && git add -A && git -c user.email=test@example.com -c user.name=test commit -q -m caps)
sed 's|git grep -Iin --fixed-strings|git grep -In --fixed-strings|' "$SCANNER" \
  >"$D/bin/check-private-info.sh"
chmod +x "$D/bin/check-private-info.sh"
if cmp -s "$SCANNER" "$D/bin/check-private-info.sh"; then
  printf '  ✗ audit case-mutant (mutation changed nothing — the sed expression is stale)\n'
  fail=$((fail + 1))
else
  out="$(cd "$D" && BINDLE_DENYLIST="$TMP/audit-caps-dl.txt" bin/check-private-info.sh --audit-denylist 2>&1)"
  rc=$?
  check "case-sensitive mutant misses the caps-only hit (the -i is load-bearing)" \
    [ "$rc" -eq 0 ]
fi

# ===========================================================================
echo "self-test is failable:"

# A gate that cannot go red is decoration. Each case copies the scanner into a
# throwaway tree, breaks ONE rule, and requires the self-test to notice —
# proving the assertions above are load-bearing, not just a clean exit code.
# The copy sits at <dir>/bin/ because the scanner derives its own repo root
# from its location. --self-test returns before any git call, so no fixture
# repo is needed.
mutate() { # mutate NAME SED_EXPR EXPECTED_FAILURE_TEXT
  local name="$1" expr="$2" expected="$3" d="$TMP/$1" out rc
  mkdir -p "$d/bin"
  sed "$expr" "$SCANNER" >"$d/bin/check-private-info.sh"
  chmod +x "$d/bin/check-private-info.sh"

  if cmp -s "$SCANNER" "$d/bin/check-private-info.sh"; then
    printf '  ✗ %s (mutation changed nothing — the sed expression is stale)\n' "$name"
    fail=$((fail + 1))
    return
  fi

  out="$("$d/bin/check-private-info.sh" --self-test 2>&1)"
  rc=$?
  check "$name — self-test goes red" [ "$rc" -ne 0 ]
  check "$name — names the rule that broke" contains "$expected" "$out"
}

# The relay-email pattern stops matching: relay.md must no longer be flagged.
mutate "neutered apple-private-relay pattern" \
  's|privaterelay\\\.appleid|privaterelay-NEVERMATCH\\.appleid|' \
  "relay.md NOT flagged"

# Denylist matching loses case-insensitivity: 'Dana' stops catching 'dana'.
# shellcheck disable=SC2016 # "$term" is literal sed replacement text, not expansion
mutate "case-sensitive denylist matching" \
  's|grep -InFi "\$term"|grep -InF "$term"|' \
  "casefold.md NOT flagged"

# The clean verdict stops disclosing that NO denylist was loaded — the two
# facts ("nothing matched" vs "nothing was checked") collapse into one line.
mutate "clean verdict stops disclosing an absent denylist" \
  's|pattern rules only — NO personal denylist loaded|no personal denylist loaded|' \
  "does not disclose that NO denylist was loaded"

# The missing-denylist advice reverts to naming the RESOLVED read path, which
# with no denylist anywhere is the deprecated ~/.claude-kit fallback (#289).
# shellcheck disable=SC2016 # sed pattern/replacement text, not expansions
mutate "missing-denylist advice names the deprecated read fallback" \
  's|no personal denylist at \$DENYLIST_SUGGESTED|no personal denylist at $DENYLIST|' \
  "does not name the notes home"

# ===========================================================================
echo
if [ "$fail" -eq 0 ]; then
  printf '  ✓ all %d checks pass\n' "$pass"
  exit 0
fi
printf '  %d of %d checks FAILED\n' "$fail" "$((pass + fail))"
exit 1
