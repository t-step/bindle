#!/usr/bin/env bash
#
# check.sh — Bindle's canonical repository verification gate.
#
# Run locally before opening or updating a PR:
#   bash scripts/check.sh
#
# Runs unchanged in GitHub Actions (.github/workflows/ci.yml). Local and CI
# environments differ only in one respect: the private personal-info
# denylist (docs/PRIVACY.md) is present locally and absent in CI. Every
# check below already tolerates that difference on its own — nothing here
# special-cases the environment.
#
# This is a repository invariant gate, not workstation readiness — that
# boundary is scripts/doctor.sh, which this script deliberately does not
# call.
#
set -uo pipefail # not -e: run every check, then fail once at the end

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

fail=0
section() { printf '\n== %s ==\n' "$1"; }

# bash <4.4 (macOS system /usr/bin/env bash can still resolve to 3.2) treats
# "${arr[@]}" on a zero-element array as unbound under set -u; guard every
# expansion below rather than drop set -u (same convention as
# bin/check-private-info.sh).
SH_FILES=()
# Excludes .specify/ — Spec Kit's own vendored scripts (D035: committed
# verbatim for team reproducibility, never hand-edited by Bindle). Linting
# upstream's own code and either fixing it (creating local drift a future
# `specify integration upgrade` would clobber) or leaving warnings unfixed
# (permanently failing this gate) are both wrong; this repository has no
# standing to lint code it doesn't own and never modifies.
while IFS= read -r f; do
  SH_FILES+=("$f")
done < <(git ls-files '*.sh' ':!:.specify/**')

# --- 1. bash syntax validation ----------------------------------------------
section "bash -n (syntax)"
if [ "${#SH_FILES[@]}" -gt 0 ]; then
  for f in "${SH_FILES[@]}"; do
    if bash -n "$f"; then
      printf '  ✓ %s\n' "$f"
    else
      printf '  ✗ %s\n' "$f"
      fail=1
    fi
  done
else
  printf '  - no tracked *.sh files found\n'
fi

# --- 2. ShellCheck -----------------------------------------------------------
# Required, not opportunistic: a missing shellcheck fails the gate rather
# than silently skipping it. No auto-install here — install it yourself
# (e.g. `brew install shellcheck` or your distro's package manager).
section "shellcheck"
if ! command -v shellcheck >/dev/null 2>&1; then
  printf '  ✗ shellcheck not found on PATH — install it and re-run\n'
  fail=1
elif [ "${#SH_FILES[@]}" -gt 0 ]; then
  if shellcheck "${SH_FILES[@]}"; then
    printf '  ✓ shellcheck passed for %d tracked script(s)\n' "${#SH_FILES[@]}"
  else
    fail=1
  fi
else
  printf '  - no tracked *.sh files found\n'
fi

# --- 3-6. personal-disclosure guard (docs/PRIVACY.md) -----------------------
section "bin/check-private-info.sh --self-test"
bin/check-private-info.sh --self-test || fail=1

section "bin/test-check-private-info.sh"
bin/test-check-private-info.sh || fail=1

section "bin/check-private-info.sh (full-tree scan)"
bin/check-private-info.sh || fail=1

section "bin/check-private-info.sh --audit-denylist"
bin/check-private-info.sh --audit-denylist || fail=1

# --- guardrail layer (docs/DECISIONS.md D031/D032) ---------------------------
section "bin/test-git-hook-dispatch.sh"
bin/test-git-hook-dispatch.sh || fail=1

section "bin/test-claude-protected-main-guard.sh"
bin/test-claude-protected-main-guard.sh || fail=1

section "bin/test-install-guardrails.sh"
bin/test-install-guardrails.sh || fail=1

section "bin/test-guardrail-ownership.sh"
bin/test-guardrail-ownership.sh || fail=1

section "bin/test-guardrail-status.sh"
bin/test-guardrail-status.sh || fail=1

section "bin/test-packaged-install.sh"
bin/test-packaged-install.sh || fail=1

# --- 7. decision-reference consistency ---------------------------------------
# docs/DECISIONS.md defines decisions as "## D001: <title>" headings. Collect
# the defined IDs, then fail if any tracked Markdown file cites a D### token
# that isn't defined there. A prior development-only version of this check
# (scripts/doctor.sh, since removed) matched '^D[0-9]{3}:' against decision
# lines and never matched the real "## D001:" heading shape — every citation
# looked dangling. Match the heading shape itself instead.
section "decision-reference consistency"
check_decision_references() {
  local decisions_file="docs/DECISIONS.md"
  local defined
  defined="$(grep -oE '^## D[0-9]{3}:' "$decisions_file" | grep -oE 'D[0-9]{3}')"

  local dangling=0 file cited token
  while IFS= read -r file; do
    cited="$(grep -oE 'D[0-9]{3}' "$file" | sort -u)"
    [ -n "$cited" ] || continue
    while IFS= read -r token; do
      if ! grep -qx "$token" <<<"$defined"; then
        printf '  ✗ %s cites unknown decision %s\n' "$file" "$token"
        dangling=1
      fi
    done <<<"$cited"
  done < <(git ls-files '*.md')

  if [ "$dangling" -eq 0 ]; then
    printf '  ✓ all D-number citations in tracked Markdown resolve to %s\n' "$decisions_file"
    return 0
  fi
  return 1
}
check_decision_references || fail=1

# --- 8. bindle CLI unit tests -------------------------------------------------
section "python3 -m unittest (bindle CLI)"
if ! command -v python3 >/dev/null 2>&1; then
  printf '  ✗ python3 not found on PATH — install it and re-run\n'
  fail=1
elif python3 -m unittest discover -s tests -t . -v; then
  printf '  ✓ bindle CLI unit tests passed\n'
else
  fail=1
fi

# --- 9. documentation site build (MkDocs, strict) -----------------------------
section "mkdocs build --strict"
if uv run mkdocs build --strict; then
  printf '  ✓ documentation site builds cleanly\n'
else
  fail=1
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "scripts/check.sh: all checks passed"
else
  echo "scripts/check.sh: one or more checks FAILED (see above)"
fi
exit "$fail"
