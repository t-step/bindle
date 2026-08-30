# Research: Public Documentation and Documentation Site

**Input**: `specs/006-public-documentation-site/spec.md` (Grounding, Assumptions, "Deferred to Planning / Research")

Every decision below resolves one of spec.md's explicitly deferred planning questions. None reopens a settled specification decision; each cites the FR/SC/Grounding entry it satisfies.

**2026-08-29 human decision pass** (post-initial-planning, pre-`/speckit.tasks`): four planning open items were resolved by explicit operator decision rather than left to implementation-time judgment. Decisions 2 and 5 below are rewritten to reflect them; Decision 1's theme wording is tightened for clarity. No specification decision was reopened — see each decision's text for the specific change and its rationale.

---

## Decision 1: Static docs generator — MkDocs, built-in default presentation only

**Decision**: Adopt plain **MkDocs** (`pip`/`uv`-installable, pure Python, MIT-licensed) as the static-site generator, using only its own built-in default theme (`mkdocs`, or `readthedocs` — the choice is an implementation-time detail, not a planning decision), its built-in search plugin, and no third-party plugins or themes beyond what ships with MkDocs itself. "Built-in default presentation" means exactly that — MkDocs's own out-of-the-box appearance, unmodified — not an instruction to suppress or work around MkDocs's normal rendering. No third-party theme dependency (e.g., no Material for MkDocs) and no custom CSS/JS are introduced in this slice (human decision, 2026-08-29).

**Rationale**:

- **Pure Python, zero new-language toolchain.** MkDocs is a Python package installable as an ordinary `uv`-managed dependency, consistent with this repository's Python/`uv` baseline (`pyproject.toml`, `AGENTS.md` CLI invocation). It introduces no Node.js/npm, no Rust toolchain, and no second package manager.
- **Mature and stable.** MkDocs has a long release history and a stable, well-documented configuration surface (`mkdocs.yml`, `nav`, plugin API). For a dependency that becomes part of the repository's canonical verification gate (`scripts/check.sh`), stability outweighs novelty.
- **Satisfies every functional requirement without a theme.** FR-011/FR-012/SC-004 require only that the site build locally without network access and that `mkdocs build --strict` fail on a broken internal link or a nav entry pointing at a missing file — both are native MkDocs behavior via its `validation` config block (`nav.omitted_files`, `links.not_found`, `links.absolute_links`, `links.anchors`, each settable to `warn`, which `--strict` promotes to a build-failing error) and the standard `nav:` key in `mkdocs.yml` (an entry pointing at a nonexistent file is itself a `links.not_found`-class validation warning). No plugin is required to get build-time link/nav validation.
- **No elaborate theming needed.** The spec's own scope discipline (Scope discipline: "no elaborate theming or branding") means bare MkDocs's default theme is sufficient; adding Material for MkDocs would pull in a larger dependency and configuration surface (extra Markdown extensions, custom CSS/JS asset pipeline) to satisfy a requirement (visual polish) this feature explicitly does not have.
- **Built-in search.** MkDocs ships a `search` plugin enabled by default — satisfies general newcomer navigability without an added dependency.

**Alternatives considered**:

- **Zensical** (`zensical/zensical`, PyPI `zensical`) — a Rust-core, Python-packaged successor to MkDocs/Material for MkDocs, built by the same team, positioned to eventually replace both. Verified: it has its own `--strict` mode and internal-reference validation (link, footnote, and anchor resolution) as of release v0.0.38, and can read an existing `mkdocs.yml` for compatibility. It is a credible, well-regarded, actively developed project. **Rejected for adoption now, not rejected outright**: as of this research, Zensical is published on PyPI with Alpha development status at a pre-1.0 version (`0.0.x` line) — its module system was still being opened to third-party developers in early 2026, and MkDocs/Material for MkDocs were only placed in maintenance mode (not end-of-life) in November 2025 with a committed 12-month support window. Adopting an Alpha-stage tool for a dependency load-bearing on the repository's canonical verification gate (`scripts/check.sh`) does not match this repository's tooling precedence (`AGENTS.md`, "Replace tooling only when it is broken, unsafe, contradictory, abandoned, or explicitly under review" — MkDocs is none of those yet) or `docs/TOOLCHAIN.md`'s adoption-state discipline (a pre-1.0 tool with an actively evolving CLI surface fits "Trial" or "Deferred," not "Adopted"). **Recorded as a Deferred candidate** (see "Deferred" below) to revisit once Zensical reaches a stable (post-1.0, or otherwise declared stable) release — a concrete, demonstrated-need trigger, not a speculative migration.
- **Sphinx** — mature and Python-native, but its idiomatic source format is reStructuredText (Markdown support exists via MyST but is a secondary path) and its dominant real-world use case is generated API-reference documentation — a capability this feature's Non-Goals/scope discipline explicitly excludes ("no generated API docs"). Using Sphinx here would mean adopting a heavier tool for a use case (newcomer narrative pages linking to existing hand-written Markdown) it is not optimized for. Rejected without a deeper comparison — the decision does not change.
- **Docusaurus** — capable and widely used for documentation sites, but requires a Node.js/npm toolchain entirely foreign to this Python/`uv`, Markdown-first repository (`AGENTS.md` CLI invocation, `pyproject.toml`). Adopting it would mean introducing a second language ecosystem and package manager solely for documentation. Rejected without a deeper comparison — the decision does not change.

