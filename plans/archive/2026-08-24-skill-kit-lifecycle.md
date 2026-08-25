# Skill-kit lifecycle

Date: 2026-08-24. Status: **implemented, including a final correctness pass (worktree-scoped Codex ownership, content-digest-verified removal, truthful provider-error/missing-CLI reporting, Python 3.14 argparse compatibility) — `python3 -m unittest discover -s tests -t .` (206 tests) and `bash scripts/check.sh` both pass cleanly with no exceptions; ready for review before merge.**

## Outcome

Add `bindle skills list|status|add|remove`: the third product-lifecycle
seam alongside repo-local guardrails (D031/D032) and Projectmem (D033).
A skill kit is a named collection of agent-facing skills/capabilities
Bindle makes available to Claude Code and Codex through each harness's
own native mechanism. Two kits ship this slice: `software-engineering`
(source `t-step/skills`) and `spec-kit` (source `github/spec-kit`).

Full architecture-level rationale is recorded in `docs/DECISIONS.md` D035;
this document is the investigation trail and verification evidence behind
it.

## Why now

The user explicitly wants to be able to add and remove skill kits
generally, and expects this area to evolve — the third differently-shaped
provider-lifecycle specimen D033 predicted might justify revisiting
whether shared structure is warranted. It didn't: two kits confirmed the
divergence pattern D033 already found (one Bindle-owned/symmetric
integration, one provider-owned/asymmetric integration) rather than
resolving it, and this slice adds a third shape again (a materialized,
ownership-tracked projection with no native provider lifecycle at all —
Codex skills). The smallest durable model that supports "add/remove kits
generally" without becoming a package manager is a small catalog +
kit-specific modules, not a generic Component/Provider framework.

## Scope

**In scope:**
- `bindle skills list|status|add|remove` CLI surface.
- `bindle.toml`'s `[skills].kits` array as repository-owned desired state.
- `software-engineering` kit: Claude via native marketplace/plugin CLI
  (project scope); Codex via Bindle-materialized `.agents/skills/*` from
  a fresh `t-step/skills` clone, with a minimal ownership marker for safe
  removal.
- `spec-kit` kit: both harnesses via the native `specify` CLI end-to-end
  (`specify init`/`specify integration install|uninstall|status`).
- `docs/DECISIONS.md` D035, this plan, `PLAN.md` re-sequencing.

