# PRIVACY

Public machinery must not accidentally publish the private corpus or the topology of the user’s machine.

Bindle code may be public and open source. The data it touches, including session context, personal knowledge, and machine layout, is private and locally owned. This document defines the boundary between them.

## Threat model

This is personal-disclosure protection, not secret scanning.

Credentials and other secrets are a separate concern handled by dedicated tooling and the secrets rules in AGENTS.md.

Personal-disclosure protection covers information that conventional secret scanners may not recognize:

* personal and relay email addresses
* local home paths that reveal usernames or machine layout
* knowledge-vault names and paths
* chat-transcript shapes copied into files
* explicitly denylisted personal terms, such as names, employers, internal codenames, or private hostnames

The goal is to prevent private context and machine topology from crossing into public artifacts.

## Disclosure boundaries

Treat any movement from private or local state into a potentially publishable surface as a disclosure boundary.

Examples include:

* tracked repository files
* commits and pull requests
* generated artifacts
* exports
* evidence pointers
* prompts or handoffs intended for external use
* release and publication output

Apply privacy filtering before emission or publication, not afterward.

Repository commit-time enforcement is a backstop, not permission to generate unsafe content earlier in the workflow.

## Personal-disclosure guard

bin/check-private-info.sh is the repository’s canonical personal-disclosure guard. Its self-tests live in bin/test-check-private-info.sh. Both are tracked in this repository and run offline.

The guard is intended to run at the repository boundary as a pre-commit check, scanning the staged (index) content a commit would actually write — not the working tree, which can differ from what gets committed. Git hooks are not tracked by Git, so a fresh checkout has no enforcement until the hook is installed locally. `.git` is a plain file (not a directory) in a linked worktree, so writing directly to `.git/hooks/pre-commit` breaks there; resolve the hook path through Git instead, which works from both a primary checkout and a linked worktree:

```
hook="$(git rev-parse --git-path hooks/pre-commit)"
cat > "$hook" <<'HOOK'
#!/usr/bin/env bash
exec bin/check-private-info.sh --staged
HOOK
chmod +x "$hook"
```

Until that step is done, the guard exists and can be run manually (`bash bin/check-private-info.sh --staged`, or `bash bin/check-private-info.sh` for the full tree) but is not enforced automatically. Do not describe the guard as "enforced by the repository" in a context where the reader cannot reproduce that enforcement from a fresh checkout — say instead that the guard is present and must be installed. Publish or release mechanisms that can expose repository content must apply the same guard.

Claude Code, Codex, and humans at the terminal should inherit the same enforcement once the hook is installed. Do not create separate harness-specific implementations of the same privacy policy.

### Guard invariants

#### Verdict disclosure

A clean result must state whether the personal denylist was loaded. A pattern-only scan must never appear equivalent to a complete scan.

#### Scope honesty

The guard must disclose meaningful gaps in its scan scope. In particular, if untracked files are outside the scanned set, the result must say so.

#### Offline operation

The guard must not transmit repository contents, denylist terms, or findings to an external service.

#### Single implementation

Maintain one canonical implementation of the disclosure guard. Extend that implementation rather than creating provider- or harness-specific copies.

## Private configuration

The personal denylist lives outside every repository and must never be committed.

Path convention: `$BINDLE_DENYLIST` when set, otherwise `<notes home>/private-denylist.txt`, where the notes home is `$BINDLE_NOTES_DIR` when set, else `~/.bindle`. One term per line, case-insensitive, `#` comments. A term belongs on the list only if it has zero *unvouched* tracked occurrences, forever — a specific legitimate occurrence may carry a narrow `private-ok` vouch (the same mechanism the normal scan honors), but an unvouched occurrence means the term isn't ready to rely on. `bin/check-private-info.sh --audit-denylist` proves that against the current tree before a term starts flagging every commit.

Public Bindle code may reference the denylist’s path convention, but must never:

* embed real denylist terms
* print or echo real denylist terms unnecessarily
* include real denylist terms in tests or fixtures
* copy the denylist into repository-owned state

Tests and examples must use synthetic values.

Absence of the personal denylist must be distinguishable from a successful full scan.

## Repository content rules

Tracked repository content must not contain:

* personal absolute paths; use $HOME, <repo>, or another non-identifying placeholder
* personal vault names or vault paths
* personal or relay email addresses
* real chat transcript excerpts used as fixtures or examples
* terms prohibited by the configured personal denylist

Use synthetic content for fixtures, examples, documentation, and tests whenever private material would otherwise be required.

Do not weaken these rules merely because a repository is currently private. Bindle’s machinery should remain safe to publish without depending on repository visibility as the privacy boundary.

## Generated and exported content

Any Bindle feature that emits information derived from local or private state must consider disclosure before emission.

Generated content intended for potentially public use must support appropriate redaction or omission of private information.

In particular:

* paths that may identify the user or machine must be redactable
* an evidence pointer's recorded value, if it is ever a path, must support redaction before embedding outside local state
* generated examples must not substitute real private data for synthetic fixtures
* exports must not silently broaden the set of private information being disclosed

Preview-before-apply or preview-before-publish should be preferred when the disclosure consequences are not obvious to the user.

## Relationship to secret scanning

Personal-disclosure protection complements rather than replaces secret scanning.

Secret scanners protect credentials and credential-like material. The disclosure guard protects contextual information that may be harmless as a credential but private in aggregate or by association.

Both protections may apply to the same publication boundary. Passing one does not imply passing the other.