**Deferred**: Revisit Zensical once it ships a stable (non-`0.0.x`/non-Alpha) release. If adopted later, its `mkdocs.yml`-compatibility path means this feature's `mkdocs.yml` and `docs/` source tree would very likely carry over with little or no change — deferring now does not create migration debt.

---

## Decision 2: Information architecture and rendering approach

**Decision** (revised 2026-08-29 by explicit human decision, superseding this decision's original "link out" recommendation): site-only orientation pages live at **`docs/site/`** — `docs/site/index.md` (Home), `docs/site/getting-started.md`, `docs/site/how-bindle-works.md` — and every existing canonical `docs/*.md` reference document is **rendered directly by MkDocs**, in place, as a real site page. The governing rule, stated by the operator: *one canonical Markdown source, rendered through the documentation site.* `docs/site/`'s pages orient and route readers into the canonical documents; they do not copy or restate their substantive content (FR-008 still governs the *new* pages, not whether the existing files are built).

A minimal top-level nav:

```
Home                  → docs/site/index.md
Getting Started       → docs/site/getting-started.md
How Bindle Works      → docs/site/how-bindle-works.md
Reference (section)   → PHILOSOPHY.md, SCOPE.md, DATA-OWNERSHIP.md, SYMPHONY.md,
                         WORKTREES.md, PRIVACY.md, TOOLCHAIN.md, DECISIONS.md
                         (each rendered directly, nav paths relative to docs_dir)
```

**Why `docs/site/` (not a repository-root or non-nested location)**: nesting the new orientation pages *inside* the existing `docs/` directory means MkDocs's own default `docs_dir` (a folder literally named `docs`, next to `mkdocs.yml`, when `docs_dir` is left unset) already covers both the new pages and every existing canonical document with zero non-default configuration — no `docs_dir` override, no symlink, no multi-root plugin. This is the same "smallest configuration that satisfies the requirement" reasoning as Decision 1's theme choice: the location the operator picked is also the path of least MkDocs configuration.

**No separate "Reference" content page is authored.** Since the canonical documents are rendered directly (not summarized on a new pointer page), the "Reference" node in `mkdocs.yml`'s `nav:` is a **nav section** grouping the eight existing documents by title — structure, not new prose. This still satisfies FR-007 (a discoverable navigation path to each document from the landing page) and FR-008 (no duplication — there is nothing to duplicate; the rendered page *is* the canonical file). `docs/DECISIONS.md` is included in this Reference section, not the primary Home/Getting-Started/How-Bindle-Works path — preserving FR-009's "MUST NOT require it as reading to understand the primary spec-to-milestone-review workflow" and the operator's restated constraint that it "remains historical reference and must not become required onboarding reading."

**Alternatives considered**: A deeper nav mirroring `docs/`'s own structure with one top-level (not grouped) nav entry per document was considered and rejected — it would visually promote every reference document to primary-navigation status, contradicting US4's framing of them as reachable-but-secondary, and the spec's explicit "no broad docs-tree restructuring." The originally-recommended "link out" approach (plain Markdown links to `docs/*.md` as GitHub-rendered files, never built by MkDocs) is superseded by the human decision above — it remains a valid FR-008-satisfying design in the abstract, but the operator's stated rule ("one canonical Markdown source, rendered through the documentation site") specifically prefers direct rendering, and direct rendering does not introduce a second copy of anything — `docs/*.md` stays the one and only source; MkDocs only builds it into HTML at the same source path.

**Implementation-time nuance, not a further planning decision**: MkDocs maps output paths to source paths relative to `docs_dir`. A page at `docs/site/index.md` builds to `site/index.html`, not the site root's `index.html` — visiting the bare site root will not automatically show the Home page unless either (a) `docs/index.md` itself also exists as a thin redirect/landing stub, or (b) the built site is always entered via its nav (acceptable for a local/newcomer-facing site with no public root URL yet, consistent with Decision 4's "readiness, not activation"). This is a mechanical detail for implementation to resolve and verify (a task acceptance check: "the built site's Home page is reachable"), not a reason to relocate `docs/site/`.

---

