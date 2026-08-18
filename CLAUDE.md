# CLAUDE.md

@AGENTS.md

AGENTS.md is the authoritative, portable instruction set for this repository.
This file contains only Claude Code-specific guidance and must not restate
portable repository policy.

Claude Code auto-memory is soft recall, not project authority. Durable
decisions, summaries, and handoffs must be routed according to
docs/DATA-OWNERSHIP.md.

## Claude-specific configuration

Claude-specific repository configuration belongs under `.claude/` only when
it cannot be expressed portably. Prefer repository-native or open Agent Skills
mechanisms when they are sufficient.

## projectmem

Follow the projectmem policy in AGENTS.md.

When the projectmem MCP server is connected, prefer its MCP tools over the
`pjm` CLI. The CLI is the fallback. projectmem remains optional and
machine-local.
