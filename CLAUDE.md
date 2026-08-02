# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

The import above loads AGENTS.md deterministically (Claude Code does not read AGENTS.md natively; the `@` import is the documented bridge). It is the authoritative, portable instruction set (shared with Codex), covering scope and safety rules, the three-subagent ceiling, secrets handling, commit conventions, the planning flow, skills/MCP policy, and the development/runtime isolation rules for Bindle itself. This file only adds what AGENTS.md cannot express portably.

That division is deliberate (D017): AGENTS.md holds the single authoritative copy of every policy; this file is a thin Claude-specific bridge and must never restate a policy AGENTS.md already carries. Claude Code's per-project auto-memory is soft recall, never project authority — durable decisions, summaries, and handoffs go to the shared locations in docs/DATA-OWNERSHIP.md, not to a Claude-private store that Codex cannot see.

## Repository state

Bindle is pre-implementation. This repository currently defines the workshop, conventions, and scope for a not-yet-built tool — there is no package manifest, build system, linter, or test suite yet. Do not invent one; do not scaffold a framework, memory platform, graph system, or daemon without an approved plan (AGENTS.md, "Current phase").

`scripts/doctor.sh` is the one script present: a read-only toolchain/file-presence check. It is functional (`bash scripts/doctor.sh`) and reports missing tools or repository files with a nonzero exit code.

Commit messages are validated by Cocogitto against `cog.toml`. A local `commit-msg` git hook (installed via `cog install-hook`, not tracked by git) runs `cog verify` on every commit — do not bypass it (AGENTS.md, "Do not bypass repository hooks"). If it's missing in a fresh checkout, reinstall with `cog install-hook commit-msg`.

## Orientation

Reading multiple files is required to get the full picture; short version:

- `AGENTS.md` — working instructions: scope/safety, subagent limits, secrets, commits, planning flow, skills/MCP policy, Obsidian projection rules, and Bindle's own development/runtime isolation requirements (never touch live `~/.local/share/bindle/` state or the real Bindle vault from dev/tests; use `BINDLE_HOME="$PWD/.bindle-dev" uv run bindle ...`).
- `PLAN.md` — current outcome and near-term milestones.
- `docs/SCOPE.md` — what Bindle owns / may later own / explicitly does not own, the session model, the candidate canonical-state layout (`~/.bindle/{sessions,memories,index.sqlite,config.yaml}`), and the M0–M4 milestone sequence.
- `docs/DECISIONS.md` — numbered decision log (D001–D018); check it before proposing anything that would revisit a settled decision (e.g. no generic agent loop, no broad ontology, graphs are derived not canonical).
- `docs/TOOLCHAIN.md` — the full toolchain, skill selection, and MCP profile rationale, with tool precedence order.
- `docs/PHILOSOPHY.md` — what Bindle is (a stateless toolchain bridge), what it refuses to become, the replaceability/durability/preservation rules, and the feature admission test.
- `docs/DATA-OWNERSHIP.md` — the authority model for Claude Code and Codex, the ownership and routing tables, durable versus derived.
- `docs/WORKTREES.md` — the identity model (common dir / worktree path / SHA / branch), provider behavior across linked worktrees, evidence-block fields, operating rules.
- `docs/PRIVACY.md` — the personal-disclosure threat model, the archived guard's status, and content rules for this repository.
- `config/skills.yaml`, `config/mcp-profiles.yaml` — machine-readable mirrors of the toolchain doc (skill bundles and MCP server profiles by task category).

Core intent, if you only read one line: Bindle is a continuity layer (capture → promote → project → resume) across Claude Code, Codex, and repositories — not a replacement for any of them. Inherit first, extend second, replace deliberately, invent last.

Claude-specific configuration belongs under `.claude/` only when it cannot be expressed portably. Repository-local instructions and tooling take precedence over global skills and defaults. Do not introduce Claude-specific project structure when an open Agent Skills or repository-native alternative is sufficient.

## projectmem (Claude-specific note)

The projectmem mandate lives in AGENTS.md ("Project memory (projectmem)"), loaded by the import above. In Claude Code the projectmem MCP server is registered (project scope) and injects its own detailed tool instructions at session start — use the MCP tools, not the `pjm` CLI fallback, when the server is connected.
