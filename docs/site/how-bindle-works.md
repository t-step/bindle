# How Bindle Works

This page explains what Bindle owns, what it hands off, and who decides
what "done" means — without requiring you to read
[docs/DECISIONS.md](../DECISIONS.md).

## The flow, in order

1. **A specification tool defines the work.** In this repository that
   tool is Spec Kit: a feature's `spec.md`/`plan.md` decomposition ends in
   a `tasks.md` with one dependency-tracked, independently verifiable
   `T###` line per unit of work. Bindle does not define work — it reads a
   task decomposition someone else already produced.
2. **Bindle durably records that work as coordination state, and exposes
   which items are currently schedulable.** `bindle work load-speckit`
   reads one Spec Kit feature's `tasks.md` into Bindle's own SQLite work
   ledger (`.bindle-work/ledger.sqlite3`) — one ledger row per `T###`
   line, tracking status, blocking dependencies, claims, and evidence
   pointers. `bindle work status` and `bindle work forecast` report which
   items are dispatchable now, which are blocked, and the dependency
   frontier — computed entirely from this ledger, with no external
   coordinator involved. A separate, read-only export
   (`.bindle-work/symphony-projection.sqlite3`) republishes only the
   currently-dispatchable subset in a form an external coordinator can
   read.
3. **An execution harness performs the work.** Symphony — an
   independently-run, independently-owned external coordinator — can
   dispatch a coding agent (Claude Code or Codex) against one schedulable
   item at a time, reading Bindle's published projection and claiming
   work through Bindle's own narrow write surface
   (`bindle work claim`/`release`/`done`). Bindle does not perform this
   execution itself, does not run or supervise the coding agent, and does
   not install, configure, start, or stop Symphony.
4. **Git and GitHub own the resulting evidence and history.** A commit, a
   branch, a pull request — these are Git/GitHub-owned records. Bindle
   never copies or re-stores them.
5. **Bindle records pointers to that evidence, not the evidence itself.**
   When a task carries a branch, commit, or pull-request reference,
   Bindle stores a lightweight evidence pointer (kind, value, timestamp,
   optional note) against that ledger row — never a copy of the commit,
   diff, or PR content.
6. **A human decides whether a milestone is accepted.** A milestone is a
   ledger work item that groups one or more tasks for review. Whether all
   of a milestone's children are resolved and carry a qualifying evidence
   pointer — "review-readiness" — is a mechanical, computed fact.
   Whether the resulting outcome is actually *accepted* is not: it is an
   explicit, human-invoked decision (`bindle milestone accept` /
   `decline`), never inferred or automated from readiness alone.

## The same flow, as a diagram

The indigo **Bindle-owned** boxes are the only boxes Bindle itself durably
owns. Everything else belongs to another owner, and the final decision is
explicitly human — never a computed output of readiness:

![Diagram: Spec Kit's task decomposition flows into Bindle's coordination ledger (Bindle-owned), which publishes a dispatchable subset to Symphony and an execution harness (Claude Code or Codex); the harness's work becomes Git/GitHub evidence; an evidence pointer is recorded back into the coordination ledger (Bindle-owned); ledger state computes milestone review-readiness; a human makes the final accept/decline decision, never automated from readiness alone.](img/how-bindle-works-diagram.svg)

Notice what the diagram does *not* show: no box labeled "Bindle" ever
touches the Symphony/execution-harness boxes, the Git/GitHub box, or the
final human-decision block — Bindle's own boxes stop at recording state and
pointers.

## What Bindle does not do

- **Bindle does not perform execution.** It never runs a coding agent,
  never runs a build or a test, and never edits your source code.
  Execution belongs to a harness (Symphony dispatching Claude Code or
  Codex), not to Bindle.
- **Bindle does not own Git/GitHub history.** Commits, branches, pull
  requests, and their history remain entirely Git/GitHub's own durable
  record. Bindle only ever holds a pointer to one.
- **Bindle does not own project or personal knowledge.** Notes,
  transcripts, and project memory belong to the tools that own that
  domain (an editor's memory system, an execution harness's own session
  history, a knowledge vault). Bindle is never the sole copy of any of
  that.
- **Bindle does not automate milestone acceptance from readiness alone.**
  Readiness is mechanical (a computed query over ledger state);
  acceptance is semantic (a human judgment call). The ledger will tell
  you a milestone's children are all resolved and evidenced — it will
  never tell you the result should be accepted, and it never transitions
  a milestone to accepted by itself.

## Is Bindle "stateless"?

Not entirely, and the qualification matters. Bindle is stateless with
respect to **user history, knowledge, and transcripts** — it keeps no
database of your notes, no copy of your conversations with a coding
assistant, no store of "what happened" beyond what it needs to coordinate
work. That's the sense in which "stateless toolchain bridge" is true.

But Bindle does durably own one bounded category of state: the
**coordination ledger** — work-item status, blocking relationships,
claims, and evidence pointers, held in
`.bindle-work/ledger.sqlite3`. This is real, tested, repository-local
state that survives across sessions and is not derived from, or
rebuildable from, any other provider. So the accurate answer to "is
Bindle stateless?" is not a plain yes or no: Bindle owns no user
history/knowledge/transcripts, but it does durably own bounded,
repository-local coordination state.

## Where Symphony fits

Symphony is optional, independently-run, and independently-owned — it is
referenced, never vendored. Nothing on this page's Getting Started path
requires installing, configuring, or starting it: the coordination ledger,
`bindle work status`, and `bindle work forecast` all work against a local
repository with no external coordinator running at all. Symphony becomes
relevant only when you want an external process to actually dispatch a
coding agent against the tasks Bindle has marked dispatchable.

## Summary

| Layer | Owner |
| --- | --- |
| Task decomposition | A specification tool (e.g. Spec Kit) |
| Coordination state (status, blocking, claims, evidence pointers) | Bindle |
| Dispatch and execution | An execution harness (e.g. Symphony, dispatching Claude Code or Codex) |
| Commits, branches, pull requests, history | Git / GitHub |
| Milestone acceptance | A human |
