# Implementation Plan: Public Documentation and Documentation Site

**Branch**: `spec/public-documentation-site` | **Date**: 2026-08-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/006-public-documentation-site/spec.md`

**Baseline**: `docs/DECISIONS.md` D038 (durable work ledger), D039/D041 (Symphony projection and proven Tracker adapter), D042 (milestone review surface), D043/D044 (unconditional ledger/projection provisioning and collision safety), D045 (work-state visibility adopted at US1–US4; `bindle view` evaluated and declined), and D046 (evidence-pointer model, superseding the old evidence-block framing) are all implemented, tested, and unchanged by this feature. This plan adds no new lifecycle behavior, no new ledger schema, and no runtime code path over any of them — it is a documentation-and-tooling feature only. `docs/DECISIONS.md` D045's "Considered and Declined" boundary (a live, per-repository operational surface) is preserved exactly as spec.md's own "Considered and Declined" section states; see Constitution Check and Research Decision 6 ("Confirmation: D045 is not reopened").

## Summary

Correct the specific stale/incomplete passages Grounding identified in `README.md`, `docs/SCOPE.md`, and `docs/DATA-OWNERSHIP.md` (durable coordination state is real and currently unrecorded in their "Bindle-owned state" framing); add a new "How Bindle Works" newcomer page and a Getting Started walkthrough built from real, already-implemented `bindle` commands run against a disposable local repository; and stand up a minimal static documentation site (MkDocs, built-in default presentation only — no third-party theme) whose new orientation pages live at `docs/site/` and which renders every existing canonical `docs/*.md` file directly (one canonical Markdown source, rendered through the site — never duplicated), builds and link-validates locally with no network access, and is wired into `scripts/check.sh` as the canonical verification gate. No live ledger read, server process, authentication, or deployment activation is introduced (FR-013/FR-014, Research Decision 4/"Confirmation: D045 is not reopened").

**2026-08-29 human decision pass** (post-initial-planning, pre-`/speckit.tasks`): four planning open items were resolved by explicit operator decision — (1) `docs/TOOLCHAIN.md` gains an MkDocs adoption row, now part of this feature's touch list; (2) site-only content location is fixed at `docs/site/`, not an implementation-time choice; (3) existing canonical `docs/*.md` files are rendered directly by MkDocs rather than linked out, superseding this plan's original "Option 1" recommendation; (4) "built-in default presentation only" wording is clarified to mean MkDocs's own out-of-the-box theme, not a stripped-down or workaround configuration. Research Decisions 1, 2, and 5 are updated accordingly; see research.md's "2026-08-29 human decision pass" note.

## Technical Context

**Language/Version**: Python 3.11+ (repository baseline, `pyproject.toml`, `requires-python = ">=3.11"`). MkDocs itself supports this range.

**Primary Dependencies**: One new dependency: **MkDocs** (built-in default presentation only, no third-party theme, no third-party plugins — Research Decision 1). Everything else in this feature (the content-reconciliation edits, the new Markdown pages, the `scripts/check.sh` addition) uses only what the repository already has (Markdown files, Bash, the existing `bindle` CLI). No Python source (`src/bindle/`) is touched — this feature has no runtime/library code.

**Storage**: N/A. This feature reads and writes only tracked Markdown/YAML/Bash files; it never touches `.bindle-work/*.sqlite3` (FR-013, SC-006) or any other repository-local state store.

**Testing**: No new `tests/test_*.py` is added — this feature has no Python runtime behavior to unit-test. Verification is: (a) `mkdocs build --strict` succeeding on a correct tree and failing nonzero on a deliberately broken internal link or missing nav target (US5, SC-004) — a `scripts/check.sh` section, not a `unittest` module; (b) FR-003's command-by-command direct-execution verification of every documented CLI command before publication (implementation-phase discipline, not an automated test); (c) `bin/check-private-info.sh` (unchanged, already covers all tracked files including new ones) for FR-017/`docs/PRIVACY.md` compliance.

**Target Platform**: Static site output, buildable and browsable on any machine with the repository checked out and MkDocs installed; deployable (not deployed) to a conventional static host (Research Decision 4). No server-side runtime target.

**Project Type**: Documentation/content feature with one small tooling addition (`scripts/check.sh` section) — not a library/CLI/service feature. No `src/`/`tests/` structure applies.

**Performance Goals**: N/A — a small, newcomer-scale static site (single-digit page count). No performance requirement beyond "builds locally in a reasonable time," which bare MkDocs trivially satisfies at this scale.

**Constraints**: Must not read any `.bindle-work/*.sqlite3` file, start a server, or require authentication (FR-013/FR-014, SC-006). Must not edit `docs/DECISIONS.md`'s existing entries (FR-009, SC-005). Must not duplicate the substantive content of any existing canonical `docs/*.md` file (FR-008). Must not present any currently-interface-only stub command (`bindle list`, `update`, `upgrade`, `doctor`) as functional (FR-003, US2 Acceptance Scenario 5). Must not imply a published, installable Bindle package exists (FR-004). Must build and validate with no network access at build time (FR-011). Must not restructure or rename the existing `docs/` tree (spec.md Scope discipline).

**Scale/Scope**: One small static site — three new orientation pages (`docs/site/index.md`, `getting-started.md`, `how-bindle-works.md`) plus eight existing `docs/*.md` files rendered directly (no new content authored for those eight), optionally one static diagram page/section at P3 — plus targeted edits to four existing files (`README.md`, `docs/SCOPE.md`, `docs/DATA-OWNERSHIP.md`, `docs/TOOLCHAIN.md`) and one existing script (`scripts/check.sh`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` remains the unfilled Spec Kit template (unchanged from every prior plan's own finding in this repository). This repository's operative constitution remains `AGENTS.md` ("Architecture rules," "Repository tooling precedence") and `docs/PHILOSOPHY.md` (the feature-admission test, D014–D016), per repo-local precedence — consistent with specs/001–005's own plans.

Gates evaluated:

| Gate | Status | Basis |
|---|---|---|
| No live read of any repository's `.bindle-work/*.sqlite3`, no server process, no authentication mechanism (FR-013/FR-014, SC-006) | **PASS** | This feature's file list (Project Structure below) contains no server module, no database-access code, and no auth code — the site is static Markdown built by MkDocs. Structurally enforced by the generator choice (Research Decision 1) and the deployment-readiness-not-activation shape (Research Decision 4). |
| Does not reopen `docs/DECISIONS.md` D045's declined `bindle view` (spec.md "Considered and Declined") | **PASS** | See Research, "Confirmation: D045 is not reopened." No artifact in this plan reads live ledger state or renders it. |
| `docs/DECISIONS.md` remains historical, append-only, unedited by this feature's own touch list (FR-009, SC-005) | **PASS** | Research Decision 5's touch list explicitly excludes `docs/DECISIONS.md`. A future *appended* entry recording this feature's own adoption is permitted by SC-005 but is completion-time work, not part of this plan's file list. |
| No duplication of an existing canonical document's substantive content (FR-008) | **PASS** | Research Decision 2 (revised): existing `docs/*.md` files are rendered directly by MkDocs — the one canonical source, built into the site with no second copy. `docs/site/`'s own new pages route to them; they do not restate their content. |
| No implemented capability described as future/placeholder (FR-002, FR-003) | **PASS** (design-level; content-level verification is implementation-phase) | Research Decision 6 requires every documented command be verified by direct execution before content is authored — this plan does not itself author page prose, so the gate applies to the *approach*, which correctly requires verification-before-publication rather than assuming it. |
| No new toolchain/dependency surface beyond a demonstrated, minimal need (`AGENTS.md`, "Repository tooling precedence," "Invent last") | **PASS** | Exactly one new dependency (MkDocs) is added, chosen specifically because it requires no new language runtime, no new package manager, and no theme/plugin beyond what ships with it (Research Decision 1). Alternatives (Zensical, Sphinx, Docusaurus) were evaluated and rejected for concrete, stated reasons, not skipped. |
| One canonical verification path, no duplicate CI behavior (spec.md Verification framing, US5) | **PASS** | The docs build/link-validation check is added as a new section inside the existing `scripts/check.sh`, not a second script `.github/workflows/ci.yml` would need to learn about separately — CI continues to just call `bash scripts/check.sh` unchanged. |
| No repository-visibility or GitHub Pages activation performed by this feature (spec.md Assumptions, Deferred Questions) | **PASS** | Research Decision 4 scopes this feature to build-output readiness only; no workflow file that deploys is added, and no operator-level GitHub setting is touched. |
| No broad docs-tree restructuring; existing `docs/*.md` files are not renamed or moved (spec.md Scope discipline) | **PASS** | Research Decision 2/5: new site-only pages live at `docs/site/`, nested inside the existing `docs/` tree without moving or renaming any existing file; every existing `docs/*.md` path is unchanged even though four of them now also build as site pages. |
| Personal-disclosure guard coverage for new tracked content (`docs/PRIVACY.md`, FR-017) | **PASS** | `bin/check-private-info.sh` already scans the full tracked tree, including any new files this feature adds; no new denylist term or guard change is needed since all new content is either synthetic (command examples) or already-public policy prose. |
| Worktrees (D018) — the documentation site has no worktree-dependent state | **PASS** (N/A) | The site is built from tracked files common to every worktree of this repository; it has no per-worktree runtime state to get wrong. |

No unjustified violations. Complexity Tracking is not filled in below because none apply.

## Project Structure

### Documentation (this feature)

```text
specs/006-public-documentation-site/
├── spec.md                        # Already complete (input to this plan)
├── checklists/requirements.md     # Already complete
├── plan.md                        # This file
├── research.md                    # Phase 0 output
└── quickstart.md                  # Phase 1 output
```

No `data-model.md` and no `contracts/` are produced — see "Data model and contracts: deliberately skipped" below.

### Source Code / Content (repository root)

```text
mkdocs.yml                         # New — MkDocs project config; docs_dir left at its default (docs/), nav,
                                    #   built-in default theme only, bundled search plugin only

docs/                               # docs_dir for MkDocs — existing tree plus one new subdirectory, no renames:
├── site/                           #   New — site-only orientation pages (decided location, human decision)
│   ├── index.md                    #     Home
│   ├── getting-started.md          #     Getting Started — the verified command walkthrough (Research Dec. 6)
│   └── how-bindle-works.md         #     How Bindle Works — ownership/execution/human-review model (US3)
├── SCOPE.md                        #   Edited — "Bindle-owned state" section gains coordination-ledger
│                                    #     category (FR-001); also now rendered directly as a site page
├── DATA-OWNERSHIP.md               #   Edited — ownership table gains coordination-ledger/work-items row
│                                    #     (FR-001); also now rendered directly as a site page
├── TOOLCHAIN.md                    #   Edited — "Documentation and web" table gains an MkDocs row, state:
│                                    #     Adopted (human decision, 2026-08-29); also rendered as a site page
├── PHILOSOPHY.md                   #   Unchanged content — rendered directly as a site page
├── SYMPHONY.md                     #   Unchanged content — rendered directly as a site page
├── WORKTREES.md                    #   Unchanged content — rendered directly as a site page
├── PRIVACY.md                      #   Unchanged content — rendered directly as a site page
└── DECISIONS.md                    #   Unchanged content (existing entries) — rendered directly as a site
                                     #     page, placed in the Reference nav section, not the onboarding path

README.md                           # Edited — names durably-owned coordination state (FR-001); reduced to a
                                     #   concise entry point pointing onward (FR-016, SC-008)

scripts/check.sh                    # Edited — new section: `uv run mkdocs build --strict --site-dir <dir>`,
                                     #   `|| fail=1`, matching the file's existing section/fail convention

.gitignore                          # Edited — ignore the MkDocs build output directory
```

**Structure Decision**: This feature is content/tooling-only — it introduces no `src/bindle/` module and no `tests/test_*.py` file, unlike specs/001–005. The one new piece of executable-ish surface is a single new `scripts/check.sh` section (a shell command invocation, not new shell logic) and a new `mkdocs.yml` configuration file. New site-only prose content lives at `docs/site/`, nested inside the existing `docs/` tree by explicit human decision — this both keeps MkDocs's `docs_dir` at its zero-configuration default and lets every existing `docs/*.md` canonical document render directly as a site page (Research Decision 2) without being moved, renamed, or copied.

### Data model and contracts: deliberately skipped

This feature introduces no new runtime data model, no persisted schema, no API, and no CLI subcommand — `data-model.md` and `contracts/` would have nothing genuinely new to describe beyond what `mkdocs.yml`'s own `nav:` key already expresses structurally. Per the plan workflow's own "skip if project is purely internal" guidance for contracts, and because there are no entities with fields, relationships, or state transitions to extract for a data model, both are omitted rather than generated as empty boilerplate.

## Phasing (for /speckit.tasks, not started in this session)

Reflecting spec.md's own user-story priorities:

- **P1 (User Stories 1–3)**: Content reconciliation (`README.md`, `docs/SCOPE.md`, `docs/DATA-OWNERSHIP.md`); `docs/site/getting-started.md` with the verified command walkthrough (Research Decision 6); `docs/site/how-bindle-works.md` (Research Decision 5).
- **P2 (User Stories 4–5)**: `mkdocs.yml` with the Reference nav section rendering existing canonical docs directly (Research Decision 2), plus the `docs/TOOLCHAIN.md` MkDocs-adoption row; `scripts/check.sh` docs-build/link-validation wiring (Research Decisions 1 and 3).
- **P3 (User Story 6, optional)**: A static conceptual diagram on the "How Bindle Works" page. Not designed further here; remains optional and lowest-priority, addable or droppable without affecting P1/P2 completion, per spec.md's own framing.

`/speckit.tasks` is explicitly **not** run in this session (user instruction) — this phasing is recorded so a future task-composition pass does not need to rediscover story-to-artifact mapping from spec.md alone.

## Deliberately deferred (not part of this feature; recorded so it isn't rediscovered as an oversight)

- Concrete build-output directory name (e.g. `site/` vs `_site/`) — implementation-time detail with no behavioral consequence; must be gitignored either way.
- The mechanical detail of making the built site's root URL resolve to `docs/site/index.md`'s content (a thin `docs/index.md` redirect stub, or accepting nav-only entry for a not-yet-deployed site) — Research Decision 2's "implementation-time nuance," verified by a task acceptance check, not a further planning decision.
- Actual GitHub Pages activation or repository-visibility change — operator decision, out of scope (Research Decision 4).
- Output-drift detection (documented example output going stale after a future CLI change) — named residual risk, not solved here (spec.md Assumptions).
- The optional static diagram (US6) — P3, not designed in this plan.
- Exact wording/diff for `README.md`/`docs/SCOPE.md`/`docs/DATA-OWNERSHIP.md`/`docs/TOOLCHAIN.md` beyond the specific Grounding-identified gaps and the decided MkDocs-adoption row — implementation-phase content authoring.

**Resolved since initial planning** (2026-08-29 human decision pass, no longer open): site-only content location (`docs/site/`, fixed); whether existing `docs/*.md` are rendered directly by MkDocs (yes, superseding the original "link out" recommendation); whether `docs/TOOLCHAIN.md` records MkDocs's adoption (yes, now in the touch list); MkDocs presentation wording (its own built-in default theme, unmodified).
