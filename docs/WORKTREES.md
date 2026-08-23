# WORKTREES

How identity, context, hooks, and providers behave when a repository has more than one checkout. Bindle's own development flow requires worktrees (AGENTS.md, "Development isolation"), so this is an operating condition, not an edge case.

## Identity model

* Repository identity: the Git common directory (`git rev-parse --git-common-dir`), plus stable remote metadata when available (`git remote get-url origin`). All worktrees of one repository share one repository identity.
* Execution identity: the absolute worktree path (`git rev-parse --show-toplevel`).
* Code-state identity: full commit SHA plus a dirty summary.
* Branch: mutable, descriptive context. Never primary identity — branches get renamed, rebased, squashed, and deleted.

The previous Bindle prototype keyed project identity on the worktree directory basename and produced eleven orphaned project folders in its vault. That failure is why identity keys on the common directory.

## What is shared, what is not

| Scope | Examples | Behavior across linked worktrees |
| --- | --- | --- |
| Shared via the common directory | object store, refs, remotes, git config, `.git/hooks` (unless `core.hooksPath` overrides) | one copy for all worktrees |
| Branch-specific (tracked files) | `AGENTS.md`, `CLAUDE.md`, `docs/`, `cog.toml`, `.gitignore` | follow the checked-out branch; two worktrees on different branches can present different instructions |
| Worktree-local (untracked or ignored) | `.projectmem/` (fully ignored here), scratch files, build output, local databases (e.g. PlanDB's `.plandb.db`) | exist only in the checkout that created them |

Consequences:

* Hooks fire everywhere: the Cocogitto `commit-msg` hook and projectmem's `post-commit`/`post-merge` hooks live in the common directory and run in every linked worktree, with the working directory set to that worktree.
* Instructions can differ by branch: a worktree on an older branch runs under that branch's `AGENTS.md`/`CLAUDE.md`. This is inherent to tracked instruction files and acceptable — merge durable policy changes to `main` promptly to keep the window small.

## Provider behavior

Verified against source or local state on 2026-08-02 unless marked otherwise.

projectmem v0.2.0:

* Store discovery walks the filesystem for `.projectmem/`, not git. This repository ignores `.projectmem/` entirely, so a linked worktree has no store and auto-capture there is a silent no-op.
* `pjm hooks install` fails inside a linked worktree (`.git` is a file there, not a directory).
* The primary checkout's hooks do fire in linked worktrees but bail out on the missing `.projectmem/`.
* Net effect: projectmem is single-checkout in this repository. Record decisions made during worktree work from the primary checkout after merging. Accepted as a known limitation.

Claude Code:

* The transcript directory is keyed to the working directory, so each worktree gets its own transcript store. The auto-memory directory follows the primary repository root instead, shared across all linked worktrees. Both were re-verified empirically 2026-08-02 (during the now-closed Obsidian Mind trial's Gate 4, docs/DECISIONS.md D028): a worktree session created a new munged transcript directory containing only its transcript `.jsonl` — no `memory/` subdirectory — while its memory context resolved to the primary checkout's `memory/`. The two keyings are deliberate and independent: transcripts split per literal path, memory is repo-level. Stated together because either half alone makes the other look wrong.

Codex:

* Thread records natively carry cwd, git SHA, branch, and origin URL (observed in local state).

PlanDB v0.2.1 (at adoption, docs/DECISIONS.md D030):

* `.plandb.db` defaults to the current working directory, so it is worktree-local like the other entries in the table above: linked worktrees do not share it automatically.
* A PlanDB execution graph belongs to the worktree executing the bounded change it coordinates. Agents being coordinated by that graph must operate against that same `.plandb.db` — in practice, run from that worktree.
* Do not assume atomic claiming, ready/blocked state, or dependency updates coordinate agents that are operating against separate, independent PlanDB databases in separate worktrees.
* Net effect: the normal model for a PlanDB-coordinated bounded change is one executing worktree with multiple native Claude Code / Codex agents operating against its graph — not a graph spanning worktrees. This is consistent with, not a change to, the one-worktree-per-active-slice rule (AGENTS.md, "Development isolation").
* If future usage demonstrates a real need to coordinate PlanDB execution across separate worktrees, treat that as a concrete seam to solve then (AGENTS.md, "Repository tooling precedence"). No synchronization mechanism or adapter is built by this note.

## Operating rules for now

* Worktrees are supported but not yet deeply integrated.
* Launch provider tools from the intended worktree; most tools key identity on the working directory.
* Expect branch-local tracked instructions to differ between worktrees; that is Git working correctly.
* Deterministic evidence must include: common directory, worktree path, branch or detached flag, full HEAD SHA, dirty summary, and remote URL when available.
* No Bindle feature may assume one checkout per repository.

## Evidence block fields

A future evidence block records, verbatim at capture time:

* repository identity: common directory path, remote URL if available
* execution identity: absolute worktree path
* code state: full HEAD SHA, dirty summary (counts of modified and untracked files), detached flag
* branch name (descriptive only)
* timestamp
* optional pointers: transcript path, thread id, PR or issue number

Blocks are immutable observations — "at time T this worktree was at SHA X on branch Y." Later history rewrites do not falsify them; they describe what was, not what should be believed now.

## History scenarios

| Scenario | Effect on an evidence block | Notes |
| --- | --- | --- |
| Detached HEAD | branch null, `detached: true` | a valid state; record it, don't error |
| Rebase | old SHAs stay in old blocks; resolvable until GC | inherent; blocks are history, not claims |
| Squash merge | pre-squash SHAs vanish from remote history | the PR number is the durable secondary pointer |
| Deleted branch | branch name becomes dangling context | SHA plus common directory still identify the work |
| Abandoned worktree | worktree path dangles | repository identity survives via the common directory |

Inherent risks (cannot be eliminated, only documented): SHA unreachability after aggressive GC; branch names becoming misleading after rewrites. Eliminable by deterministic stamping: identity confusion across worktrees (common directory), "which checkout" ambiguity (absolute path), "which code state" ambiguity (SHA plus dirty summary).

## Known single-checkout assumptions today

* `.projectmem/` is fully gitignored, so repository memory exists only in the primary checkout, and projectmem hooks can only be (re)installed from there.

A documented limitation, not a bug to fix in this pass.
