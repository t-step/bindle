# Feature Specification: Public Documentation and Documentation Site

**Feature Branch**: `spec/public-documentation-site`

**Created**: 2026-08-29

**Status**: Draft

**Input**: User description: "Bindle has accumulated enough real product surface (repository-local guardrails, a Bindle-owned durable SQLite coordination ledger, Spec Kit task ingestion, task claims/completion/evidence pointers/publication, a Symphony-readable projection and proven Symphony-side Tracker adapter, milestone work items and a human milestone-review surface, `bindle work status`/`--json`/`--watch`, `bindle work forecast`, and optional Projectmem/QMD/skill-kit integrations) that the README and architecture documents no longer provide a clean newcomer path — some prominent documentation still frames Bindle broadly as a 'stateless toolchain bridge,' wording that predates the durable coordination ledger. Determine, from grounding against the actual repository, whether a simpler truthful newcomer explanation is supportable (specification tools define work; Bindle maintains durable coordination state and exposes schedulable work; execution harnesses perform the work; Git/GitHub and other providers own their evidence and history; Bindle records evidence pointers; humans retain semantic acceptance at milestone boundaries), sharpen or reject that hypothesis against evidence, and specify a narrow first public-documentation-and-documentation-site slice — reconciling stale docs, adding a getting-started path and a 'how work flows' page, making deeper reference documents navigable, and establishing a static, locally buildable documentation site — while explicitly not reopening `docs/DECISIONS.md` D045's declined `bindle view` (a live local operational surface over Bindle work-item state)."

## Grounding

This section records what was directly verified against the repository (`main` @ `a24110ae09f9bd072a2123eef8842d6189ffbc7d`) before any requirement below was written, per this repository's own "ground before you spec" convention (`specs/001`–`005`'s own "Baseline"/grounding sections).

