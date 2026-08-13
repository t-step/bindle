# PLAN

Outcome

Define and validate the smallest useful Bindle vertical slice.

Current

Establish the shared workshop and durable-session model before implementing memory or graph infrastructure.

Next

1. ~~Create the repository skeleton and manifests.~~ Done — `config/skills.yaml`/`config/mcp-profiles.yaml` were added, then superseded: neither tool ever consumed them as data, so they were deleted in favor of `docs/TOOLCHAIN.md` as the sole policy source plus a real, natively-consumed `.mcp.json`/`.codex/config.toml` for the one unconditionally-default MCP server (Context7). `scripts/doctor.sh` reports all repository-file checks passing.
2. ~~Implement a read-only doctor command.~~ Done — `scripts/doctor.sh`.
3. Define the evidence-block schema (fields and worktree semantics in docs/WORKTREES.md).
4. Trial repository-local memory tooling in Valence.
5. Trial obsidian-mind as the dedicated vault (deploy the template with the om MCP server; commit `.om-project` markers in participating repos).

Blocked

* Graphiti adoption waits on real session records and retrieval failures.
* Automatic Obsidian publication waits on preview quality.
* Release automation waits on an installable product.

Later

* Evidence-block emission, list, and show
* Resume-context assembly from provider-owned records
* Promotion and supersession routing
* Obsidian projection emission
* Temporal-index comparison
* Toolchain bootstrap and drift repair (e.g., installing this repo's cog.toml git-hook pattern into other project repositories, so conventional-commit enforcement is consistent across repos without re-deriving it each time)

Recent decisions

See docs/DECISIONS.md.

plans/active/README.md

Active plans

This directory contains executable work packets for current outcomes.

Each plan should include:

* outcome
* why now
* scope
* evidence
* work
* verification
* decisions
* open questions
* showcase evidence

Completed plans move to ../archive/.

plans/archive/.gitkeep
