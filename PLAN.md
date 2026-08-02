# PLAN

Outcome

Define and validate the smallest useful Bindle vertical slice.

Current

Establish the shared workshop and durable-session model before implementing memory or graph infrastructure.

Next

1. Create the repository skeleton and manifests.
2. Implement a read-only doctor command.
3. Define the initial session-record schema.
4. Trial repository-local memory tooling in Valence.
5. Establish the dedicated Bindle Obsidian vault.

Blocked

* Graphiti adoption waits on real session records and retrieval failures.
* Automatic Obsidian publication waits on preview quality.
* Release automation waits on an installable product.

Later

* Session start, close, list, and show
* Resume-context assembly
* Promotion and supersession
* Obsidian projection
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
