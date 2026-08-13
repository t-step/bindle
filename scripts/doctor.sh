#!/usr/bin/env bash
set -euo pipefail

status=0

check_command() {
  local command_name="$1"
  local label="${2:-$1}"

  if command -v "$command_name" >/dev/null 2>&1; then
    printf '✓ %s: %s\n' "$label" "$(command -v "$command_name")"
  else
    printf '✗ %s: not found\n' "$label"
    status=1
  fi
}

check_file() {
  local path="$1"
  local label="$2"

  if [[ -e "$path" ]]; then
    printf '✓ %s: %s\n' "$label" "$path"
  else
    printf '✗ %s: missing (%s)\n' "$label" "$path"
    status=1
  fi
}

printf 'Bindle doctor\n'
printf '%s\n\n' '============='

printf 'Core tools\n'
printf '%s\n' '----------'
check_command git
check_command rg "ripgrep"
check_command fd
check_command fzf
check_command jq
check_command sqlite3
check_command uv "uv"
check_command claude "Claude Code"
check_command codex "Codex"
check_command cog "Cocogitto"
check_command hf "Hugging Face CLI"

printf '\nGlobal instructions\n'
printf '%s\n' '-------------------'
check_file "$HOME/.claude/CLAUDE.md" "Claude global instructions"
check_file "$HOME/.codex/AGENTS.md" "Codex global instructions"

printf '\nRepository files\n'
printf '%s\n' '-----------------'
check_file "AGENTS.md" "Shared agent instructions"
check_file "CLAUDE.md" "Claude bridge"
check_file "PLAN.md" "Current plan"
check_file "cog.toml" "Cocogitto configuration"
check_file "docs/TOOLCHAIN.md" "Toolchain documentation"
check_file "docs/SCOPE.md" "Scope documentation"
check_file "docs/DECISIONS.md" "Decision log"
check_file ".mcp.json" "Claude Code MCP defaults"
check_file ".codex/config.toml" "Codex MCP defaults"

check_decision_references() {
  local decisions_file="docs/DECISIONS.md"
  local defined_ids
  defined_ids="$(grep -oE '^D[0-9]{3}:' "$decisions_file" | tr -d ':' || true)"

  local dangling=0
  local file token
  while IFS= read -r file; do
    [[ "$file" == "$decisions_file" ]] && continue
    while IFS= read -r token; do
      [[ -z "$token" ]] && continue
      if ! grep -qx "$token" <<<"$defined_ids"; then
        printf '    %s cites unknown decision %s\n' "$file" "$token"
        dangling=1
      fi
    done < <(grep -oE 'D[0-9]{3}' "$file" | sort -u || true)
  done < <(git ls-files '*.md')

  if [[ "$dangling" -eq 0 ]]; then
    printf '✓ %s\n' "Decision references: all D-numbers cited in tracked docs exist in $decisions_file"
  else
    printf '✗ %s\n' "Decision references: dangling citations found (see above)"
    status=1
  fi
}

printf '\nDocumentation consistency\n'
printf '%s\n' '--------------------------'
check_decision_references

printf '\nNotes\n'
printf '%s\n' '-----'
printf '%s\n' \
  '- This command is read-only.' \
  '- It reports desired-state gaps but does not modify client configuration.' \
  '- MCP and skill detection will be added after installation paths are finalized.'

exit "$status"