**Out of scope (see D035 and AGENTS.md's explicit non-goals list):**
arbitrary third-party kit URLs, a remote catalog service, a semver
solver, a lockfile, transitive/nested/composite kits, an `fde` meta-kit,
automatic updates, `bindle update`/`upgrade`, `bindle init`/`bindle
remove` skill reconciliation, fleet-wide management, a generic package
manager, a generic Component abstraction, Symphony integration,
Projectmem changes, and any modification to `t-step/skills` or
`github/spec-kit` themselves.

## Investigation (native surfaces, verified this session)

Four parallel investigations, each against the actually-installed tooling
and live repositories, not memory:

**Claude Code (2.1.243).** `claude plugin install --scope {user,project,local}`:
`project` writes the repository's own tracked `.claude/settings.json`
(`enabledPlugins`); `local` writes the gitignored-by-convention
`.claude/settings.local.json`; `user` writes `~/.claude/settings.json`.
Marketplace registration (`claude plugin marketplace add <source>`) is
always user-level — no per-project marketplace scope exists, confirmed
via `CLAUDE_CONFIG_DIR`-isolated testing (add marketplace, install/
uninstall at each scope, inspect every file written, all in a throwaway
`/tmp` config dir). `claude plugin list --json` and direct
`enabledPlugins` reads are both stable, documented read interfaces.

**Codex (0.146.0).** No `codex skills` CLI exists. Skills are pure
file-based: repo-local `.agents/skills/<name>/SKILL.md` (a cross-vendor
convention — also used by Spec Kit's own Codex integration, and by
`.agents/plugins/marketplace.json` for the separate `codex plugin`
mechanism), scanned from CWD up to repo root. `codex plugin` is a
distinct, broader mechanism (marketplace-distributed bundles of
skills+hooks+MCP+apps) — evaluated and rejected as the vehicle for a
plain skill kit; it is not simply "skills with extra steps." The
underlying `SKILL.md` format is the shared, open Agent Skills standard —
confirmed a plain Claude-Code-style SKILL.md (name+description
frontmatter, markdown body) works unmodified in Codex.

**`t-step/skills` (live `main`, read-only via `gh api`).**
`plugins/software-engineering/.claude-plugin/plugin.json`: name
`software-engineering`, version `0.1.2` (confirmed live, not assumed
stale). Marketplace `t-step-skills`. Exactly 4 skills under
`plugins/software-engineering/skills/`: `next-best-slice`,
`repo-orientation`, `slice-plan`, `slice-review` — each directory
contains only a `SKILL.md` file, no supporting scripts/hooks/MCP config,
confirmed fully portable to Codex as-is. Development-only material lives
on a separate `development` branch per the repo's own README; `main`
only ever contains what's safe to install.

**Spec Kit (`specify-cli` 1.0.1).** `specify integration
install|uninstall|status|list` is a full native lifecycle CLI —
`specify integration status --json` returns a stable
`installed_integrations` list. Verified empirically, against a
**realistic pre-populated repository snapshot** (a full copy of this
repository's own tracked files, including its own `.gitignore` and
`AGENTS.md`, not an empty scratch directory) that `specify init --here
--force --non-interactive --integration claude --script sh` only ever
adds new untracked `.claude/`/`.specify/` paths — every pre-existing
tracked file's sha1 was confirmed byte-identical before and after.
`specify integration install codex` afterward coexists cleanly (adds
`.agents/skills/speckit-*`, shares `.specify/` infrastructure without
re-touching it). `specify integration uninstall <key>` removes exactly
that integration's own tracked-manifest files, confirmed via a
deliberately-modified file surviving uninstall untouched (matching its
own "safely preserving modified files" documentation) and via sha1
comparison that unrelated repository files never moved. Re-running
install on an already-installed key is a documented, verified no-op.
`specify bundle` was inspected directly (`bundle info --json` on a real
community bundle) and found to compose Spec Kit's own primitive types
(extensions/presets/steps/workflows) — rejected as a generic
distribution mechanism for this slice's purposes.

**A genuine, unplanned finding**, discovered while writing the
`spec-kit` test suite: `specify`'s own output (`.specify/`,
`.claude/skills/speckit-*`, `.agents/skills/speckit-*`) is created
**untracked** by default. Since untracked content is worktree-local
(docs/WORKTREES.md), spec-kit adoption does not automatically propagate
to a linked worktree unless the repository itself commits these paths —
verified by running `sk.add()` in a main checkout, then confirming
`sk.status()` correctly reports `not-installed` from a freshly created
linked worktree, and that adding independently from the worktree works.
The Codex materialization for `software-engineering` has the identical
worktree-local property, verified the same way with a synthetic fixture.

## Work

- `src/bindle/skills/config.py` — `bindle.toml` desired-state
  read/targeted-write (stdlib `tomllib` + line-level patch, no new
  dependency).
- `src/bindle/skills/catalog.py` — the two-entry catalog + per-kit module
  dispatch, `UnknownKitError`.
- `src/bindle/skills/types.py` — `KitStatus`/`KitOpOutcome`, the only
  shared shapes across kit modules.
- `src/bindle/skills/software_engineering.py` — Claude (native
  marketplace+plugin CLI, project scope) and Codex (materialization +
  worktree-scoped ownership marker at `repo_info.git_dir` + reconciled
  `info/exclude` bookkeeping across every live worktree's marker +
  content-digest-verified removal).
- `src/bindle/skills/spec_kit.py` — thin, exact wrapper over `specify
  init`/`integration install|uninstall|status`; never reimplements Spec
  Kit's own installer. Provider errors (a missing `specify` binary, or
  `integration status` failing/returning unparseable output) are
  distinguished from genuine absence.
- `src/bindle/cli.py` — `skills list|status|add|remove` subcommands;
  `_BindleArgumentParser` forces off Python 3.14's new default colorized
  `--help` output (a compatibility fix, unrelated to the skill-kit model
  itself).
- `docs/DECISIONS.md` D035, this plan, `PLAN.md`.

## Final correctness pass

A follow-up review before merge found several correctness gaps in the
first implementation, all fixed in this same branch/commit rather than a
follow-up PR:

1. **Codex ownership was repository-scoped, not worktree-scoped.** The
   marker lived at `git_common_dir` even though the materialized files
   themselves are worktree-local — two linked worktrees materializing the
   kit shared one ownership record, so one worktree's `remove()` could
   delete the only ownership evidence for another worktree's still-present
   files. Fixed: the marker now lives at `repo_info.git_dir`
   (`<git-common-dir>/worktrees/<id>` for a linked worktree — a directory
   Git itself tears down when the worktree is removed), giving every
   worktree independent, self-cleaning ownership evidence. Verified with a
   real linked-worktree fixture: add in main, add independently in the
   linked worktree, both report `installed` with independent markers,
   remove in the linked worktree, main remains `installed` with its
   ownership intact, main can then remove its own projection safely.
