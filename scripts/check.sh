#!/usr/bin/env bash
#
# check.sh — Bindle's canonical repository verification gate.
#
# Run locally before opening or updating a PR:
#   bash scripts/check.sh
#
# Runs unchanged in GitHub Actions (.github/workflows/ci.yml); the only local/CI
# difference is the private personal-info denylist (docs/PRIVACY.md), which
# every check tolerates absent, so nothing special-cases the environment.
#
# Repository invariant gate, not workstation readiness (that is
# scripts/doctor.sh, deliberately not called).
#
set -uo pipefail # not -e: run every check, then fail once at the end

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

fail=0
section() { printf '\n== %s ==\n' "$1"; }

# bash <4.4 (macOS /usr/bin/env bash can be 3.2) treats "${arr[@]}" on an empty
# array as unbound under set -u; guard each expansion (same as
# bin/check-private-info.sh).
SH_FILES=()
# Excludes .specify/: vendored Spec Kit scripts, never hand-edited (D035).
while IFS= read -r f; do
  SH_FILES+=("$f")
done < <(git ls-files '*.sh' ':!:.specify/**')

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

# Required, not opportunistic: a missing shellcheck fails the gate.
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

# Personal-disclosure guard (docs/PRIVACY.md).
section "bin/check-private-info.sh --self-test"
bin/check-private-info.sh --self-test || fail=1

section "bin/test-check-private-info.sh"
bin/test-check-private-info.sh || fail=1

section "bin/check-private-info.sh (full-tree scan)"
bin/check-private-info.sh || fail=1

section "bin/check-private-info.sh --audit-denylist"
bin/check-private-info.sh --audit-denylist || fail=1

# Guardrail layer (D031/D032).
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

section "bin/test-history-hygiene.sh"
bin/test-history-hygiene.sh || fail=1

section "bin/test-packaged-install.sh"
bin/test-packaged-install.sh || fail=1

# Match the "## D001:" heading shape in docs/DECISIONS.md; a bare '^D[0-9]{3}:'
# pattern never matches it and makes every citation look dangling.
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

section "python3 -m unittest (bindle CLI)"
if ! command -v python3 >/dev/null 2>&1; then
  printf '  ✗ python3 not found on PATH — install it and re-run\n'
  fail=1
elif python3 -m unittest discover -s tests -t . -v; then
  printf '  ✓ bindle CLI unit tests passed\n'
else
  fail=1
fi

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
