---

description: "Task list for Public Documentation and Documentation Site"
---

# Tasks: Public Documentation and Documentation Site

**Input**: Design documents from `specs/006-public-documentation-site/` (spec.md, checklists/requirements.md, research.md, plan.md, quickstart.md)

**Prerequisites**: plan.md, spec.md, research.md, quickstart.md — all present and reconciled with the 2026-08-29 human decision pass (site-only pages at `docs/site/`; existing canonical `docs/*.md` rendered directly by MkDocs, not linked out; `docs/TOOLCHAIN.md` records MkDocs's adoption; MkDocs's own built-in default presentation only). No `data-model.md`/`contracts/` — this feature introduces no runtime data model or interface (plan.md, "Data model and contracts: deliberately skipped").

**Tests**: Not applicable in the `tests/test_*.py` sense — this feature has no Python runtime code. "Tests" here means the build/link-validation checks (US5) and the direct-execution/comprehension verification passes (US2/US3) plan.md's Technical Context already names as this feature's actual verification mechanism.

**Organization**: Grouped by user story per spec.md's priorities (P1: US1 content reconciliation, US2 Getting Started, US3 How Bindle Works; P2: US4 reference rendering + `docs/TOOLCHAIN.md`, US5 build/link-validation; P3: US6 optional diagram, kept separable). Tasks are coherent, independently-verifiable units — a single task may span the small set of files one finding or one page requires, and no task exists solely because a file changed.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1–US6)
- Every task names its exact file path(s), or the exact command sequence for a verification-only task with no tracked file of its own (mirroring `specs/005-work-state-visibility/tasks.md`'s own T001 precedent)

## Path Conventions

This is a documentation/tooling feature — no `src/`/`tests/` tree applies. All paths are relative to the repository root:

- `mkdocs.yml` — new, repository root
- `docs/site/` — new, nested inside the existing `docs/` directory (index.md, getting-started.md, how-bindle-works.md)
- `docs/SCOPE.md`, `docs/DATA-OWNERSHIP.md`, `docs/TOOLCHAIN.md` — existing, edited
- `docs/PHILOSOPHY.md`, `docs/SYMPHONY.md`, `docs/WORKTREES.md`, `docs/PRIVACY.md`, `docs/DECISIONS.md` — existing, unedited, rendered directly by MkDocs once `mkdocs.yml` exists
- `README.md` — existing, edited
- `scripts/check.sh` — existing, edited (new section only)
- `.gitignore` — existing, edited (build-output directory)

---

## Phase 1: Setup

**Purpose**: Confirm a clean baseline before any change.

- [x] T001 Confirm the existing repository verification gate passes cleanly before starting: `bash scripts/check.sh` from the repository root. (No code change; establishes a clean baseline to diff against, matching this repository's own `specs/005-work-state-visibility/tasks.md` T001 precedent.)

---

## Phase 2: Foundational

**None required.** Unlike prior features in this repository, no single piece of infrastructure blocks *every* user story here: US1 (content reconciliation), US2 (Getting Started), and US3 (How Bindle Works) are pure Markdown authoring/editing with no dependency on MkDocs existing — their own Independent Tests in spec.md are satisfied by reading the documented text directly. Only US4 and US5 need `mkdocs.yml` to exist, and that dependency is stated explicitly where it applies (Phase 6/T008) rather than hoisted into a phase that would incorrectly gate US1–US3.

---

## Phase 3: User Story 1 - Prominent docs stop contradicting current architecture (Priority: P1)

**Goal**: Close the specific stale/incomplete "Bindle-owned state" gap Grounding identified, without a broader rewrite.

**Independent Test**: Read `README.md`, `docs/PHILOSOPHY.md`'s "What Bindle is"/"What Bindle must not do", `docs/SCOPE.md`'s "Bindle owns"/"Bindle-owned state", and `docs/DATA-OWNERSHIP.md`'s ownership table; confirm each accurately reflects that Bindle durably owns bounded, repository-local coordination state (D038) in addition to configuration/cache/export, while still correctly stating Bindle never becomes the sole owner of user history/knowledge/transcripts (D015, D016, unchanged). Satisfiable with no other phase complete.

- [x] T002 [P] [US1] Reconcile the "Bindle-owned state" framing across `README.md`, `docs/SCOPE.md` ("Bindle-owned state" section), and `docs/DATA-OWNERSHIP.md` (ownership table), per research.md Decision 5's exact touch list: name the durable, repository-local coordination ledger (work-item status, blocking, claims, evidence pointers) as something Bindle owns, sourced by reference to D038 (not restated as new policy); add a distinct ownership-table row for it, separate from the existing "Evidence pointers" and "Bindle runtime state" rows; reduce `README.md`'s architecture explanation to a concise entry point that points onward rather than carrying the full model itself (FR-001, FR-016, SC-008). Leave every other passage in these three files unchanged, and leave `docs/PHILOSOPHY.md` and `docs/DECISIONS.md` untouched entirely (FR-002, FR-009 — do not describe any implemented capability, including `bindle work status/forecast`, milestone review, the Symphony projection, or the Spec Kit loader, as future or unimplemented).
- [x] T003 [US1] Verify Acceptance Scenarios 1–5 for User Story 1 (quickstart.md Walkthrough E, README/SCOPE/DATA-OWNERSHIP portion): confirm the three edits from T002 land correctly, confirm `docs/PHILOSOPHY.md` is byte-identical to its pre-feature state, and confirm `docs/DECISIONS.md`'s pre-existing entries are byte-identical via `git diff` restricted to existing entries (SC-005's pre-existing-content clause — the full SC-005 check, including any later-appended entry, is finished in Phase 9/T021).
  - *Depends on*: T002.

---

## Phase 4: User Story 2 - A newcomer runs the real coordination flow end to end (Priority: P1)

**Goal**: A truthful, execution-verified Getting Started walkthrough using only real `bindle` commands, entirely Symphony-free.

**Independent Test**: A person unfamiliar with this repository follows only the documented getting-started steps, starting from a clone of the repository, and reaches a point where `bindle work status`/`bindle work forecast` show meaningful dispatchable/blocked state derived from a real Spec Kit `tasks.md`, entirely by typing the commands as documented. Satisfiable with no other phase complete (the page itself does not require the site to build — it is read as Markdown).

- [x] T004 [US2] **Gate for T005 — direct-execution verification before content is authored (FR-003).** Run the exact command sequence from research.md Decision 6 / quickstart.md Walkthrough D against a disposable local repository with an isolated `BINDLE_HOME`, using this repository's own `specs/005-work-state-visibility/` as the worked-example feature directory:
  ```sh
  mkdir -p /tmp/bindle-newcomer-demo && cd /tmp/bindle-newcomer-demo && git init
  BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle init
  BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work load-speckit <bindle-checkout>/specs/005-work-state-visibility
  BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work status
  BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work status --json
  BINDLE_HOME="$PWD/.bindle-dev" uv run --project <bindle-checkout> bindle work forecast
  ```
  Capture the real, literal output of every command. This task produces no tracked file — its output is the input to T005. **Do not write `docs/site/getting-started.md` from assumed or remembered output; only from what this run actually printed** (SC-002).
- [x] T005 [US2] Author `docs/site/getting-started.md` using only the verified command sequence and captured output from T004: state the actual current installation path (a cloned development checkout run via `uv run bindle ...`, FR-004) with no implication that a published package exists; do not present `bindle list`/`update`/`upgrade`/`doctor` as functional (FR-003 Acceptance Scenario 5); do not require installing, configuring, or running Symphony at any point (FR-005, FR-006 — Symphony stays out of the Getting Started prerequisite path entirely).
  - *Depends on*: T004.

---

## Phase 5: User Story 3 - A newcomer understands ownership boundaries without reading the decision log (Priority: P1)

**Goal**: One page that gives a newcomer the correct ownership/execution/evidence/human-acceptance mental model.

**Independent Test**: Give the "How Bindle Works" page (and only that page, plus README's entry point) to a newcomer; confirm every answer about ownership, Symphony's role, execution, evidence, and milestone acceptance matches spec.md's Grounding section and the currently adopted decisions, without the newcomer opening `docs/DECISIONS.md`. Satisfiable with no other phase complete.

- [x] T006 [P] [US3] Author `docs/site/how-bindle-works.md` per FR-010: state plainly that Spec Kit defines work, Bindle durably records it as coordination state and exposes schedulable items, an execution harness (Symphony dispatching Claude Code or Codex) performs the work, Git/GitHub own the resulting evidence and history, Bindle records pointers to that evidence, and a human makes the milestone accept/decline decision (Acceptance Scenario 1). Explicitly state what Bindle does *not* do — execution, Git/GitHub history ownership, project/personal knowledge ownership, automated milestone acceptance (Acceptance Scenario 2). Introduce Symphony only as an optional, independently-run external coordinator per `docs/SYMPHONY.md` (FR-006) — reference material, not a Getting Started prerequisite. Every claim must trace to an already-adopted decision (D038, D039, D041, D042, D046) or directly-observable CLI behavior (Acceptance Scenario 3) — introduce no new product concept, term, or promise. State explicitly that "stateless" means stateless with respect to user history/knowledge/transcripts, not "owns no durable state at all" (Acceptance Scenario 4).
- [x] T007 [US3] Run the comprehension-check verification pass (quickstart.md Walkthrough F): give a reader unfamiliar with this repository only `docs/site/how-bindle-works.md` plus the README entry point; confirm their answers to "what does Bindle durably own," "what does it not own," "what is Symphony's role," "who decides milestone acceptance," and "is Bindle stateless" match spec.md's Grounding and FR-010 (SC-001, contributing to SC-007's fuller reconciliation pass in Phase 9/T020).
  - *Depends on*: T006.

---

## Phase 6: User Story 4 - Deeper reference material is reachable, not duplicated (Priority: P2)

**Goal**: A minimal MkDocs site whose nav renders every existing canonical `docs/*.md` file directly and reaches it from the landing page, with no duplicated content and no restructured `docs/` tree.

**Independent Test**: Starting from the documentation landing page, confirm every one of this repository's existing canonical architecture documents is reachable within a small, bounded number of navigation steps, and confirm no page on the new site restates more than a brief pointer-level summary of any of them. Requires T008 (and, for a real build, T005/T006 from Phases 4–5 — see Dependencies below); text-only review of nav intent does not.

- [x] T008 [US4] Create `mkdocs.yml` at the repository root: leave `docs_dir` at its MkDocs default (resolves to the existing `docs/` directory, covering both `docs/site/*.md` and every existing canonical `docs/*.md` file with no override — research.md Decision 2/3); `nav:` = Home → `site/index.md`, Getting Started → `site/getting-started.md`, How Bindle Works → `site/how-bindle-works.md`, and a "Reference" nav section grouping `PHILOSOPHY.md`, `SCOPE.md`, `DATA-OWNERSHIP.md`, `SYMPHONY.md`, `WORKTREES.md`, `PRIVACY.md`, `TOOLCHAIN.md`, and `DECISIONS.md` (each rendered directly, per the human decision — no separate reference/pointer page is authored); `theme:` MkDocs's own built-in default only, no third-party theme, no custom CSS/JS (human decision, 2026-08-29); `plugins:` the bundled `search` plugin only. Resolve the "site root reaches the Home page" nuance research.md Decision 2 flags (e.g., a thin `docs/index.md` redirect stub, or accepting nav-only entry) — this is a mechanical detail, not a new planning decision.
- [x] T009 [US4] Author `docs/site/index.md` (Home): brief orientation linking to Getting Started, How Bindle Works, and the Reference section — no restatement of any canonical document's substantive content (FR-008).
  - *Depends on*: T008 (nav references this file's path).
- [x] T010 [P] [US4] Edit `docs/TOOLCHAIN.md`: add a row to the "Documentation and web" table for MkDocs, state: Adopted, role: static documentation-site generator — decided, not merely recommended, per the 2026-08-29 human decision that once MkDocs participates in `scripts/check.sh`'s canonical verification path it is adopted repository tooling.
- [x] T011 [US4] Verify the Independent Test (quickstart.md Walkthrough G): build the site (`uv run mkdocs build --site-dir /tmp/bindle-docs-build`) and confirm every one of the eight existing canonical documents is reachable within a small, bounded number of navigation steps from Home; confirm by inspection that no `docs/site/*.md` page (T005, T006, T009) restates more than a brief pointer-level summary of any of them (FR-007, FR-008, US4 Acceptance Scenarios 1–2).
  - *Depends on*: T008, T009, and — for a real build to succeed at all — T005 (Phase 4) and T006 (Phase 5), since `mkdocs build --strict` fails on any nav entry whose target file doesn't yet exist. This is the same dependency Phase 7/T013 has; see Dependencies below.

---

## Phase 7: User Story 5 - The documentation build is mechanically verifiable (Priority: P2)

**Goal**: A broken internal link or missing nav target fails the canonical verification gate, not just a manual `mkdocs build`.

**Independent Test**: Build the documentation site locally; confirm it succeeds. Introduce a deliberately broken internal link or a reference to a nonexistent page; rebuild; confirm the build fails with a clear error rather than producing output.

- [x] T012 [US5] Add a new section to `scripts/check.sh` running `uv run mkdocs build --strict --site-dir <build-output-dir>`, following the file's existing `section "..."` / `|| fail=1` convention (no new script, no CI change — `.github/workflows/ci.yml` already just calls `bash scripts/check.sh`, FR-011). Add the build-output directory to `.gitignore`.
  - *Depends on*: T008 (mkdocs.yml must exist to invoke).
- [x] T013 [US5] Verify the positive path (quickstart.md Walkthroughs A and C): run `bash scripts/check.sh` and confirm the new docs-build section passes with exit 0, with no network access required at any point (FR-011). This is the first point at which the *full* site (all of Phases 4–6's pages) must already exist and build cleanly.
  - *Depends on*: T012, T005, T006, T009, T010 (docs/TOOLCHAIN.md's own file already exists regardless of T010's edit, so T010 is not a hard build dependency, but the completed feature expects it done by this point).
- [x] T014 [US5] Verify the negative path (quickstart.md Walkthrough B): deliberately introduce a broken internal link or a nav entry pointing at a nonexistent file, rebuild, confirm nonzero exit with an error identifying the broken reference (FR-012, SC-004's negative case), confirm this failure propagates to `scripts/check.sh`'s own overall nonzero exit (US5 Acceptance Scenario 3), then revert the deliberate breakage.
  - *Depends on*: T013 (the positive path must pass first, so the negative test is a true regression check against a known-good baseline).

---

## Phase 8: User Story 6 - A static workflow diagram clarifies ownership at a glance (Priority: P3, optional)

**Goal**: One static diagram reinforcing, not replacing, User Story 3's prose. Not required for P1/P2 completion.

**Independent Test**: Show the diagram alone (no surrounding prose) to a newcomer; confirm it does not, by itself, suggest Bindle performs execution, owns Git/GitHub history, owns provider knowledge, or automates human milestone acceptance.

- [x] T015 [US6] [P3 — optional, not a prerequisite for any P1/P2 task] Add one static conceptual diagram to `docs/site/how-bindle-works.md` showing Spec Kit → coordination ledger → schedulable tasks → Symphony → execution harnesses → Git/GitHub evidence → milestone review → human acceptance (FR-015); visually distinguish Bindle's own coordination-ledger boxes from Symphony/execution-harness boxes; show the accept/decline decision as a distinct, human-attributed step, never an automated output of readiness.
  - *Depends on*: T006 (the diagram is added to an already-authored page).
- [x] T016 [US6] [P3 — optional] Verify the Independent Test: show the diagram alone to a newcomer; confirm every box/arrow corresponds to a fact already stated in T006's prose, introducing no new ownership claim (US6 Acceptance Scenarios 1–3).
  - *Depends on*: T015.

---

## Phase 9: Polish & Cross-Cutting Verification

- [x] T017 [P] Run `bin/check-private-info.sh` (full-tree scan) after all new/edited content exists; confirm no personal-disclosure violation in any new `docs/site/*.md` file or edited document (FR-017, `docs/PRIVACY.md`).
- [x] T018 Content-correctness reconciliation review: re-read every new/edited page and section from Phases 3–6 (`README.md`, `docs/SCOPE.md`, `docs/DATA-OWNERSHIP.md`, `docs/TOOLCHAIN.md`, `docs/site/index.md`, `docs/site/getting-started.md`, `docs/site/how-bindle-works.md`) against spec.md's Grounding section and `docs/DECISIONS.md` D038/D039/D041/D042/D045/D046; confirm zero implemented capabilities are described as future/placeholder anywhere in this newly-authored or edited material (FR-002, SC-003), confirm no contradiction with any of the six named decisions (SC-007), and confirm the full ownership/architecture explanation is reachable within one navigation step from Home while `README.md` no longer carries it as primary content (SC-008, direct before/after comparison).
  - *Depends on*: T002, T005, T006, T009, T010.
- [x] T019 [P] Structural-safety review: inspect every file this feature adds or edits (`mkdocs.yml`, `docs/site/*.md`, the `scripts/check.sh` addition) and confirm none of them contains, imports, or invokes a server/backend process, an authentication mechanism, or any code path that opens, queries, or otherwise reads a `.bindle-work/*.sqlite3` file (FR-013, FR-014, SC-006) — i.e., this feature builds nothing `docs/DECISIONS.md` D045 already declined under a different name.
  - *Depends on*: T008, T012.
- [x] T020 Run `bash scripts/check.sh` in full (every section, including the new docs-build section) and confirm it passes cleanly before this feature's PR is considered ready, per `AGENTS.md`'s standing verification rule.
  - *Depends on*: T003, T007, T011, T013, T014, T017, T018, T019.
- [ ] T021 [Optional] Append one new entry to `docs/DECISIONS.md` recording this feature's own adoption, per this repository's normal append-only decision-log convention (SC-005 permits this; it is not required to consider the feature complete, and it must not edit any pre-existing entry).
  - *Depends on*: T020.

---

## Considered and Declined (non-executable — no task exists for any of this)

Mirroring `specs/005-work-state-visibility/tasks.md`'s own convention of recording an evaluated-and-declined surface explicitly rather than silently omitting it: this feature builds **no** `bindle view` or other live/dynamic rendering of any repository's coordination-ledger state, **no** backend or runtime server process, **no** authentication mechanism, **no** documentation database, **no** custom JavaScript application behavior, **no** third-party theme or custom CSS/design-system work, **no** versioned docs, **no** blog/news infrastructure, **no** generated API reference, **no** analytics, **no** package publishing, **no** broad `docs/` restructuring beyond adding `docs/site/`, **no** repository-visibility change, **no** GitHub Pages activation, **no** deployment workflow beyond the build-output-readiness `mkdocs.yml`/`.gitignore` already listed in Phase 6/7, and **no** generalized command-output-drift detection system (output-drift remains a named residual risk per spec.md Assumptions, not solved by this feature). This is materially the same shape `docs/DECISIONS.md` D045 already evaluated and declined for `bindle view` — building any of the above into "the documentation site" instead would not change its nature, and would require a new, separately-scoped decision, not an extension of this task list (spec.md, "Considered and Declined").

---

## Dependencies & Execution Order

**Phase completion order**: Setup (T001) → {US1, US2, US3 in any order/in parallel — Phases 3, 4, 5} → US4 (Phase 6, needs T005/T006 for a real build) → US5 (Phase 7, needs Phase 6's `mkdocs.yml` and every page) → US6 (Phase 8, optional, needs T006) → Polish (Phase 9).

**Cross-phase dependencies worth calling out explicitly** (none are cyclic):

- T008 (`mkdocs.yml`, Phase 6) can be *authored* independently of Phases 3–5, but the first *successful* `mkdocs build --strict` — needed by T011 (Phase 6) and T013 (Phase 7) — requires T005 (Phase 4) and T006 (Phase 5) to already exist, because a nav entry pointing at a not-yet-created file is itself the kind of broken-reference condition `--strict` is meant to catch. T009 (Home) is authored within Phase 6 itself. Practically: do Phases 3–5's content work before attempting Phase 6/7's first real build, even though Phases 3–5 do not need Phase 6/7 to exist first.
- T004 → T005 (Phase 4 internal gate, FR-003): content must not be written from assumed output.
- T006 → T007 (Phase 5 internal gate): the comprehension check needs the page to exist.
- T012 → T013 → T014 (Phase 7 internal sequence): wire the check, prove it passes, then prove it correctly fails.
- T015 → T016 (Phase 8 internal gate, optional).
- Phase 9 (T018–T020) depends on the substantive content/config work in Phases 3–7 being done; T021 is the only task with a downstream dependency on Phase 9 itself (T020).

**No task asks its implementer to re-decide anything plan.md/research.md already settled**: site location (`docs/site/`), rendering approach (direct render, not link-out), theme (MkDocs's own default), and `docs/TOOLCHAIN.md` inclusion are all stated as given facts in the relevant tasks above, not as open choices.

## Parallel Execution Examples

Within Setup: none (single task).

Across Phases 3–5 (all P1, mutually independent files): T002 [US1], T004 [US2], T006 [US3] can all start together once T001 is done — they touch disjoint files (`README.md`/`docs/SCOPE.md`/`docs/DATA-OWNERSHIP.md` vs. no tracked file yet vs. `docs/site/how-bindle-works.md`).

Within Phase 6: T010 (`docs/TOOLCHAIN.md`) can run in parallel with T008/T009 — disjoint files, no shared dependency.

Within Phase 9: T017 (privacy guard) and T019 (structural-safety review) can run in parallel — disjoint concerns and disjoint output.

## Implementation Strategy

**Suggested MVP scope**: spec.md frames P1 as three co-equal, independently valuable stories rather than one dominant story. The single fastest independently-shippable increment is **User Story 1 alone** (Phase 3, T002–T003) — it corrects an active factual contradiction in already-published documentation and needs nothing else in this feature to be true or valuable. The smallest increment that delivers this feature's actual comprehension goal (spec.md SC-001) is **all of US1 + US2 + US3** (Phases 3–5) — a newcomer gets a correct, truthful, runnable mental model even before the MkDocs site itself exists, since all three pages/edits are plain Markdown, readable directly. Phases 6–7 (US4/US5) turn that content into a real, mechanically-verified site; Phase 8 (US6) is additive polish at any point afterward.
