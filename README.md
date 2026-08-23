# README

A small project about making good tools work well together.

Why “Bindle”?

A bindle is a small bundle carried from place to place. It isn’t everything you own. It’s the few things worth bringing with you.

## Overview

Modern software development has no shortage of excellent tools. Git remembers history. Obsidian captures ideas. Claude Code and Codex are becoming capable engineering partners. Context7, Playwright, Hugging Face, and countless other projects each solve a very specific problem well.

The interesting work happens somewhere in the middle. Bindle is an experiment in reducing the friction between them without replacing them. The goal isn’t to build another platform. It’s to build as little as possible while making the existing workshop feel more connected.

Concretely, Bindle is a stateless toolchain bridge. Each tool in the workshop owns its own domain — Git owns history, the harnesses own transcripts, the vault owns knowledge — and Bindle helps context and evidence cross the seams between them: it calls supported interfaces, collects deterministic facts, emits portable evidence blocks that other systems embed, and holds pointers that the owning systems resolve. It keeps no database of your history. If a better provider appears for any responsibility, the provider gets replaced; Bindle doesn’t get rewritten. The full statement of this shape — including what Bindle refuses to become and the admission test for new features — lives in [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md), with data ownership and routing in [docs/DATA-OWNERSHIP.md](docs/DATA-OWNERSHIP.md).

## Principles

Inherit first. Extend second. Replace deliberately. Invent last.

A few concepts guide the project.

* Prefer existing tools over custom implementations.
* Keep repository conventions authoritative.
* Make useful things explicit before making them automated.
* Build only after a pattern appears more than once.

## CLI

Bindle has a minimal, provider-neutral CLI. Run it in development with `uv run`:

```sh
uv run bindle --version
uv run bindle repo info
uv run bindle repo info --json
```

* `bindle --version` — deterministic package version.
* `bindle repo info` — repository/execution/code-state identity (docs/WORKTREES.md): repository root, current worktree root, Git directory, Git common directory, current branch (when attached), and HEAD SHA. Add `--json` for machine-readable output.

The CLI stays intentionally small; it is infrastructure for future narrow capabilities, not a work-DAG or orchestration layer (see AGENTS.md, docs/SCOPE.md).

## Current workshop

Today Bindle assumes a fairly standard engineering toolkit — coding harnesses, a knowledge vault, source control, and a handful of domain-specific tools spanning scientific computing and game development.

These aren’t dependencies so much as assumptions. Bindle should adapt to them rather than competing with them. The full, current toolchain — and why each tool is there — lives in [docs/TOOLCHAIN.md](docs/TOOLCHAIN.md); this file doesn't duplicate that list.

## Current focus

The repository is intentionally starting small.

Before writing a memory system, graph database, or orchestration framework, the project is defining:

* the toolchain
* shared conventions
* portable skills
* MCP recommendations by task
* project boundaries

What Bindle owns — and what it refuses to own — is written down in [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md) and [docs/SCOPE.md](docs/SCOPE.md).

## Non-goals

Bindle is not trying to become:

* another coding agent
* another project manager
* another note-taking application
* another documentation system
* another graph database
* another memory system, context database, or retrieval engine
* the canonical owner of notes, transcripts, session records, or user knowledge

Excellent tools already exist in each of those spaces.

The measure of Bindle is not how many responsibilities it acquires, but how many responsibilities it can confidently decline because another tool already owns them.
