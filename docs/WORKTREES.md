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
| Branch-specific (tracked files) | `AGENTS.md`, `CLAUDE.md`, `docs/`, `cog.toml`, `.gitignore`, `.om-project` if adopted | follow the checked-out branch; two worktrees on different branches can present different instructions |
| Worktree-local (untracked or ignored) | `.projectmem/` (fully ignored here), scratch files, build output | exist only in the checkout that created them |

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

obsidian-mind / om v8.3.1 (adopted — AGENTS.md, "Obsidian Mind"; the Codex anonymous-caller gap below is a known limitation, not a trial-pending item — docs/DECISIONS.md D023):

* Caller identity is the repository folder name from the MCP roots handshake, overridable by a one-line `.om-project` marker file. Without the marker, each worktree registers as a different project — the same basename-keying failure the old prototype had.
* Operating rule: `.om-project` is committed in this repository so every worktree and branch declares the same project identity.
* om records no VCS state anywhere; two branches of one repository are indistinguishable in its records. An embedded Bindle evidence block is the intended fix.

Claude Code:

* The transcript directory is keyed to the working directory, so each worktree gets its own transcript store. The auto-memory directory follows the primary repository root instead, shared across all linked worktrees. Both were re-verified empirically 2026-08-02 (om trial Gate 4): a worktree session created a new munged transcript directory containing only its transcript `.jsonl` — no `memory/` subdirectory — while its memory context resolved to the primary checkout's `memory/`. The two keyings are deliberate and independent: transcripts split per literal path, memory is repo-level. Stated together because either half alone makes the other look wrong.

Codex:

* Thread records natively carry cwd, git SHA, branch, and origin URL (observed in local state).

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
* obsidian-mind's project identity depends on the committed `.om-project` marker (in place in this repository); without it, worktree folder names would fragment project identity.

Both are documented limitations, not bugs to fix in this pass.
