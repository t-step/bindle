# Quickstart: Validating the Public Documentation Site

These are the runnable checks a maintainer performs once this feature is implemented. Each walkthrough traces to a User Story in `spec.md` and doubles as the shape of the `/speckit.tasks` verification tasks for that story. None of these commands exist yet as of this planning session — this quickstart documents what "done" looks like, to be run after implementation, not during planning.

## Prerequisites

- A checkout of this repository on the implementation branch, with `mkdocs.yml` and `docs/site/` (Research Decision 2/5) present.
- `uv` installed (already a repository baseline requirement).
- No network access required for any step below (FR-011) — if a step in your environment reaches out to the network, that is itself a defect against this feature's design.

## Walkthrough A — the site builds and validates (User Story 5)

```sh
uv run mkdocs build --strict --site-dir /tmp/bindle-docs-build
echo "exit: $?"
```

**Expected**: exit `0`, and `/tmp/bindle-docs-build/` contains a static site (an `index.html` at minimum) with no warnings about unresolved links or nav entries. ✅ traces to US5 Acceptance Scenario 1, SC-004 (positive case).

## Walkthrough B — a broken link fails the build (User Story 5)

```sh
# Introduce a deliberate breakage, run the same build, then revert.
cp docs/site/how-bindle-works.md /tmp/how-bindle-works.md.bak
printf '\n[broken](./does-not-exist.md)\n' >> docs/site/how-bindle-works.md
uv run mkdocs build --strict --site-dir /tmp/bindle-docs-build-broken
echo "exit: $?"
mv /tmp/how-bindle-works.md.bak docs/site/how-bindle-works.md
```

**Expected**: nonzero exit, with an error message identifying the broken reference (file and target). ✅ traces to US5 Acceptance Scenario 2, SC-004 (negative case).

## Walkthrough C — `scripts/check.sh` includes the docs build (User Story 5)

```sh
bash scripts/check.sh
```

**Expected**: output includes a section for the docs build (matching the file's own `section "..."` convention), and that section's pass/fail is reflected in the script's own final `fail` exit code — a broken docs build must make `scripts/check.sh` itself exit nonzero, exactly like every other section. ✅ traces to US5 Acceptance Scenario 3.

## Walkthrough D — a newcomer's real command sequence (User Story 2)

Run against a disposable local repository, entirely separate from this checkout:

```sh
mkdir -p /tmp/bindle-newcomer-demo && cd /tmp/bindle-newcomer-demo
git init
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <path-to-bindle-checkout> bindle init
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <path-to-bindle-checkout> bindle work load-speckit <path-to-bindle-checkout>/specs/005-work-state-visibility
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <path-to-bindle-checkout> bindle work status
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <path-to-bindle-checkout> bindle work status --json
BINDLE_HOME="$PWD/.bindle-dev" uv run --project <path-to-bindle-checkout> bindle work forecast
```

**Expected**: `bindle init` reports the guardrail layer plus `SQLite work ledger: ready` / `Symphony projection: ready` (D043); `bindle work status` shows dispatchable and blocked work items sourced from `specs/005-work-state-visibility/tasks.md`'s real task graph; `bindle work status --json` emits the documented `contracts/work-status-json-v1.md` shape; `bindle work forecast` shows a dependency frontier. No step installs, configures, or starts Symphony. ✅ traces to US2 Acceptance Scenarios 1–4, and is the exact verification FR-003 requires before this walkthrough's text is published on the Getting Started page — run this command-by-command and capture real output before writing the page, not after.

## Walkthrough E — reconciled documents state the coordination-ledger fact (User Story 1)

Read (not run):

- `README.md` — confirm it now names the coordination ledger as durably owned, alongside its existing, unchanged claim about not owning user history/transcripts.
- `docs/SCOPE.md`'s "Bindle-owned state" section — confirm a coordination-ledger category is present, citing D038.
- `docs/DATA-OWNERSHIP.md`'s ownership table — confirm a row exists for the coordination ledger/work items, distinct from "Evidence pointers" and "Bindle runtime state."
- `docs/TOOLCHAIN.md`'s "Documentation and web" table — confirm a row exists for MkDocs, state Adopted.
- `docs/DECISIONS.md` — confirm it is byte-identical for every pre-existing entry (`git diff` against the pre-implementation commit, restricted to existing entries) except for a permitted new appended entry.

**Expected**: all five checks pass. ✅ traces to US1 Acceptance Scenarios 1–3 and 5, SC-005, and the 2026-08-29 `docs/TOOLCHAIN.md` decision.

## Walkthrough G — canonical docs render directly, with no duplicated content (User Story 4)

```sh
uv run mkdocs build --strict --site-dir /tmp/bindle-docs-build
ls /tmp/bindle-docs-build/PHILOSOPHY /tmp/bindle-docs-build/SCOPE /tmp/bindle-docs-build/DATA-OWNERSHIP \
   /tmp/bindle-docs-build/SYMPHONY /tmp/bindle-docs-build/WORKTREES /tmp/bindle-docs-build/PRIVACY \
   /tmp/bindle-docs-build/TOOLCHAIN /tmp/bindle-docs-build/DECISIONS
```

**Expected**: each existing canonical document has a corresponding built page (exact output-path shape depends on final `mkdocs.yml` `use_directory_urls` setting — adjust the paths above to match once `mkdocs.yml` exists; the point of this check is that all eight are reachable from the built site, not the literal path form). Separately, confirm by inspection that no `docs/site/*.md` page contains more than a brief pointer-level summary of any of these eight documents' substantive content (FR-008). ✅ traces to US4 Acceptance Scenarios 1–2.

## Walkthrough F — comprehension check (User Story 3)

Give a reader unfamiliar with this repository only the "How Bindle Works" page (plus the README entry point). Ask them:

1. What does Bindle durably own?
2. What does Bindle explicitly not own or do?
3. What is Symphony's role?
4. Who decides whether a milestone is accepted?
5. Is Bindle "stateless"?

**Expected**: answers matching spec.md's Grounding section and FR-010; question 5's answer distinguishes "stateless with respect to user history/knowledge/transcripts" from "owns bounded, repository-local coordination state" rather than a plain yes/no. ✅ traces to US3 Acceptance Scenarios 1–4, SC-001, SC-007.
