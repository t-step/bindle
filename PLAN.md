# PLAN

Outcome

Define and validate the smallest useful Bindle vertical slice: a stateless toolchain bridge that moves evidence and context across Claude Code, Codex, and repositories without becoming a memory or session store itself.

Current

M0 (workshop) is established: toolchain manifest, doctor checks, the decision log, and toolchain policy are in place. The evidence-block schema is defined (docs/WORKTREES.md), but deterministic emission from git state has not been implemented — M1 is schema-complete, not built. projectmem (D022) is adopted as local operational memory. Obsidian Mind (D023) was briefly adopted the same way but is back on active trial (D025) — not ready for main. `config/skills.yaml` and `config/mcp-profiles.yaml` were added and then removed after neither tool ever consumed them as data; docs/TOOLCHAIN.md is now the sole policy source, backed by a real, natively-consumed `.mcp.json`/`.codex/config.toml` for the one unconditionally-default MCP server (Context7). Work is now preparing `main` as a promoted baseline, with CI/repository wiring for that promotion under consideration.

Next

1. Promote `development` to `main` as the accepted baseline.
2. Decide and implement whatever CI/repository wiring that promotion needs (scope not yet fixed).
3. Implement the first evidence-block emission path — deterministic emission from git state, embedding into a provider-owned record, list/show of emitted blocks — as the first concrete piece of M1.
4. Begin the first vertical slice implementation once M1 emission lands.

Blocked/Deferred

* Graphiti adoption (M4) waits on real session records and retrieval failures.
* Automatic Obsidian publication waits on preview quality.
* Full release automation for Bindle itself (versioning, changelog generation, package publication) still waits on an installable or externally consumed artifact — distinct from the narrower CI/repository wiring under consideration for the `main` promotion above.

See docs/DECISIONS.md for the decision history and plans/active/ for in-flight work packets.