2. **`info/exclude` needed reconciliation, not per-worktree ownership.**
   Since the ignore file genuinely is shared Git state, `add()`/`remove()`
   now recompute the required ignore lines from the union of every live
   worktree's marker (found by walking `git_common_dir/worktrees/*`) and
   rewrite exactly one delimited, mechanically-owned block to match —
   every other line, including a pre-existing identical foreign entry, is
   left untouched. One worktree removing the kit only strips the lines no
   remaining worktree still needs.
3. **Removal ownership required only a remembered directory name, not
   proof of unmodified content.** A user-modified or replaced materialized
   skill would have been silently `shutil.rmtree()`'d. Fixed: each marker
   entry now pairs a skill name with a deterministic content digest
   (sha256 over a sorted relative-path+content-hash manifest) computed at
   materialization time; `remove()` only deletes a directory whose current
   digest still matches, preserves anything modified/replaced/foreign
   byte-for-byte, reports it as a conflict, and retains its ownership
   evidence in the marker for a safe retry after manual resolution.
   `status()` reports `conflict` for the same predicate.
4. **Spec Kit provider errors collapsed into `not-installed`.**
   `_installed_integrations()` returned an empty set on any command
   failure or unparseable output, indistinguishable from "genuinely zero
   installed." Fixed to return `None` for genuine failures, propagated as
   `unavailable`. A real, verified nuance surfaced while fixing this: once
   every integration is removed, `specify integration status --json`
   exits 1 (`.specify/integration.json` missing) while still emitting a
   well-formed `"installed_integrations": []` — trusting that valid JSON
   body regardless of exit code is *more* truthful than exit-code gating
   would have been, not less, so `_installed_integrations()` parses first
   and only falls back to `None` on genuinely unparseable output.
5. **Remove could report success it didn't actually perform.** Both
   `software-engineering`'s Claude harness and `spec-kit` could report
   "nothing to remove" / `unavailable` with `ok=True` purely because the
   required CLI (`claude`/`specify`) was missing, even when local
   configuration objectively showed the projection still installed. Fixed:
   removal is now a clean no-op only when the projection is objectively
   already absent; if configuration/`.specify/` shows it present but the
   CLI needed to detach it safely is unavailable (or, for spec-kit, the
   status query itself fails), `remove()` returns `ok=False` and leaves
   everything untouched rather than claiming success.
