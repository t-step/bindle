# QMD retrieval integration

## Outcome

`bindle init --qmd` gives a repository the smallest useful opt-in onto local retrieval over its own durable Markdown, via the native `tobi/qmd` (`@tobilu/qmd`) CLI — the first concrete instance of docs/SCOPE.md's M4 ("derived indexing experiment"). `bindle status` reports read-only adoption state; `bindle remove` never touches it.

## Why now

PLAN.md's M1 (evidence emission) had not yet started, but M4 was explicitly named in docs/SCOPE.md as a milestone worth a deliberate, bounded evaluation. This work was scoped directly (branch `feat/qmd-retrieval`, base `main`) rather than waiting on M1, on explicit instruction — it does not depend on evidence emission and does not touch Symphony/coordination work being explored on other branches.

## Scope

In scope: repository-local opt-in (`bindle init --qmd`), read-only detection (`bindle status`), a fixed collection over root/`docs/`/`plans/` Markdown, BM25 search verified end-to-end. Explicitly out of scope (see docs/DECISIONS.md D036 for the full list): a `bindle search` wrapper, embeddings/vector orchestration, Projectmem→QMD promotion, QMD's MCP server, and any agent-prompt retrieval wiring.

## Evidence

### Repository grounding (read before designing)

PLAN.md, docs/SCOPE.md, docs/DECISIONS.md (through D035), docs/WORKTREES.md, docs/TOOLCHAIN.md, docs/PHILOSOPHY.md, docs/DATA-OWNERSHIP.md, AGENTS.md, and the existing provider-lifecycle seams (`src/bindle/projectmem.py`, `src/bindle/skills/*.py`, `src/bindle/cli.py`, their tests) were read in full before any design decision. The skill-kit lifecycle (D035) and Projectmem seam (D033) are the two existing shapes this integration was measured against.

### Upstream verification

`tobi/qmd` / `@tobilu/qmd` confirmed as the correct project (distinct from an unrelated same-named `ehc-io/qmd`). Installed and inspected two versions directly (not from documentation alone):