- **The durable work ledger is real, tested, and load-bearing, and README.md never mentions it.** `bindle init` (verified by direct execution against a disposable local repository) unconditionally provisions `.bindle-work/ledger.sqlite3` and `.bindle-work/symphony-projection.sqlite3` (D043), and `bindle work load-speckit`, `bindle work status`, `bindle work status --json`, and `bindle work forecast` (verified by direct execution against `specs/005-work-state-visibility/tasks.md` loaded into a fresh ledger) correctly report dispatchable/blocked/claimed state and a dependency frontier with no Symphony process involved at any point. Yet README.md's CLI section documents only `bindle --version`, `bindle repo info`, `bindle branch`, and the lifecycle-command table (`init`/`remove`/`status`/etc.) — it names no `bindle work` or `bindle milestone` subcommand anywhere, even though `specs/001`–`005` (adopted in D038, D039, D042, D045) are the majority of this repository's actually-implemented, actually-tested product surface.
- **`docs/SCOPE.md`'s "Bindle-owned state" section is factually incomplete, not merely stale wording.** It states Bindle-owned state is "limited to: configuration / disposable cache that can be rebuilt from owning providers / explicit exports requested by the user," all "under `BINDLE_HOME`." Verified directly in `src/bindle/work_ledger.py` (`ledger_path()`, `_LEDGER_DIR_NAME = ".bindle-work"`): the coordination ledger lives at `<repo_root>/.bindle-work/ledger.sqlite3` — inside the Git repository's own common directory, **not** under `BINDLE_HOME` — and is none of the three listed categories: it is not configuration, it is not "disposable cache... rebuilt from owning providers" (claim/status/blocking/evidence facts have no other owning provider to rebuild from), and it is not an explicit user-requested export (D043 made its creation unconditional). D038 itself calls the ledger "accepted, bounded Bindle-owned coordination state" — a real, decision-adopted category `docs/SCOPE.md`'s own "Bindle-owned state" section does not name. `docs/DATA-OWNERSHIP.md`'s ownership table has the same gap: it has a row for "Evidence pointers" and one for "Bindle runtime state | `BINDLE_HOME`," but no row for the coordination ledger / work items themselves.
- **"Bindle is a stateless toolchain bridge" (README.md, `docs/PHILOSOPHY.md`, `docs/SCOPE.md`, `AGENTS.md`) remains true in the sense those documents actually argue for — statelessness with respect to *user history, knowledge, notes, and transcripts* (D015, unchanged and reaffirmed as recently as D046) — but is misleading if read as "Bindle keeps no durable state at all," which is no longer true and has not been true since D038 (2026-08-26). No document currently states this distinction explicitly.
- **The getting-started flow is real and Symphony-free.** Directly exercised end-to-end in a disposable repository with an isolated `BINDLE_HOME`: `bindle init` → `bindle work load-speckit <feature-dir>` → `bindle work status` / `bindle work status --json` / `bindle work forecast` → (not exercised further here, but documented and tested elsewhere) `bindle work claim`/`done`, `bindle milestone review`/`accept`/`decline`. None of this requires Symphony to be installed, configured, or running. Symphony (`docs/SYMPHONY.md`) is a referenced, independently-run external coordinator — its own toolchain (Elixir/Erlang via `mise`, a `WORKFLOW.md`, a tracker) is entirely separate from anything `bindle init` provisions.
- **There is no installable published Bindle package today.** Verified: no Git tags exist, `.github/workflows/ci.yml` runs only `scripts/check.sh` (no build/publish job), and `docs/TOOLCHAIN.md`'s "Release tooling" section explicitly leaves packaging/publication as future, undecided repository infrastructure. The only currently truthful "install" path is cloning the repository and running `uv run bindle ...`, exactly as `AGENTS.md`'s "CLI invocation" section already states for development use.
- **No documentation-site tooling of any kind currently exists.** Verified by search: no `mkdocs`, `sphinx`, `docusaurus`, `zensical`, or similar reference anywhere in tracked files; no `gh-pages` branch or ref on `origin`; no GitHub Pages workflow. This is a greenfield build within this feature's scope, not a migration.
- **`docs/DECISIONS.md` D045 declined a local *operational* surface (`bindle view`) — a live, loopback-served rendering of the ledger's current work-item state, optionally composed with Symphony's own live runtime facts — specifically because no repeated, observed friction demonstrated a need for it once `bindle work status`/`--json`/`--watch` and `bindle work forecast` already existed.** That decision is about a live view of a specific repository's *current coordination state*. A public documentation site explaining Bindle's architecture, with static examples and command walkthroughs, is a categorically different artifact — general-audience, build-time-generated, and never a read of any specific repository's live `.bindle-work/` ledger. This specification treats collapsing that distinction as a defect (see "Considered and Declined" and Non-Goals).
- **Spec Kit is this repository's own adopted skill kit** (`bindle.toml`: `kits = ["spec-kit"]`, D035) and is what produced `specs/001`–`005` and this very specification. The getting-started walkthrough can truthfully use this repository's own real `specs/*/tasks.md` files (or a synthetic equivalent) as its worked example without inventing a fictional domain.
- **The repository is currently private on GitHub** (per standing operator context). Free GitHub Pages publishing from a private repository has platform-level prerequisites this specification does not resolve — see Assumptions and Deferred Questions. "Deployable to a conventional static host such as GitHub Pages" is specified here as a *build-output capability*, not as an instruction to actually flip the repository public or turn on Pages.

## Terminology

- **Newcomer**: a technically competent reader (a maintainer, a future contributor, or an interested engineer) who has not read `docs/DECISIONS.md` and has no prior session context with this repository. The primary audience for every user story below except US5 (build verification), whose audience is the repository maintainer.
- **Coordination state**: the durable, repository-local facts Bindle itself stores and is the sole owner of — work-item status, blocking edges, claims, and evidence pointers, held in `.bindle-work/ledger.sqlite3` (D038) and exported as `.bindle-work/symphony-projection.sqlite3` (D039). Distinct from, and never to be confused with, **user history/knowledge** (notes, transcripts, project memory, personal knowledge) — the category `docs/PHILOSOPHY.md`'s D015 says Bindle must never become the sole copy of.
- **Documentation site**: the static, build-time-generated public documentation surface this feature specifies. Never a live reader of any repository's `.bindle-work/` ledger, never a network service, never the declined `bindle view` (D045) under a different name.
- **Reference documentation**: this repository's existing, already-canonical architecture documents (`docs/PHILOSOPHY.md`, `docs/SCOPE.md`, `docs/DATA-OWNERSHIP.md`, `docs/SYMPHONY.md`, `docs/WORKTREES.md`, `docs/PRIVACY.md`, `docs/TOOLCHAIN.md`, `docs/DECISIONS.md`). This feature makes them navigable; it does not replace, restructure, or duplicate them by default.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prominent docs stop contradicting current architecture (Priority: P1)

