# README

A small project about making good tools work well together.

Why “Bindle”?

A bindle is a small bundle carried from place to place. It isn’t everything you own. It’s the few things worth bringing with you.

## Overview

Modern software development has no shortage of excellent tools. Git remembers history. Obsidian captures ideas. Claude Code and Codex are becoming capable engineering partners. Context7, Playwright, Hugging Face, and countless other projects each solve a very specific problem well.

The interesting work happens somewhere in the middle. Bindle is an experiment in reducing the friction between them without replacing them. The goal isn’t to build another platform. It’s to build as little as possible while making the existing workshop feel more connected.

## Principles

Inherit first. Extend second. Replace deliberately. Invent last.

A few concepts guide the project.

* Prefer existing tools over custom implementations.
* Keep repository conventions authoritative.
* Make useful things explicit before making them automated.
* Build only after a pattern appears more than once.

## Current workshop

Today Bindle assumes a fairly standard engineering toolkit.

* Coding: Claude Code, Codex
* Knowledge: Obsidian
* Documentation: Context7
* Verification: Playwright
* Source Control: Git and GitHub
* Research: Hugging Face
* Scientific Computing: CHILmesh, ADCIRC, DG-SWEM
* Game Development: Godot

These aren’t dependencies so much as assumptions. Bindle should adapt to them rather than competing with them.

## Current focus

The repository is intentionally starting small.

Before writing a memory system, graph database, or orchestration framework, the project is defining:

* the toolchain
* shared conventions
* portable skills
* MCP profiles
* project boundaries

Only then will it start answering the question of what Bindle actually needs to own.

## Non-goals

Bindle is not trying to become:

* another coding agent
* another project manager
* another note-taking application
* another documentation system
* another graph database

Excellent tools already exist in each of those spaces.
