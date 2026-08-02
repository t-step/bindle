# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read and follow AGENTS.md in full — it is the authoritative, portable instruction set (shared with Codex), covering scope and safety rules, the three-subagent ceiling, secrets handling, commit conventions, the planning flow, skills/MCP policy, and the development/runtime isolation rules for Bindle itself. This file only adds what AGENTS.md cannot express portably.

## Repository state

Bindle is pre-implementation. This repository currently defines the workshop, conventions, and scope for a not-yet-built tool — there is no package manifest, build system, linter, or test suite yet. Do not invent one; do not scaffold a framework, memory platform, graph system, or daemon without an approved plan (AGENTS.md, "Current phase").

`scripts/doctor.sh` is the one script present: a read-only toolchain/file-presence check. It is functional (`bash scripts/doctor.sh`) and reports missing tools or repository files with a nonzero exit code.

Commit messages are validated by Cocogitto against `cog.toml`. A local `commit-msg` git hook (installed via `cog install-hook`, not tracked by git) runs `cog verify` on every commit — do not bypass it (AGENTS.md, "Do not bypass repository hooks"). If it's missing in a fresh checkout, reinstall with `cog install-hook commit-msg`.

## Orientation

Reading multiple files is required to get the full picture; short version:

- `AGENTS.md` — working instructions: scope/safety, subagent limits, secrets, commits, planning flow, skills/MCP policy, Obsidian projection rules, and Bindle's own development/runtime isolation requirements (never touch live `~/.local/share/bindle/` state or the real Bindle vault from dev/tests; use `BINDLE_HOME="$PWD/.bindle-dev" uv run bindle ...`).
- `PLAN.md` — current outcome and near-term milestones.
- `docs/SCOPE.md` — what Bindle owns / may later own / explicitly does not own, the session model, the candidate canonical-state layout (`~/.bindle/{sessions,memories,index.sqlite,config.yaml}`), and the M0–M4 milestone sequence.
- `docs/DECISIONS.md` — numbered decision log (D001–D013); check it before proposing anything that would revisit a settled decision (e.g. no generic agent loop, no broad ontology, graphs are derived not canonical).
- `docs/TOOLCHAIN.md` — the full toolchain, skill selection, and MCP profile rationale, with tool precedence order.
- `config/skills.yaml`, `config/mcp-profiles.yaml` — machine-readable mirrors of the toolchain doc (skill bundles and MCP server profiles by task category).

Core intent, if you only read one line: Bindle is a continuity layer (capture → promote → project → resume) across Claude Code, Codex, and repositories — not a replacement for any of them. Inherit first, extend second, replace deliberately, invent last.

Claude-specific configuration belongs under `.claude/` only when it cannot be expressed portably. Repository-local instructions and tooling take precedence over global skills and defaults. Do not introduce Claude-specific project structure when an open Agent Skills or repository-native alternative is sufficient.

<!-- >>> projectmem bridge >>> -->
## projectmem (MANDATORY)

This project uses projectmem for persistent memory + workflow rules.

SESSION START — call these three MCP tools, in this order, BEFORE
answering ANY question about this project:

  1. `get_instructions()` — loads the project's mandatory workflow
     rules. Without this you will not know how to log work
     correctly, when to use `add_note` vs `add_decision`, or how
     the event log is structured.
  2. `get_summary()` — loads project content. Do NOT answer from
     conversation history or by re-reading package.json / README /
     source files.
  3. `get_project_map()` — loads structural layout when relevant.

BEFORE modifying ANY file:
  - Call `precheck_file(path)` — check failure history first.

DURING work — use MCP write tools, NEVER edit `.projectmem/`
files directly via filesystem write:
  - On a bug discovery → `log_issue(summary, location)`.
  - After each fix attempt → `record_attempt(summary, outcome)`.
  - After confirmation → `record_fix(summary)`.
  - On a design choice → `add_decision(summary)`.
  - On a gotcha / setup detail → `add_note(summary)`.

Editing `.projectmem/summary.md` or `.projectmem/PROJECT_MAP.md`
directly bypasses event logging and breaks audit replay. The
summary file regenerates from `events.jsonl` automatically — write
via the MCP tools and the summary will follow.

Do not re-scan source files when MCP tools can give you the same
answer in ~500 tokens instead of ~5000. This is not optional.
<!-- <<< projectmem bridge <<< -->
