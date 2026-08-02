# PRIVACY

Public machinery must not accidentally publish the private corpus or the topology of the user's machine.

Bindle the code may be public and open source. The data it touches — session context, personal knowledge, machine layout — is private and locally owned. This document keeps those two facts compatible.

## Threat model

This is personal-disclosure protection, not secret scanning. Credentials are a separate lane with separate tools (gitleaks, detect-private-key, and the secrets rules in AGENTS.md). This guard covers what secret scanners ignore:

* personal and relay email addresses
* local home paths that reveal usernames and machine layout
* knowledge-vault names and paths
* chat-transcript shapes pasted into files
* a personal denylist: names, employers, internal codenames, private hostnames — terms that should appear zero times in any public repository, forever

## The guard

The archived prototype ships a working implementation: `bin/check-private-info.sh` (~430 lines of deliberately boring offline grep, four modes, 20 self-test fixtures, plus `bin/test-check-private-info.sh`). It is dormant but functional, and it already encodes two hard-won lessons:

* Verdict disclosure: a clean run must state whether a personal denylist was actually loaded, so "pattern rules only" can never masquerade as a full scan.
* Scope honesty: it scans tracked files, so it prints a warning when untracked files were skipped — a gap that once shipped three real home-path leaks that were green before `git add`.

## Where it runs

At the repository boundary, as a pre-commit check and in any publish or release script — a plain git hook, so Claude Code, Codex, and a human at the terminal all inherit exactly the same enforcement (D001: prefer mechanisms both harnesses already defer to). There must be one guard implementation; per-harness safety logic is a duplication bug.

## Disposition

The guard is one of the strongest extraction candidates in the project's history: it survived a full redesign, has its own tests and vocabulary, and applies to every public repository regardless of Bindle. It is not extracted in this pass — it stays dormant in the archive until a Bindle repository actually publishes content that needs it, at which point restore it (or extract it to a standalone tool) rather than rewriting it.

## Private configuration

The personal denylist lives outside every repository and is never committed. Public Bindle code may reference its path convention; it must never embed, echo, or test against real denylist terms. Fixtures are synthetic.

## Rules for this repository's own content

* No personal absolute paths in tracked files — use `$HOME`, `<repo>`, or placeholders.
* No vault names or vault paths.
* No personal or relay email addresses.
* No transcript excerpts as fixtures or examples — synthetic content only.
* Any future evidence block that may be embedded in a public place must support path redaction before emission.
