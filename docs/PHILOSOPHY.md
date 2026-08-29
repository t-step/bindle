# PHILOSOPHY

## What Bindle is

Bindle is a stateless toolchain bridge.

It helps move useful context and evidence between tools that already own their respective domains. Git owns implementation history. GitHub owns collaboration. Claude Code and Codex own live sessions and their transcripts. A repository-local memory tool owns working reasoning. A personal knowledge vault owns durable lessons. Language servers and code graphs own program structure.

None of these tools are wrong. They stop at different boundaries. Bindle exists because there are seams between them, and useful context gets dropped at the crossings.

Bindle is not the destination. It is connective tissue that helps work move to where it is already going. If a better provider appears for any responsibility, the provider gets replaced; Bindle does not get rewritten.

## What Bindle may do

* invoke providers through supported interfaces
* collect deterministic facts: git state, tool presence, configuration
* normalize or project those facts
* record evidence pointers — branch, commit, pull request, or other locator — that other systems' records may embed
* emit pointers that owning systems store and resolve
* diagnose whether the local toolchain is wired correctly
* provide lightweight adapters, hooks, templates, and commands

## What Bindle must not do

* become the canonical owner of notes, transcripts, project memories, Git history, embeddings, narrative session records, or user knowledge
* parse another tool's private or internal datastore
* establish a hidden Bindle database as the only copy of user history
* silently promote temporary reasoning into durable truth
* preserve every thought
* duplicate a provider merely because its integration is imperfect

## The replaceability rule (D014)

No Bindle code may parse another tool's private store. Bindle may call supported interfaces, record evidence pointers that other systems embed, and hold pointers that the owning systems resolve.

Bindle's durable outputs are embeddable artifacts, not destinations. A pointer exists so the receiving system can resolve it — never because Bindle wants a graph.

If a provider is replaced or removed, Bindle may lose pointers. It must never break.

## The durability rule (D015)

Every durable artifact lives with the system that naturally owns it.

Bindle-owned runtime state is limited to configuration, disposable cache, and explicit export. Nothing under Bindle's control may be the only copy of user history.

## The preservation rule (D016)

Not every thought deserves to be preserved.

Temporary exploration, conversational branches, speculative ideas, and low-value intermediate reasoning normally remain in transcripts or scratch space and are allowed to disappear.

Durable capture requires a reason, such as:

* an accepted project decision
* a significant attempt, failure, or fix
* a reusable cross-project lesson
* a meaningful work record
* a stable handoff boundary
* a reproducible benchmark or verification result

## Negative space

The measure of Bindle is not how many responsibilities it acquires, but how many responsibilities it can confidently decline because another tool already owns them.

## Feature admission test

Three questions come first:

* Ownership — who naturally owns this?
* Replaceability — can that owner be replaced?
* Preservation — does this deserve to survive?

A weak answer to any one of them ends the proposal. The nine criteria below are the full test for proposals that survive the screen.

A proposed feature normally belongs in Bindle only if it:

1. bridges independently useful tools or workflow stages
2. operates through supported public interfaces
3. emits derived, portable, or disposable output
4. does not become the sole owner of user history
5. remains conceptually useful if a provider is replaced
6. solves repeated observed friction rather than hypothetical scope
7. cannot be handled adequately by a routing rule, template, or small script
8. respects worktree and branch identity
9. does not preserve information merely because preservation is possible

Rejection examples:

* "List sessions by reading Claude Code's transcript JSONL and Codex's SQLite directly." Fails 2 and 5. Those are private stores. Hold pointers and let each harness resolve its own.
* "A Bindle notes database for decisions and lessons." Fails 1 and 4. The repository decision log and the knowledge vault already own those categories.
* "Embed and index all transcripts for semantic search." Fails 3, 4, and 9. Retrieval belongs to a provider, and transcripts are allowed to disappear.
* "Auto-summarize every session into a permanent record." Fails 9 and the preservation rule. Capture requires a reason.
* "A generic agent loop so both harnesses behave identically." Fails 1 and 7, and contradicts D001.
* "Re-implement repository memory because projectmem is branch-blind." Fails 6 and the last must-not: an imperfect integration does not justify duplication. Document the limitation and route around it.