* `qmd 2.5.3` — already on PATH on the development machine (installed independently, for the developer's own Obsidian vault retrieval — see below).
* `qmd 2.8.3` — installed via `npm install @tobilu/qmd` into a disposable scratch directory (never global), used for deeper investigation once a version discrepancy was found.

`--help` output is identical in command surface across both versions.

### The pre-existing global QMD state that shaped the collision-safety design

Before choosing a collection-naming scheme, the developer's actual global QMD state was inspected directly: `~/.config/qmd/bindle.yml` already registers a collection also named `bindle`, indexing a path under the developer's personal Obsidian vault (Bindle's own dedicated vault, per AGENTS.md's "Obsidian projection" section) — a completely different directory from this Git repository, on the same machine, sharing only the name. This is real, observed evidence that a naive "derive a global collection name from the repository" design would collide with real user state, not a hypothetical concern — it directly motivated using QMD's project-local mode (`.qmd/index.yml` inside the worktree) instead of any global-named-index scheme. (Personal absolute paths are not reproduced here — docs/PRIVACY.md.) See docs/DECISIONS.md D036.

### Two empirical failure modes found and fixed

1. **`qmd collection add` without a prior `qmd init` silently falls back to the global default index.** Discovered by accident during exploration: an early `collection add . --name repo ...` run (before a project-local `.qmd/` existed in that directory) created a real `~/.config/qmd/index.yml` on the development machine, registering a collection pointing at a scratch fixture path. Caught by diffing `~/.config/qmd/` and `~/.cache/qmd/` before/after each exploratory command; cleaned up immediately (`rm ~/.config/qmd/index.yml`, `rm ~/.cache/qmd/index.sqlite*`), confirmed against the pre-existing `bindle.yml`/`bindle.sqlite` md5 sums that nothing unrelated was touched. Fix: every mutating code path in `qmd.py`/`cli.py` runs `qmd init` unconditionally before ever running `collection add`.

2. **QMD resolves its project root from the `PWD` environment variable, not the process's actual cwd.** `subprocess.run(cmd, cwd=X)` changes the child's real working directory (confirmed via `os.getcwd()` inside the child) but does not set `PWD` — that is shell-only bookkeeping (`cd` performs it; Python's `subprocess` module does not). A `qmd init`/`collection add` child spawned this way silently resolved against a stale/inherited `PWD`, fell through to the global default index, and `qmd init` printed "ready to go with new local index" without ever creating `.qmd/` — a second, independent way to trip the exact same global-pollution hazard as failure mode 1, this time via `bindle init --qmd`'s own normal `subprocess.run(cwd=info.worktree_root)` calls, not exploratory shell commands. Root-caused with a minimal reproduction (bare `subprocess.run([qmd, "init"], cwd=X)`, no Bindle code involved) that isolated the variable to `PWD` specifically — setting `env["PWD"] = X` alongside `cwd=X` fixed it identically to running the same command from a shell already `cd`'d into `X`. Fix: `qmd.subprocess_env(worktree_root)`, used by every `qmd` invocation in `_apply_qmd`.

Both fixes are covered by dedicated tests (`tests/test_cli.py::TestInitQmdFlag` for the ordering; `TestInitQmdRealCli::test_real_qmd_init_never_creates_the_global_default_index` and the real end-to-end tests for the PWD fix, run against the real CLI).

### Collection mask version incompatibility

The comma-joined mask form QMD's own README shows first (`"*.md,docs/**/*.md,plans/**/*.md"`) silently matched **zero files** against the globally-installed `qmd 2.5.3`, while the identical mask matched correctly against `2.8.3`. The brace-form union (`"{*.md,docs/**/*.md,plans/**/*.md}"`) was verified to index the correct files, and only the correct files (confirmed a `src/**/*.md`-shaped decoy file was excluded), under both versions — this is what `qmd.COLLECTION_MASK` uses.

### Real disposable smoke test (the task's own required proof)

Run end-to-end via `tests/test_cli.py::TestInitQmdRealCli` (real `qmd` CLI, isolated via `QMD_CONFIG_DIR`/`XDG_CACHE_HOME` redirected to disposable temp directories, mirroring `TestInitProjectmemRealPjm`'s `PROJECTMEM_HOME` isolation):

* fresh fixture repository → `bindle init --qmd` → `.qmd/index.yml`/`index.sqlite` created, `detect_qmd` reports `ready`
* `qmd search` (BM25, no embeddings) correctly retrieves a uniquely-marked string from `docs/SCOPE.md` and from `plans/active/README.md`, and correctly excludes a decoy file outside `COLLECTION_MASK`
* a newly-added Markdown file is not found by `qmd search` until `qmd update` runs, then is found — the answer to "how does retrieval become fresh"
* re-running `bindle init --qmd` is idempotent (no second native invocation, `index.yml`'s mtime unchanged)
* `bindle remove` preserves the QMD collection and guardrail state independently
* `.qmd/` is added to the repository's `info/exclude` and never appears in `git status --porcelain` output
* no global default index (`<QMD_CONFIG_DIR>/index.yml`) is ever created

No embedding model was downloaded or exercised by any test in this slice — `qmd search` alone was sufficient to prove retrieval works, matching the brief's "BM25 first, no model downloads" requirement.

## Work

* `src/bindle/qmd.py` — detection (`detect_qmd`, four states), native-CLI argument builders (`QMD_INIT_ARGS`, `collection_add_args`), `qmd_executable()`, `subprocess_env()` (the PWD fix), `ensure_gitignored()` (a follow-up: adds `.qmd/` to the repository's machine-local `info/exclude` so it never shows up as untracked clutter — added once QMD is initialized, idempotent, never touches the tracked `.gitignore`, no-op if `.qmd/` is already tracked or already ignored some other way).
* `src/bindle/cli.py` — `--qmd` flag on `init` (composes with `--projectmem`), `_qmd_init_preflight`/`_apply_qmd`, a `QMD` row on `bindle status`, a preserved-on-`remove` note. The existing `--projectmem` mutation logic was extracted into `_apply_projectmem` (behavior-preserving refactor, verified against the full pre-existing test suite) so both opt-ins compose through the same preflight-then-mutate structure.
* `tests/test_qmd.py` — detection/parsing unit tests, real-fixture based (no `qmd` CLI dependency), mirroring `tests/test_projectmem.py`'s structure.
* `tests/test_cli.py` — `TestInitQmdFlag` (mocked, mirrors `TestInitProjectmemFlag`), `TestInitQmdRealCli` (real CLI, skipped when `qmd` isn't installed, mirrors `TestInitProjectmemRealPjm`), plus `QMD` rows added to `TestStatusCommand`.
* `docs/DECISIONS.md` (D036), `docs/TOOLCHAIN.md`, `AGENTS.md`, `PLAN.md` — documentation of the adopted shape, explicit non-goals, and verified findings.

## Verification

* `python3 -m unittest discover -s tests -t .` — 257 tests, all passing, run twice consecutively with no state leakage.
* `bash scripts/check.sh` — all checks pass, including the full unit test suite, shellcheck, and the decision-reference consistency check (D036 resolves).
* Real `qmd` CLI smoke tests (`TestInitQmdRealCli`, 5 tests) pass against the actually-installed 2.5.3 binary.
* The developer's pre-existing global QMD state (`~/.config/qmd/bindle.yml`, `~/.cache/qmd/bindle.sqlite`) was confirmed byte-identical (md5) before and after every phase of this work, including the accidental pollution incident (cleaned up immediately) and the full automated test suite (run twice).

## Decisions

See docs/DECISIONS.md D036 for the full, itemized record (collection scope, worktree identity, installation expectation, ownership semantics, required-vs-optional retrieval modes, refresh behavior, removal behavior, relationship to Projectmem, independence from Symphony).

## Open questions

* Whether a tiny `bindle search`/`bindle query` wrapper ever earns its place — deferred; native `qmd search`/`qmd query` was judged sufficient for this slice, no evidence yet that a wrapper improves usability.
* Whether `bindle remove` should eventually gain a scoped `qmd collection remove repo` step once ownership-record bookkeeping (mirroring the skill kits' worktree-scoped marker) is judged worth the added complexity for a rebuildable index — deferred, conservatism preferred for a first integration.
* Whether repository-wide refresh friction (having to remember to run `qmd update`) proves real enough to justify a git-hook-based refresh later — no evidence yet either way.

## Showcase evidence

* Real end-to-end BM25 retrieval verified against a fixture reproducing this repository's own Markdown layout (see "Real disposable smoke test" above) — the concrete proof that `bindle init --qmd` followed by `qmd search` works.
* Two independently-discovered, verified, and fixed correctness bugs (global-index fallback without `qmd init`; `PWD`-vs-`cwd` resolution) that would otherwise have made `bindle init --qmd` intermittently or silently write into the user's real global QMD state — the exact failure category this slice's brief was most concerned about.