A newcomer reading README.md, `docs/PHILOSOPHY.md`, or `docs/SCOPE.md` today forms a mental model that Bindle keeps no durable state of its own beyond configuration/cache/export — a model contradicted by the durable coordination ledger these same documents never mention. This story corrects that, narrowly: only the specific stale-or-incomplete passages identified in Grounding, not a rewrite of every sentence.

**Why this priority**: Every other story in this feature builds newcomer-facing material on top of these documents' claims. If the source documents themselves still assert the pre-ledger model, any new page built alongside them either repeats the same error or visibly disagrees with them — this must be fixed first, and has standalone value even if no documentation site is ever built.

**Independent Test**: Read README.md, `docs/PHILOSOPHY.md`'s "What Bindle is"/"What Bindle must not do", `docs/SCOPE.md`'s "Bindle owns"/"Bindle-owned state", and `docs/DATA-OWNERSHIP.md`'s ownership table after this story is implemented; confirm each accurately reflects that Bindle durably owns bounded, repository-local coordination state (D038) in addition to configuration/cache/export, while still correctly stating Bindle never becomes the sole owner of user history, knowledge, transcripts, or another provider's domain (D015, D016, unchanged).

**Acceptance Scenarios**:

1. **Given** README.md as it exists today, **When** this story is implemented, **Then** README.md's description of Bindle names the coordination ledger and coordination state as something Bindle durably owns, alongside its existing correct claims about not owning user history/notes/transcripts.
2. **Given** `docs/SCOPE.md`'s "Bindle-owned state" section as it exists today, **When** this story is implemented, **Then** that section names the repository-local coordination ledger as a distinct, `BINDLE_HOME`-independent category of Bindle-owned durable state, sourced by reference to D038 rather than restated as new policy.
3. **Given** `docs/DATA-OWNERSHIP.md`'s ownership table as it exists today, **When** this story is implemented, **Then** the table includes a row for the coordination ledger / work items, distinguishing it from the existing "Evidence pointers" and "Bindle runtime state" rows.
4. **Given** any passage in `docs/PHILOSOPHY.md`'s "What Bindle must not do" or `docs/DATA-OWNERSHIP.md`'s routing table that is still accurate as written (e.g., Bindle never becoming the sole owner of transcripts or personal knowledge), **When** this story is implemented, **Then** that passage is left unchanged — this story corrects specific identified gaps, not a general rewrite.
5. **Given** `docs/DECISIONS.md`, **When** this story is implemented, **Then** it is not edited, restructured, or treated as needing reconciliation — it remains the historical, append-only record; only prominent *summary* documents that restate architecture in newcomer-facing prose are in scope.

---

### User Story 2 - A newcomer runs the real coordination flow end to end (Priority: P1)

A newcomer follows a documented getting-started path and, using only real `bindle` commands against a disposable local repository, provisions Bindle, loads a Spec Kit feature's tasks into the ledger, and observes dispatchable/blocked/claimed state and a dependency forecast — without installing, configuring, or running Symphony.

**Why this priority**: Reading about the architecture (User Story 3) is not the same as a newcomer confirming it is real by running it themselves. This is the other half of a truthful newcomer path and stands alone in value even before the conceptual page or a built site exist.

**Independent Test**: A person unfamiliar with this repository follows only the documented getting-started steps, starting from a clone of the repository, and reaches a point where `bindle work status`/`bindle work forecast` show meaningful dispatchable/blocked state derived from a real Spec Kit `tasks.md`, entirely by typing the commands as documented — no undocumented step required, no command that fails or behaves differently than described.

**Acceptance Scenarios**:

1. **Given** a newcomer with a cloned checkout of the repository and no prior Bindle experience, **When** they follow the documented getting-started path, **Then** every command they are told to run (installation/execution, `bindle init`, loading tasks, `bindle work status`/`forecast`) is a real, currently-implemented command that behaves as documented — verified directly, not asserted.
2. **Given** the documented installation step, **When** a newcomer follows it, **Then** it describes the actual current path (a development checkout run via `uv run bindle ...`) and does not imply a published, installable package exists.
3. **Given** the documented getting-started path, **When** a newcomer completes it, **Then** they have observed dispatchable, blocked, and claimed work-item state and a dependency forecast without installing, configuring, or starting Symphony at any point.
4. **Given** the getting-started path's worked example, **When** a newcomer inspects it, **Then** it uses this repository's own real (or a clearly-labeled synthetic-but-representative) Spec Kit `tasks.md` shape, not an invented CLI surface.
5. **Given** the stub lifecycle commands (`bindle list`, `update`, `upgrade`, `doctor`), **When** the getting-started path is written, **Then** it does not present any of them as functional — either omitting them or explicitly labeling them as not yet implemented, matching README.md's own existing "interface-only placeholder" framing.

---

### User Story 3 - A newcomer understands ownership boundaries without reading the decision log (Priority: P1)

A newcomer reads one page — "How Bindle Works" or equivalent — and comes away able to correctly state what Bindle owns (coordination state: status, blocking, claims, evidence pointers), what it exposes (schedulable work, via the Symphony projection), what it explicitly does not own or do (execution, orchestration, Git/GitHub history, transcripts, project/personal knowledge), and where human judgment remains required (milestone acceptance) — without reading `docs/DECISIONS.md`.

**Why this priority**: This is the comprehension outcome the whole feature exists to produce. User Stories 1 and 2 make the underlying facts truthful and runnable; this story is where a newcomer actually forms the correct mental model from them.