## Decision 3: Build and link-validation strategy, and `scripts/check.sh` integration

**Decision**: A new `mkdocs.yml` at the repository root, with `docs_dir` left at its MkDocs default (`docs/`, already Bindle's existing canonical docs directory — see Decision 2) so both `docs/site/*.md` and every existing `docs/*.md` canonical document build from the one tree with no docs_dir override. The docs build runs as `uv run mkdocs build --strict --site-dir <build-output-dir>`. A new section is added to `scripts/check.sh` (not a separate parallel script) that runs this command and fails the gate (`fail=1`) on nonzero exit, following the file's own existing `section "..."`/`|| fail=1` convention used by every other check.

**Rationale**: Directly satisfies FR-011 (build succeeds locally, no network access — MkDocs's `search` and (if used) other bundled plugins operate entirely offline; no Google Fonts or CDN fetch is enabled by default in the bare theme), FR-012 (`--strict` turns `nav`/link-validation warnings into a nonzero exit), US5's Independent Test (build succeeds on a correct tree, fails with a clear error on a deliberately broken link or missing nav target), and SC-004. Placing it inside `scripts/check.sh` — rather than a separate script CI invokes independently — satisfies "one canonical verification path" (spec.md's Verification framing) and AGENTS.md's standing rule that `scripts/check.sh` is the canonical gate; `.github/workflows/ci.yml` needs no change, since it already just calls `bash scripts/check.sh`.

**Network-access verification**: MkDocs core and its bundled `search` plugin (Lunr-based, generated at build time) require no network access to build. No Google Fonts, CDN-hosted assets, or remote plugin data sources are introduced by this plan — confirmed by using only the bundled theme and bundled plugin. If a future page needs an additional MkDocs plugin, it must be checked against this same offline-build requirement before adoption.

**Test-first negative check**: `python3 -m unittest` and `shellcheck` already run in `scripts/check.sh` as separate sections; the new docs-build section is independent of both and does not change their behavior. A concrete negative-path test (deliberately broken link, rebuild, confirm nonzero exit — US5 Acceptance Scenario 2) is implementation-phase work (`/speckit.tasks`), not resolved further here.

---

## Decision 4: Deployment-readiness shape (not activation)

**Decision**: This feature makes the repository **capable** of a conventional static-host deploy without performing any deploy, visibility change, or Pages activation:

- `mkdocs.yml` plus the `docs/`/site-only source produce a self-contained static `site/`-equivalent output directory (path decided during implementation, e.g. `site/` or `_site/`, gitignored) via `mkdocs build`.
- No `.github/workflows/*.yml` file that deploys (e.g., a `gh-pages` publish step or a Pages deployment action) is added by this feature.
- No change to repository visibility (still private) or GitHub Pages settings.

**Rationale**: Directly matches spec.md's Assumptions ("this specification does not resolve or require" a visibility/Pages change) and Grounding's explicit split between "deployable... as a build-output capability" and "an instruction to actually flip the repository public or turn on Pages." `docs/TOOLCHAIN.md`'s "Release tooling" section already treats CI/publication infrastructure as "ordinary repository infrastructure... introduced according to demonstrated repository needs," so a future, separately-decided PR can add an actual deploy workflow once the repository's visibility/Pages decision (an operator decision, not this feature's) is made.

---

## Decision 5: Content reconciliation — exact touch list

**Decision**: Five existing/new document surfaces are touched, matching Grounding's own findings, FR-001/FR-009/FR-010/FR-016, and the 2026-08-29 human decision to record MkDocs in `docs/TOOLCHAIN.md`:

| Document | Change | Requirement |
|---|---|---|
| `README.md` | Add that Bindle durably owns bounded, repository-local coordination state (the ledger); reduce to a concise entry point pointing onward rather than carrying the full architecture explanation | FR-001, FR-016, SC-008 |
| `docs/SCOPE.md` | "Bindle-owned state" section gains a distinct, `BINDLE_HOME`-independent coordination-ledger category, sourced by reference to D038 (not restated as new policy) | FR-001 |
| `docs/DATA-OWNERSHIP.md` | Ownership table gains a row for the coordination ledger/work items, distinct from the existing "Evidence pointers" and "Bindle runtime state" rows | FR-001 |
| `docs/TOOLCHAIN.md` | "Documentation and web" table gains a row for MkDocs (state: Adopted) — decided, not merely recommended: once MkDocs participates in `scripts/check.sh`'s canonical verification path, it is adopted repository tooling, not an incidental implementation detail (human decision, 2026-08-29) | repository convention (`docs/TOOLCHAIN.md`'s own adoption-state discipline), not a numbered FR |
| New: `docs/site/how-bindle-works.md` | States the ownership/execution/evidence/human-acceptance model per US3/FR-010 | FR-010, US3, SC-001, SC-007 |

**`docs/PHILOSOPHY.md` requires no change.** Verified against Grounding and against the file's own text (read this session): "What Bindle must not do" and the replaceability/durability/preservation rules (D014–D016) already state Bindle's statelessness *with respect to user history/knowledge/transcripts* — exactly the qualified claim this feature needs preserved, not the unqualified "no durable state at all" reading Grounding found only in the *summary* framing of README/SCOPE/DATA-OWNERSHIP. No passage in `docs/PHILOSOPHY.md` asserts the incorrect unqualified claim, so User Story 1's Acceptance Scenario 4 ("any passage that is still accurate as written... is left unchanged") applies to the whole file. Confirmed again during this decision pass: no new repository evidence contradicts this finding.

**`docs/DECISIONS.md`'s existing content is explicitly not touched** by this reconciliation pass (FR-009); a new entry recording this feature's own eventual adoption is permitted later, per SC-005 and normal repository decision-log convention (append-only), but is implementation/completion-time work, not part of this touch list. It is rendered directly by MkDocs (Decision 2) but placed in the Reference nav section, not the primary onboarding path.

**Files expected to be added**:

- `mkdocs.yml` (repository root; `docs_dir` left at its MkDocs default so it resolves to the existing `docs/` tree — Decision 2/3)
- `docs/site/index.md` (Home), `docs/site/getting-started.md`, `docs/site/how-bindle-works.md` — decided location and shape (human decision, 2026-08-29); no separate `reference/index.md` is authored (Decision 2)
- A new `scripts/check.sh` section (edit, not a new file)
- A gitignore entry for the build output directory (edit to `.gitignore`)

**Files expected to be modified**: `README.md`, `docs/SCOPE.md`, `docs/DATA-OWNERSHIP.md`, `docs/TOOLCHAIN.md`, `scripts/check.sh`, `.gitignore`.

**Files explicitly not modified**: `docs/DECISIONS.md` (existing entries), `docs/PHILOSOPHY.md`, `docs/SYMPHONY.md`, `docs/WORKTREES.md`, `docs/PRIVACY.md` — none of these carry the stale framing Grounding identified, and all five are rendered as-is (no content edit) even though four of them now also build as site pages.

---

## Decision 6: Getting Started walkthrough — worked example and verification requirement

**Decision**: The Getting Started page documents this exact, real command sequence, run against a disposable local repository with an isolated `BINDLE_HOME`:

```sh
git init <scratch-dir> && cd <scratch-dir>
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle init
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work load-speckit <feature-dir>
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work status
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work status --json
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work forecast
```

using this repository's own `specs/005-work-state-visibility/` as the worked-example feature directory (real, complete, already in this repository, and Symphony-free — confirmed by reading `specs/005-work-state-visibility/tasks.md` this session). The exact invocation form (`uv run --project` vs. running from inside a cloned checkout) is finalized during implementation once the actual page text is drafted — this decision fixes the command *sequence* and *worked example*, not final prose.

**Rationale**: Directly satisfies FR-003 (only real, currently-implemented commands), FR-004 (development-checkout install path, no implied published package), FR-005 (dispatchable/blocked state and forecast, no Symphony), and Grounding's "getting-started flow is real and Symphony-free" finding (already directly exercised this session: `bindle --help`, `bindle work --help`, `bindle milestone --help` all confirm these subcommands exist and match this description). Using `specs/005-work-state-visibility/` as the worked example satisfies spec.md's Assumption that Spec Kit's own real `specs/*/tasks.md` files may be used without inventing a fictional domain.

**Deferred to implementation**: FR-003's requirement that "every command shown... is verified by direct execution before publication" means the actual documented output (command → output pairs) must be captured by literally running these commands against a fresh scratch repository at content-authoring time, not reconstructed from this research pass's own exploratory verification. This is `/speckit.tasks` + implementation-phase work.

**Output-drift residual risk** (spec.md Assumptions): no mechanism is added by this feature to detect when a future CLI change makes previously-correct documented example output stale. This is named here as a known, explicitly out-of-scope gap, not solved by this plan.

---

## Confirmation: D045 is not reopened

This feature's public documentation site is static and build-time-generated; it reads no repository's `.bindle-work/*.sqlite3` file, starts no server process, and requires no authentication (FR-013/FR-014/SC-006, enforced structurally by the generator choice in Decision 1 and the deployment shape in Decision 4 — nothing in this plan's file list includes a server module or ledger-reading code path). `docs/DECISIONS.md` D045's declined `bindle view` (a live, per-repository operational surface) remains declined and unreferenced by any artifact this plan produces, other than as historical citation in spec.md's own "Considered and Declined" section. No proposal in this research reopens it.