6. **Python 3.14 made `argparse` colorize `--help` output by default**,
   breaking 8 pre-existing help-surface tests (confirmed identical on
   unmodified `main`, unrelated to the skill-kit model). Fixed with a
   `_BindleArgumentParser` subclass that forces `color = False` when the
   attribute exists (a no-op on Python 3.11-3.13, where it doesn't) —
   `add_subparsers()`'s `parser_class` default (`type(self)`) propagates
   this to every subparser and nested subparser, verified both
   behaviorally (no ANSI escapes anywhere, even under `PYTHON_COLORS=1`
   forcing color on) and structurally (every subparser instance actually
   is `_BindleArgumentParser`).

## Verification

- `python3 -m unittest discover -s tests -t .` — **206 tests, all pass**,
  no exceptions. (Earlier in this branch's history, 180 tests passed with
  8 pre-existing, unrelated Python 3.14 argparse-color failures also
  present on unmodified `main`; the final correctness pass above fixed
  those too, so the qualification no longer applies.)
- `bash scripts/check.sh` — **all sections pass cleanly.**
- `git diff --check` — clean.
- Manual end-to-end smoke test in a disposable `/tmp` scratch repository
  against the **real** `claude`, `git`, and `specify` CLIs: `skills add
  software-engineering` (Claude installed via real marketplace+plugin
  flow, Codex materialized 4 real skills from a live clone), `skills add
  spec-kit` (bootstrapped `.specify/`, installed both harnesses), `skills
  status` (correct per-harness/per-kit reporting), idempotent re-add,
  `skills remove software-engineering` (removed only its own 4 Codex
  skill directories, left spec-kit's 10 `speckit-*` directories
  untouched, cleaned exactly its own `info/exclude` lines, left the
  Claude marketplace registered), `skills remove spec-kit` (removed both
  integrations, left `.specify/` in place). Final `bindle.toml`:
  `kits = []`. This smoke test's first `add` call ran without a
  `CLAUDE_CONFIG_DIR` isolation override — see "Safety note" below.
- Real (non-mocked), isolated integration tests: `TestRealClaudeAndCodexIntegration`
  (`tests/test_skills_software_engineering.py`, gated on `claude`+`git`
  presence, `CLAUDE_CONFIG_DIR`-isolated, skips cleanly if
  `t-step/skills` is unreachable) and `TestRealSpecifyIntegration`
  (`tests/test_skills_spec_kit.py`, gated on `specify` presence; no
  isolation override needed since `specify` was confirmed to touch no
  global state, including the real `specify integration status`
  exit-code-1-but-valid-JSON case above, which the round-trip test now
  exercises for real).
- Final correctness pass, new coverage: `TestCodexMultiWorktree` (real
  linked-worktree fixtures — independent markers, independent removal,
  shared `info/exclude` reconciliation surviving one worktree's removal),
  `TestCodexModifiedContentSafety` (a user-modified materialized skill
  survives `remove()` byte-for-byte, is reported as a conflict, and a
  retry after manual resolution succeeds), `TestDigestDir` (digest
  stability/sensitivity), spec-kit's `TestAddRemoveMocked`/`TestStatus`
  additions for missing-CLI and failed-status-query removal/status
  truthfulness, and `TestHelpOutputIsPlainText` in `tests/test_cli.py`
  (no ANSI escapes anywhere in `--help` output, tested under
  `PYTHON_COLORS=1` forced-color so the test cannot pass merely because
  stdout isn't a terminal, plus a structural check that every subparser
  instance is `_BindleArgumentParser`).

### Safety note

While manually smoke-testing before formalizing the automated suite, one
`bindle skills add software-engineering` invocation ran against a
disposable `/tmp` scratch repository **without** a `CLAUDE_CONFIG_DIR`
override — a direct miss against AGENTS.md's Runtime Isolation rule
("Never use live Bindle state during development or tests... Do not
modify: ... global Claude Code configuration"). Verified immediately
afterward, via `claude plugin list --json`, that `software-engineering@t-step-skills`
was already installed at both `user` and `local` scope on this machine
since 2026-08-21/22 — well before this session — so the marketplace-
registration check in `_claude_add()` correctly detected it as already
registered and never called `claude plugin marketplace add`; no new
global mutation occurred. The scratch repository's own `--scope project`
write stayed fully contained to its own disposable `.claude/settings.json`.
No harm resulted, but the isolation override should have been used
regardless of expected idempotency. Every subsequent test — the full
automated suite and all further manual verification — uses
`CLAUDE_CONFIG_DIR` isolation strictly.

## Decisions

Recorded in full in `docs/DECISIONS.md` D035. Summary: skill kit is the
unit of composition; desired state is repository-scoped (`bindle.toml`);
provider-native mechanisms remain the owners of projections; availability
is not adoption; removal means detach this repository's kit projection,
never uninstall the upstream tool from the machine; mixed
repository/machine scope is represented honestly rather than forced
uniform; this is a skill-kit-specific abstraction, not a generic Bindle
Component framework; further evolution (more kits, richer status) is
explicitly expected and not frozen by this design. Amended by the final
correctness pass: Codex ownership is worktree-scoped (`git_dir`), never
repository- or machine-scoped; the shared `info/exclude` bookkeeping it
requires is reconciled from every live worktree's marker rather than
owned by any one of them; and removal requires positive proof of
unmodified content (a digest), not merely a remembered directory name.

## Open questions

- Whether `bindle.toml`'s minimal line-patch writer should grow into a
  general TOML editor if a future repository config need arises — no
  evidence yet that it should; revisit only with a concrete second use.
- Whether Codex materialization should eventually gain a lightweight
  "refresh" path (still not `bindle update`) if staleness becomes an
  observed pain point — explicitly deferred per this slice's non-goals.
- Whether Spec Kit's own choice to leave its output untracked should be
  surfaced more prominently in `bindle skills status` (e.g. a
  worktree-locality hint) — deferred; the current per-harness status
  already answers "is it installed here," which is the immediately
  actionable fact.
- Whether a resolved Codex conflict should ever be auto-detected and
  cleared without a `remove()` call (e.g. a `status`-time hint pointing at
  the exact conflicting path) — deferred; the current conflict message
  already names the path and the fix (resolve by hand, then retry).

## Showcase evidence

Verified command transcripts (marketplace add/install/uninstall, `specify
init`/`integration install|uninstall`/`status --json` including the
exit-1-but-valid-JSON all-removed case, materialization + `info/exclude`
+ worktree-scoped ownership-marker inspection, cross-kit non-collision
under `.agents/skills/`, a real linked-worktree add/remove round trip)
are preserved in this session's tool-call history; the automated test
suite (`tests/test_skills_*.py`, `tests/test_cli.py::TestHelpOutputIsPlainText`)
reproduces the load-bearing subset deterministically and repeatably.