**Independent Test**: Give the "How Bindle Works" page (and only that page, plus README's entry point) to a newcomer; ask them to state what Bindle durably owns, what Symphony's role is, who/what performs execution, who owns Git/GitHub evidence, and who makes the accept/decline call on a milestone; confirm every answer matches this specification's Grounding section and the currently adopted decisions (D038, D039, D041, D042, D046) without the newcomer having opened `docs/DECISIONS.md`.

**Acceptance Scenarios**:

1. **Given** the "How Bindle Works" page, **When** a newcomer reads it, **Then** it states plainly that specification tooling (Spec Kit) defines work, Bindle durably records that work as coordination state and exposes which items are currently schedulable, an execution harness (Symphony dispatching Claude Code or Codex) performs the work, Git/GitHub own the resulting evidence and history, Bindle records pointers to that evidence, and a human makes the milestone accept/decline decision.
2. **Given** the same page, **When** a newcomer reads it, **Then** it does not claim Bindle performs execution, owns Git/GitHub history, owns project or personal knowledge, or automates milestone acceptance from readiness alone — each of these is stated as explicitly not Bindle's role, matching `docs/SCOPE.md`'s "Bindle does not own" and D042's "readiness is mechanical; acceptance is semantic."
3. **Given** the same page, **When** a newcomer reads it, **Then** every claim it makes traces to a currently-adopted decision or directly-observable CLI behavior — it introduces no new product concept, term, or promise not already true of the implemented system.
4. **Given** a newcomer who has read this page, **When** asked whether Bindle is "stateless," **Then** they can correctly answer that Bindle is stateless with respect to user history/knowledge/transcripts but durably owns bounded, repository-local coordination state — not a simple yes or no.

---

### User Story 4 - Deeper reference material is reachable, not duplicated (Priority: P2)

From a documentation landing page, a newcomer or maintainer can navigate to the existing deeper architecture documents (`docs/PHILOSOPHY.md`, `docs/SCOPE.md`, `docs/DATA-OWNERSHIP.md`, `docs/SYMPHONY.md`, `docs/WORKTREES.md`, `docs/DECISIONS.md`) without those documents' substantive content being copied onto the new site.

**Why this priority**: Valuable completeness once Stories 1–3 exist, but a newcomer already gets the core comprehension outcome from Stories 1–3 without this; this story makes the deeper material discoverable rather than newly comprehensible.

**Independent Test**: Starting from the documentation landing page, confirm every one of this repository's existing canonical architecture documents is reachable within a small, bounded number of navigation steps, and confirm no page on the new site restates more than a brief pointer-level summary of any of them.

**Acceptance Scenarios**:

1. **Given** the documentation landing page, **When** a reader looks for deeper material on a specific concept (e.g., worktree identity, evidence pointers, Symphony's scope boundary), **Then** they find a link to the existing canonical document rather than a second, parallel explanation.
2. **Given** any existing `docs/*.md` file that already explains its subject well, **When** this feature is implemented, **Then** that file's substantive content is not duplicated onto the new site — only linked to.
3. **Given** `docs/DECISIONS.md`, **When** a reader follows a link to it from the new site, **Then** it remains reachable as historical reference but is not presented as required onboarding reading.

---

### User Story 5 - The documentation build is mechanically verifiable (Priority: P2)

A maintainer can verify, locally and without network access to an external hosting provider, that the documentation site builds successfully and that a broken internal link or missing navigation target fails the build rather than shipping silently broken output.

**Why this priority**: Protects the truthfulness established by Stories 1–3 over time — without mechanical verification, the site can drift back into the same kind of staleness this feature exists to fix. Ranked below the comprehension stories because it is a regression-prevention mechanism, not itself newcomer-facing content.

**Independent Test**: Build the documentation site locally; confirm it succeeds. Introduce a deliberately broken internal link or a reference to a nonexistent page; rebuild; confirm the build fails with a clear error rather than producing output.

**Acceptance Scenarios**:

1. **Given** a correctly cross-linked documentation source tree, **When** the site is built locally, **Then** the build succeeds without requiring network access to any external hosting provider.
2. **Given** a documentation source tree with one broken internal link or a navigation entry pointing at a nonexistent page, **When** the site is built, **Then** the build fails with a nonzero exit and an error identifying the broken reference.
3. **Given** the repository's canonical verification gate (`scripts/check.sh`) or an equivalent invoked step, **When** a maintainer runs it, **Then** the documentation build's success/failure is included in what gets verified before a PR is considered ready — the mechanism for wiring this in is a planning decision, but the outcome (docs build status is part of normal verification) is this story's requirement.

---

### User Story 6 - A static workflow diagram clarifies ownership at a glance (Priority: P3)

A newcomer looking at the "How Bindle Works" page sees one static diagram showing the relationship among Spec Kit, Bindle's coordination ledger, schedulable tasks, Symphony, execution harnesses, Git/GitHub evidence, milestone review, and human acceptance — reinforcing, not replacing, the prose explanation from User Story 3.

**Why this priority**: A genuine comprehension aid, but User Story 3's prose already carries the required outcome on its own; this is a polish increment addable or removable without changing what a newcomer can correctly conclude.

**Independent Test**: Show the diagram alone (no surrounding prose) to a newcomer; confirm it does not, by itself, suggest Bindle performs execution, owns Git/GitHub history, owns provider knowledge, or automates human milestone acceptance.

**Acceptance Scenarios**:

1. **Given** the diagram, **When** a newcomer reads it, **Then** every box or arrow in it corresponds to a fact stated in User Story 3's prose — the diagram introduces no ownership claim the prose does not already make.
2. **Given** the diagram, **When** it depicts Symphony and execution harnesses, **Then** it visually distinguishes them from Bindle's own coordination-ledger boxes, rather than implying Bindle performs or supervises execution.
3. **Given** the diagram, **When** it depicts milestone review, **Then** it shows the accept/decline decision as a distinct, human-attributed step, not an automated output of readiness.

---

### Considered and Declined — Live/Operational Documentation Surface

A live, dynamic rendering of any specific repository's current coordination-ledger state — dispatchable tasks, claims, forecast, milestone readiness — served through the documentation site or a related surface, optionally enriched with Symphony's own live runtime facts, was considered while scoping this feature and is explicitly declined.

This is materially the same shape of capability `docs/DECISIONS.md` D045 already evaluated and declined as `bindle view`: a local operational surface over live Bindle work-item state, declined because no repeated, observed friction demonstrated a need for it once `bindle work status`/`--json`/`--watch` and `bindle work forecast` already existed as CLI/JSON/NDJSON interfaces. Building it into a "documentation site" instead of a `bindle view` command would not change its nature — it would still be a live, per-repository operational view, not general-audience static documentation. This specification's public documentation site is static, build-time-generated content describing the *system* (architecture, concepts, commands), never a live read of *a* repository's ledger. Non-Goals and FR-013/FR-014 below make this boundary an explicit requirement, not merely a stated intent — see also Success Criteria SC-006.

### Edge Cases

- **Stale example output**: a documented command's example output no longer matches real CLI output after a future code change. Mitigated by User Story 5's build verification only for links/navigation, not output drift — output-drift detection is out of scope for this feature and is named as a known residual risk in Assumptions, not solved here.
- **A newcomer follows the getting-started path against a repository that already has Bindle initialized** (an existing `.bindle-work/` ledger with real work items) rather than a fresh disposable one: the path's own instructions must make clear it is meant to be followed in a disposable/scratch repository, since `bindle init` and the loader are safe to rerun (idempotent, per D039/D043/D044) but a newcomer should not be misled into thinking they are meant to experiment against a repository with real coordination state.
- **A newcomer only reads README.md and stops there**: README.md alone (post–User-Story-1) must not itself claim ownership boundaries it cannot fully explain in a few paragraphs — it must correctly summarize and then point onward (User Story 4), rather than trying to be self-sufficient.
- **A reader compares the new site against `docs/DECISIONS.md`'s D045 and concludes the project is inconsistent** (declined a local visual surface, then built a "documentation site"): the "Considered and Declined" section above and this feature's Non-Goals exist specifically to make the distinction explicit and citable, so this apparent contradiction is addressed by the specification itself rather than left for a reader to puzzle out.
- **The repository is private and the documentation site is meant to be "public"**: this specification requires the site to be *buildable and deployable to a conventional static host*; it does not require the repository to actually be made public or Pages to actually be enabled during this feature — see Assumptions and Deferred Questions.
- **A future reader tries to use the documentation site itself as a way to check a specific repository's current work state**: the site must not support this (Non-Goals, FR-013) — a reader who wants that already has `bindle work status`/`--json`/`--watch`/`forecast` and `bindle milestone review`/`list`.
- **An existing document (e.g. `docs/SYMPHONY.md`) already correctly states a nuance the new site would otherwise oversimplify** (e.g., the FR-017 admission-vs-continuation gate, D040's scheduler-granularity resolution): the newcomer-facing pages must stay at the newcomer level of detail and link to the existing document for that nuance rather than restating or, worse, incorrectly simplifying it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The public documentation surface MUST state, within the primary reading path (README entry point plus the "How Bindle Works" page), that Bindle durably owns bounded, repository-local coordination state (work-item status, blocking, claims, and evidence pointers) in addition to configuration/cache/export, correcting the incomplete "Bindle-owned state" framing identified in Grounding.
- **FR-002**: The public documentation surface MUST NOT describe any currently-implemented capability — including `bindle work status`, `bindle work forecast`, `bindle work load-speckit`/`publish`/`claim`/`release`/`done`, `bindle milestone review`/`list`/`enter-review`/`claim`/`release`/`accept`/`decline`, the Symphony projection, or the Symphony-side Tracker adapter — as future work, a placeholder, or not-yet-built.
- **FR-003**: Every command shown in the Getting Started or "How Bindle Works" pages MUST be a real, currently-implemented `bindle` command whose documented behavior is verified by direct execution before publication, not merely asserted; interface-only stub commands (`bindle list`, `update`, `upgrade`, `doctor`) MUST NOT be presented as functional in newcomer-facing material.
- **FR-004**: The Getting Started path MUST describe the actual current installation/execution path (a cloned development checkout run via `uv run bindle ...`) and MUST NOT imply a published, installable package exists unless and until one actually does.
- **FR-005**: The Getting Started path MUST let a newcomer exercise `bindle init`, loading a Spec Kit feature's tasks into the ledger, and `bindle work status`/`forecast` against a disposable local repository, entirely without installing, configuring, or running Symphony.
- **FR-006**: Symphony MUST be introduced in the documentation as an optional, independently-run external coordinator (per `docs/SYMPHONY.md`'s "referenced, never vendored" framing), positioned in advanced/reference material rather than as a Getting Started prerequisite.
- **FR-007**: The documentation site MUST provide, from a landing/entry page, a discoverable navigation path to each existing deeper architecture document (`docs/PHILOSOPHY.md`, `docs/SCOPE.md`, `docs/DATA-OWNERSHIP.md`, `docs/SYMPHONY.md`, `docs/WORKTREES.md`, `docs/PRIVACY.md`, `docs/TOOLCHAIN.md`, `docs/DECISIONS.md`).
- **FR-008**: The documentation site MUST NOT duplicate the substantive content of an existing canonical document merely to populate the site; where a concept is already well-explained in an existing document, new pages MUST link to it rather than restate it.
- **FR-009**: `docs/DECISIONS.md` MUST remain a historical, append-only record, unedited and unrestructured by this feature; the documentation site MUST NOT require it as reading to understand the primary spec-to-milestone-review workflow.
- **FR-010**: The "How Bindle Works" page MUST explicitly distinguish Bindle-owned repository-local coordination state from provider-owned state Bindle does not own (Git/GitHub history, execution-harness transcripts, project/personal knowledge), reconciling the "stateless toolchain bridge" framing per Grounding rather than repeating it unqualified.
- **FR-011**: The documentation site MUST be buildable and verifiable locally, and as part of the repository's normal verification path, without requiring network access to an external hosting provider.
- **FR-012**: The documentation site build MUST fail with a nonzero exit when it references an internal link, navigation entry, or included document that does not exist.
- **FR-013**: The documentation site MUST remain static, build-time-generated content; it MUST NOT present live or current Bindle work-item state (ledger contents, claim status, dispatchable tasks, forecast, or milestone review-readiness) for any specific repository, and MUST NOT read any repository's `.bindle-work/*.sqlite3` file at request time.
- **FR-014**: The documentation site MUST NOT introduce a backend server process, a database, or an authentication mechanism — it is static output only, consistent with FR-013 and with `docs/DECISIONS.md` D045's declined `bindle view`.
- **FR-015**: The documentation site MAY include a static conceptual diagram illustrating the relationship among Spec Kit, the coordination ledger, schedulable tasks, Symphony, execution harnesses, Git/GitHub evidence, milestone review, and human acceptance, provided the diagram does not imply Bindle performs execution, owns Git/GitHub history, owns provider knowledge, or automates human milestone acceptance.
- **FR-016**: README.md MUST be reduced to a concise entry point — what Bindle currently is, in terms consistent with FR-001/FR-010, and where to go next — rather than remaining the primary location where the full ownership/architecture explanation lives.
- **FR-017**: All documentation content introduced or modified by this feature MUST use synthetic or already-public example values and MUST NOT include personal absolute paths, vault names/paths, or other material `docs/PRIVACY.md`'s repository content rules prohibit.

### Key Entities *(include if feature involves data)*

- **Documentation Site**: the static, build-time-generated public documentation output (landing page, Getting Started, "How Bindle Works," navigation to reference documentation). Not a stored or persisted entity in Bindle's own sense — derived and rebuildable from tracked Markdown, mirroring the "derived and rebuildable" precedent already established for QMD's index (D036); deleting and rebuilding it loses nothing.
- **Getting Started Walkthrough**: the specific, execution-verified command sequence (`bindle init` → load a Spec Kit feature's tasks → `bindle work status`/`forecast`) a newcomer follows locally. Documentation content only; produces no new Bindle-owned state beyond the ordinary disposable ledger a newcomer's own scratch repository already gets from running `bindle init`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A newcomer who has read only the primary documentation path (README entry point → Getting Started → "How Bindle Works") can correctly state, without having opened `docs/DECISIONS.md`: (a) what state Bindle durably owns, (b) what it explicitly does not own, (c) Symphony's role, and (d) that milestone acceptance is a human decision — verified by a comprehension check against a reader unfamiliar with the repository.
- **SC-002**: 100% of commands shown in the Getting Started and "How Bindle Works" pages, when run verbatim against a fresh local repository, produce output consistent with what is documented — verified by direct execution of every documented command before publication.
- **SC-003**: Zero implemented capabilities (`bindle work status`/`forecast`, `bindle milestone` review lifecycle, the Spec Kit loader, the Symphony projection) are described as future, planned, or unimplemented anywhere in the public documentation surface — verified by review against FR-002.
- **SC-004**: The documentation site build completes successfully on a correct source tree and fails with a nonzero exit when a deliberately broken internal link or missing navigation target is introduced — verified by both a positive and a negative build test.
- **SC-005**: `docs/DECISIONS.md`'s existing entries are byte-identical before and after this feature's implementation — verified by diff; only a new entry recording this feature's own adoption, appended per this repository's normal decision-log convention, is expected.
- **SC-006**: The built documentation site contains no code path that opens, queries, or otherwise reads any repository's `.bindle-work/*.sqlite3` file, starts a server process, or requires authentication — verified by inspection of the build output and its source.
- **SC-007**: A reviewer comparing the public documentation surface against `docs/DECISIONS.md` D038, D039, D041, D042, D045, and D046 finds no contradiction — verified by an explicit reconciliation review pass before this feature is considered complete.
- **SC-008**: After this feature is implemented, the full ownership/architecture explanation is reachable within one navigation step from the documentation landing page, and README.md itself no longer carries that full explanation as its primary content — verified by direct comparison of README.md's content before and after.

## Assumptions

- **Framework selection is deferred to planning.** This specification states required externally-visible behavior (static, locally buildable, uses repository-owned Markdown as source, navigable, deployable to a conventional static host such as GitHub Pages) and does not select a static-site generator. A lightweight, Python-friendly generator (for example, Zensical) is a plausible planning-stage candidate given this repository's existing Python/`uv` toolchain and Markdown-first `docs/` convention, but this is not a requirement of this specification.
- **No published Bindle package exists yet**, and this feature does not create one; the Getting Started path assumes a cloned development checkout, consistent with `AGENTS.md`'s existing `uv run bindle ...` convention for development use.
- **The repository is currently private on GitHub.** Free GitHub Pages hosting from a private repository has platform-level prerequisites (a paid plan, or making the repository public) this specification does not resolve or require; "deployable to a conventional static host" is specified as a build-output capability, not as an instruction to change the repository's visibility or actually enable Pages during this feature.
- **This feature does not answer PLAN.md's open item 6** ("the next vertical slice is not yet chosen"). It is treated as an orthogonal communication/reconciliation slice — improving truthfulness and navigability of existing, already-adopted product surface — not as a new coordination capability or an implicit answer to that open question.
- **Output-drift detection (example command output going stale after a future code change) is a known residual risk this feature does not fully close.** User Story 5 verifies link/navigation integrity mechanically; keeping documented example *output* current after future CLI changes remains a review discipline, not an automated check, unless a future feature adds one.
- **This specification does not mandate exactly how much of README.md/`docs/SCOPE.md`/`docs/DATA-OWNERSHIP.md`/`docs/PHILOSOPHY.md` text is edited versus left alone beyond the specific Grounding findings and User Story 1's acceptance scenarios** — planning determines the precise diff, guided by "reconcile identified gaps, do not rewrite for its own sake."

## Deferred to Planning / Research

- Concrete static-site generator selection and its configuration.
- Exact information architecture beyond the minimal Home / Getting Started / How Bindle Works / reference-navigation path — whether any additional top-level page is warranted.
- How the documentation build is wired into `scripts/check.sh` versus a separate, referenced script (User Story 5 requires the outcome, not the mechanism).
- Whether and when to actually make the repository public and enable GitHub Pages (or another static host) — an operator decision outside this feature's scope.
- The precise wording diff for README.md/`docs/SCOPE.md`/`docs/DATA-OWNERSHIP.md`/`docs/PHILOSOPHY.md` beyond the specific gaps identified in Grounding.
- Whether a documented, repeatable check for output-drift (documented example output vs. real current CLI output) is worth adding, and if so, how.
