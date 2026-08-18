# WORKTREES

## Purpose

Bindle must behave correctly when a Git repository has more than one checkout.

Bindle’s own development flow requires worktrees (AGENTS.md, “Development isolation”), so multiple checkouts are an operating condition, not an edge case.

This document defines Bindle’s repository, execution, and code-state identity model and the worktree semantics of deterministic evidence.

## Identity model

Bindle distinguishes three forms of identity:

* Repository identity — the Git common directory (`git rev-parse --git-common-dir`), with stable remote metadata when available.
* Execution identity — the absolute worktree path (`git rev-parse --show-toplevel`).
* Code-state identity — the full commit SHA plus a description of dirty state.

The branch name is descriptive context, never primary identity. Branches may be renamed, rebased, squashed, or deleted.

The Git common directory is a local repository identity shared by linked worktrees. Its absolute path is machine-local and must not be treated as a portable cross-machine identifier.

A normalized remote URL, when available, provides portable repository context but is not sufficient by itself to identify a local checkout.

No Bindle feature may assume one checkout per repository.

## Git sharing model

Linked worktrees share some Git state while retaining independent checked-out files and local artifacts.

| Scope | Examples | Behavior across linked worktrees |
| --- | --- | --- |
| Shared through the common directory | object store, refs, remotes, Git config, hooks unless core.hooksPath overrides them | one shared repository-level copy |
| Branch-specific tracked files | AGENTS.md, CLAUDE.md, docs/, configuration, source files | follow the branch checked out in that worktree |
| Worktree-local files | ignored state, scratch files, build output | exist only where created unless another mechanism shares them |

Two consequences matter operationally:

* Repository-level Git hooks may execute from any linked worktree even though their implementation is shared.
* Tracked instructions and configuration may differ between worktrees on different branches. This is normal Git behavior.

Durable policy changes should be merged promptly to reduce the period in which active branches carry materially different instructions.

## Operating rules

* Launch tools from the worktree whose state they are intended to observe or modify.
* Confirm repository root, branch or detached state, and worktree before editing.
* Do not modify sibling worktrees.
* Do not infer repository identity from a worktree directory name.
* Do not assume provider-specific repository or session identity matches Bindle’s identity model.
* Treat branch names as descriptive metadata, not durable identity.
* Preserve exact local execution identity when capturing private evidence.
* Apply privacy redaction when evidence crosses a disclosure boundary.

Provider-specific limitations do not redefine Bindle’s identity model.

## Evidence blocks

An evidence block is an immutable observation that work occurred at a particular repository, checkout, time, and code state.

Bindle emits evidence blocks into records owned by other systems. It does not accumulate them as canonical project history.

Evidence records what was observed, not what remains reachable, current, or authoritative later.

## Fields

A deterministic evidence block records values observed at capture time.

Repository identity

* normalized Git common-directory path
* normalized remote URL, when available

Execution identity

* absolute worktree path

Code state

* full HEAD commit SHA
* dirty summary
* detached-HEAD flag
* branch name when attached

Capture context

* timestamp
* agent or execution harness when known

Optional pointers

* transcript or thread identifier
* pull request or issue identifier
* other provider-owned record identifiers when useful

Optional pointers provide provenance or recovery paths. Their absence does not invalidate the underlying evidence.

## Branch semantics

Branch names are descriptive only.

An evidence block anchored to commit X remains a valid observation even if its recorded branch is later renamed, rebased, deleted, or moved to another commit.

Detached HEAD is a valid state and must be represented explicitly rather than treated as an error.

## Dirty state

Dirty state describes divergence from the recorded HEAD.

At minimum, the summary must distinguish a clean worktree from one containing tracked modifications or untracked files.

A count-based dirty summary is descriptive and deterministic for the observation, but it does not uniquely identify the contents of uncommitted changes.

Consumers must not interpret a matching SHA and dirty-file count as proof that two dirty worktrees contain identical code.

If stronger identification of uncommitted state is later required, it must be introduced deliberately rather than inferred from the existing dirty summary.

## Immutability

Evidence blocks are immutable observations:

> At time T, this worktree was observed at code state X.

Later Git operations do not rewrite existing evidence.

An evidence block is provenance, not automatically durable project guidance or promoted knowledge.

## History scenarios

| Scenario | Effect on evidence | Interpretation |
| --- | --- | --- |
| Detached HEAD | branch absent; detached flag set | valid code state |
| Rebase | old SHA remains in the historical block | block describes the pre-rebase observation |
| Squash merge | pre-squash SHA may disappear from remote history | provider pointers such as a PR may aid recovery |
| Deleted branch | branch becomes historical context | SHA and repository identity remain the primary evidence |
| Abandoned worktree | recorded worktree path may no longer exist | repository-level context survives|
| Git garbage collection | unreachable SHA may eventually become locally unresolvable | does not falsify the historical observation |

Some risks are inherent to Git history: commits may become unreachable, branches may disappear, and paths may stop existing.

Deterministic capture eliminates a different class of ambiguity:

* which repository — Git common directory plus remote context
* which checkout — worktree path
* which committed state — full HEAD SHA
* whether uncommitted divergence existed — dirty summary
* whether a branch existed at capture time — branch and detached state

## Privacy and portability

Canonical local evidence may contain absolute paths because paths are necessary to distinguish execution identity between linked worktrees.

Absolute paths are machine-local and potentially identifying. They are not portable identifiers.

When evidence crosses a disclosure boundary, apply the redaction requirements in docs/PRIVACY.md.

A public or externally shared representation should preserve useful provenance without exposing personal home paths, usernames, machine topology, or other protected information.

Redacted representations are projections of the original evidence. Redaction must not silently change the semantics of repository identity, execution identity, or code state.

## Provider compatibility

Execution harnesses, memory tools, and other providers may use different rules to identify repositories, sessions, or working directories.

Bindle must not infer those rules from its own identity model or rely on undocumented provider behavior.

When provider identity matters:

1. use supported provider interfaces where available
2. verify the relevant behavior
3. preserve Bindle’s own deterministic evidence independently
4. treat provider identifiers as pointers rather than canonical Bindle identity

Current provider-specific observations, compatibility limitations, versions, and experiments belong in docs/TOOLCHAIN.md or the relevant decision or trial record, not in this specification.
