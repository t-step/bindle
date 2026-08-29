# WORKTREES

## Purpose

Bindle must behave correctly when a Git repository has more than one checkout.

Bindle’s own development flow requires worktrees (AGENTS.md, “Development isolation”), so multiple checkouts are an operating condition, not an edge case.

This document defines Bindle’s repository, execution, and code-state identity model, and how the evidence pointers recorded against coordination state (docs/DECISIONS.md D046) relate to worktree identity.

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
* Preserve exact local execution identity in any locally recorded coordination state.
* Apply privacy redaction if identity-model output — a path, an evidence pointer — crosses a disclosure boundary.

Provider-specific limitations do not redefine Bindle’s identity model.

## Evidence pointers

Bindle's adopted provenance mechanism is the Evidence Pointer (docs/DECISIONS.md D046): a small, append-only reference — a branch name, a commit SHA, a pull request, or another provider-owned locator — recorded against coordination state. Its schema and invariants live in `specs/001-durable-work-ledger/data-model.md` and are implemented by `work_item_evidence` in `src/bindle/work_ledger.py`; this document does not restate that schema.

An evidence pointer names a piece of Git/GitHub (or other provider-owned) state without duplicating it. Bindle records pointers; it does not accumulate a separate evidence history or store the evidence itself.

An evidence pointer establishes provenance — that work occurred at a particular repository, checkout, and code state — without itself becoming durable project guidance or promoted knowledge.

## Branch and commit semantics

Branch names are descriptive only (Identity model, above).

An evidence pointer naming a commit or branch remains a valid historical record even if that branch is later renamed, rebased, squashed, or deleted — a rebased, squashed, or deleted branch's pointer is left in place, not "fixed" or rewritten. A commit-kind pointer's value should be the full HEAD commit SHA, never an abbreviated form, matching this document's own code-state identity convention.

Detached HEAD is a valid state and must be represented explicitly rather than treated as an error, wherever code-state identity is captured.

## History scenarios

| Scenario | Effect on a recorded evidence pointer | Interpretation |
| --- | --- | --- |
| Rebase | the pointer's recorded value (e.g. an old SHA) is unchanged | the pointer describes the pre-rebase observation |
| Squash merge | a pre-squash SHA a pointer names may disappear from remote history | a pull-request pointer may aid recovery |
| Deleted branch | a branch-kind pointer's value becomes historical context | the pointer itself, and repository identity, remain the primary evidence |
| Git garbage collection | a commit-kind pointer's SHA may eventually become locally unresolvable | does not falsify the historical observation |

Some risks are inherent to Git history: commits may become unreachable, branches may disappear, and paths may stop existing.

Later Git operations do not rewrite existing evidence.

## Privacy and portability

Absolute local paths appear in Bindle's identity-model output — execution identity, and any worktree path recorded elsewhere in coordination state — because they are necessary to distinguish checkouts between linked worktrees.

Absolute paths are machine-local and potentially identifying. They are not portable identifiers.

If any such path, or an evidence pointer's recorded value, is ever surfaced across a disclosure boundary, apply the redaction requirements in docs/PRIVACY.md.

A public or externally shared representation should preserve useful provenance without exposing personal home paths, usernames, machine topology, or other protected information.

A redacted representation is a projection of the original. Redaction must not silently change the semantics of repository identity, execution identity, or code state.

## Provider compatibility

Execution harnesses, memory tools, and other providers may use different rules to identify repositories, sessions, or working directories.

Bindle must not infer those rules from its own identity model or rely on undocumented provider behavior.

When provider identity matters:

1. use supported provider interfaces where available
2. verify the relevant behavior
3. preserve Bindle’s own identity model and evidence pointers independently
4. treat provider identifiers as pointers rather than canonical Bindle identity

Current provider-specific observations, compatibility limitations, versions, and experiments belong in docs/TOOLCHAIN.md or the relevant decision or trial record, not in this specification.
