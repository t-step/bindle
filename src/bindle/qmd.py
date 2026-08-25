"""Read-only QMD adoption detection and native-CLI lifecycle helpers.

QMD (`tobi/qmd`, published as `@tobilu/qmd`) is a local Markdown search
engine: SQLite FTS5 BM25 full-text search always, with optional
vector/hybrid retrieval layered on top once embedding models are pulled.
This module gives a repository the smallest useful opt-in seam onto it —
`bindle init --qmd` — mirroring projectmem.py's shape (native CLI only,
filesystem-native detection, no vendored dependency) rather than
skills/*.py's shape (docs/DECISIONS.md D033's own closing precedent: two
provider-lifecycle integrations were enough to show real structural
differences; a third gets its own shape rather than forced symmetry).
Bindle declares no `@tobilu/qmd` package dependency — see qmd_executable().

Conceptual boundary this integration exists to keep (see this slice's own
plan/decision record): Markdown files remain the durable, authoritative
knowledge; the QMD index is derived, rebuildable retrieval state layered on
top. Deleting and rebuilding it must never lose knowledge. QMD is not a
work-coordination system and is not wired to Projectmem, Symphony, or any
agent prompt in this slice.

## Project-local mode, not a global named index — the collision-safety
## finding this design depends on

QMD supports two collection registries: a machine-global one
(`~/.config/qmd/<index>.yml`, default index name `index`, selectable via
`--index <name>`) and a project-local one (`.qmd/index.yml` +
`.qmd/index.sqlite`, created by `qmd init`, auto-adopted by every `qmd`
command run anywhere inside that directory tree — verified empirically
this session against the installed `qmd` 2.5.3/2.8.3 CLI). This
integration uses **project-local mode exclusively**. Verified directly
against this machine's own real global QMD state before choosing this:
`~/.config/qmd/bindle.yml` already registers an unrelated, pre-existing
collection also named "bindle" (the user's personal Obsidian vault, a
completely different directory) — a naive "derive a global collection
name from the repository" design would either collide with that or
require inventing a second repository-identity scheme purely for QMD.
Project-local mode sidesteps the problem entirely: `.qmd/` lives inside
this worktree, so there is nothing to name globally and nothing to
collide with.

**Consequence verified empirically and load-bearing for every function
below: `qmd collection add` run WITHOUT a prior `qmd init` in the same
directory silently falls back to the machine-global default index**
(`~/.config/qmd/index.yml` / `~/.cache/qmd/index.sqlite`) instead of
refusing or erroring. A caller that ever ran `collection add` first would
pollute the user's global QMD state with a collection pointing at this
one repository — exactly the "must not modify unrelated global
contexts/settings" failure this integration is required to avoid. Every
code path that mutates QMD state in this module (see `_apply_qmd` in cli.py)
therefore runs `qmd init` first, unconditionally, before ever running
`qmd collection add` — never the reverse, and never `collection add`
alone.

**A second, independent way to trip the exact same hazard, also verified
empirically this session: QMD resolves its project root from the `PWD`
environment variable, not from the invoking process's actual working
directory.** `subprocess.run([...], cwd=X)` changes the child process's
real cwd (confirmed via `os.getcwd()`), but does not itself set `PWD` —
that is ordinary shell bookkeeping (`cd` updates it), which nothing
inside a Python-spawned subprocess ever performs. A `qmd` child spawned
this way inherits Bindle's own `PWD` (or none), so it silently resolves
against the wrong project root — a fresh worktree with no `.qmd/` yet
falls straight through to the global default index, `qmd init` reports
success ("ready to go with new local index") without ever creating
`.qmd/`, and `qmd collection add` immediately after registers Bindle's
collection globally instead. Reproduced and fixed this session: setting
`PWD` explicitly in the subprocess environment (see `subprocess_env`
below) makes the exact same `subprocess.run(cwd=X)` call behave
identically to running the same command from a shell already `cd`'d into
`X`. Every subprocess invocation of `qmd` in this module's callers (see
`_apply_qmd` in cli.py) MUST use `subprocess_env`, never a bare
`cwd=info.worktree_root` with inherited environment — omitting this is
not a cosmetic bug, it is the same global-state-pollution hazard as
skipping `qmd init` above, just triggered a different way.

## Worktree scope

`.qmd/` is an ordinary, untracked, worktree-local directory (never
committed by this integration — see below), so it falls under
docs/WORKTREES.md's "worktree-local files ... exist only where created":
one worktree's QMD collection is independent of any other linked
worktree's. This needs no repository-identity-derived naming scheme (unlike
the Codex skill-kit ownership marker, which had to be pinned to
`repo_info.git_dir` specifically to get this property) — project-local
mode gets it for free, because `.qmd/` is just a plain directory next to
the code it indexes.

## Never tracked/committed

`qmd init` records the collection's `path:` as an absolute,
machine-specific filesystem path (verified this session) — committing
`.qmd/index.yml` would make it silently wrong for every other clone,
worktree, or machine, and QMD's own trust-gating model exists specifically
for the case of a checked-in project config with fields that "reach
outside the project." `ensure_gitignored` (below) makes this a repo-local
guarantee rather than a bystander convention: once QMD is initialized for
a repository, `.qmd/` is added to the repository's *machine-local*
`info/exclude` (`<git-common-dir>/info/exclude`) — never the repository's
own tracked `.gitignore`, mirroring D032's Claude-layer precedent for the
identical reason (a Bindle-added ignore rule must never become something
every clone silently inherits or a PR silently carries). `info/exclude`
is shared Git state across every linked worktree (D018), which is
correct here even though `.qmd/` itself is worktree-local: the rule "this
repository ignores `.qmd/`" is the same in every worktree, unlike the
Codex skill-kit materialization case (D035) where different worktrees can
legitimately have different materialized skill sets. This is add-once,
best-effort, and silent: if `.qmd/` is already tracked (an unusual,
deliberate choice) or already ignored by some other mechanism, nothing is
touched. No ownership marker is recorded and `bindle remove` never
attempts to undo this — `.qmd/` itself is never removed by `bindle
remove` either (see cli.py's `_cmd_remove`), so there is nothing to
reconcile the ignore rule against.

## Collection identity

One fixed collection name, `COLLECTION_NAME`, indexing a fixed, narrow
mask (`COLLECTION_MASK`) of this repository's existing durable Markdown:
root-level `*.md` (AGENTS.md, CLAUDE.md, PLAN.md, README.md), `docs/`, and
`plans/`, verified empirically against a fixture reproducing this
repository's real Markdown layout (including a `src/**/*.md`-style
decoy, correctly excluded) — a deliberately narrower boundary than "every
`*.md` in the tree" (excludes `.projectmem/`'s own generated Markdown,
any future vendored content, and anything outside the durable-knowledge
directories docs/DATA-OWNERSHIP.md already recognizes). No dedicated
knowledge-promotion directory is invented for this slice — see this
slice's plan/decision record for why indexing the existing corpus is
enough for a first integration.

## Detection is filesystem-native, not `qmd status`/`--json` parsing

Verified this session that neither `qmd status` nor `qmd collection list`
honors `--format json` (both still print the same plain-text report) —
so, exactly like detect_projectmem.py's own rationale, detection here
never shells out and parses CLI prose. `.qmd/index.yml` is a small,
QMD-authored YAML file with a fixed, verified-empirical shape
(`collections:\n  <name>:\n    path: <value>\n    ...`); `_parse_paths`
below is a narrow line-scan for exactly that shape, not a general YAML
parser (this project has no YAML dependency and none is added here). An
`index.yml` that doesn't match this shape (hand-edited, a different tool,
a future QMD format change) is never guessed at — see `detect_qmd`'s
`conflict` handling.

## States

Deliberately the small vocabulary suggested by this slice's own
brief, not the full projectmem/skills vocabulary:

  ready            `qmd` is on PATH, `.qmd/index.yml` exists, and its
                   `COLLECTION_NAME` collection's recorded path resolves
                   to this worktree root — Bindle's own collection,
                   confirmed.
  not-initialized  `qmd` is on PATH, but no project-local index exists
                   yet, or one exists without a `COLLECTION_NAME` entry
                   (an index some other tool or the user created, or a
                   previously-removed Bindle collection).
  unavailable      the `qmd` executable could not be resolved on PATH —
                   state cannot even be determined, distinct from
                   "not-initialized" for the same reason spec_kit.py
                   distinguishes them (D035).
  conflict         `.qmd` exists but isn't usable (occupied by a file or
                   a dangling symlink), `index.yml` exists but doesn't
                   match the expected shape, or a `COLLECTION_NAME` entry
                   exists but its recorded path resolves somewhere other
                   than this worktree (an unrelated, non-Bindle
                   collection happens to use the same name). Refuse
                   rather than guess, exactly like detect_projectmem.py's
                   own "partial"/"conflict" refusal precedent.

No "partial" state: unlike Projectmem's own recognized incomplete-init
shape, an interrupted `qmd init` leaves no intermediate directory-without-
config state worth distinguishing from "conflict" — both mean "don't
proceed without a human looking at this."
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .repo import RepoInfo

QmdState = str

_VALID_STATES = frozenset({"ready", "not-initialized", "unavailable", "conflict"})

_QMD_DIR_NAME = ".qmd"
# `qmd init` writes `index.yml`; `.yaml` is documented as also accepted —
# detection checks both rather than assuming the extension.
_INDEX_FILE_NAMES = ("index.yml", "index.yaml")

# The native QMD CLI entry point (installed separately, e.g. via
# `npm install -g @tobilu/qmd` — Bindle declares no dependency on it; see
# qmd_executable()).
_QMD_BINARY = "qmd"

# The one collection this integration ever creates or looks for. Fixed and
# singular — see module docstring's "Collection identity".
COLLECTION_NAME = "repo"

# Brace-form glob union, NOT the comma-joined form the CLI also documents
# ("*.md,docs/**/*.md,plans/**/*.md") — verified empirically this session
# that the comma-joined form silently matches zero files against the
# globally-installed `qmd` 2.5.3 (a real, load-bearing version
# incompatibility: the same comma-joined mask worked correctly against
# 2.8.3, installed separately for the deeper upstream investigation). The
# brace-form union below was verified to index the correct files under
# BOTH 2.5.3 and 2.8.3, so it — not the form shown first in the CLI's own
# README — is what this integration uses. Root-level Markdown, docs/, and
# plans/ — see module docstring's "Collection identity".
COLLECTION_MASK = "{*.md,docs/**/*.md,plans/**/*.md}"

# `qmd init` — creates (or, run again, safely leaves alone; verified
# empirically idempotent) the project-local `.qmd/index.yml` +
# `.qmd/index.sqlite` pair. Always run before QMD_COLLECTION_ADD_ARGS
# below — see module docstring's collision-safety finding.
QMD_INIT_ARGS = ("init",)


def qmd_executable() -> str | None:
    """Absolute path to the `qmd` CLI on PATH, or None if it isn't installed.

    Bindle has no QMD package dependency (AGENTS.md) and never constructs
    `.qmd/` state itself — this is only ever used to either invoke the real
    `qmd` CLI or fail clearly when it's absent.
    """
    return shutil.which(_QMD_BINARY)


def subprocess_env(worktree_root: str) -> dict[str, str]:
    """Environment for every `subprocess.run` call that invokes `qmd`.

    MUST be used for every `qmd` invocation in this integration — see
    module docstring's "PWD, not cwd" finding. `worktree_root` must be the
    same absolute path passed as that call's `cwd=`.
    """
    return {**os.environ, "PWD": worktree_root}


def collection_add_args(worktree_root: str) -> tuple[str, ...]:
    """`qmd collection add <worktree_root> --name <COLLECTION_NAME> --mask <COLLECTION_MASK>`.

    Only ever safe to run immediately after QMD_INIT_ARGS has already
    succeeded against the same `worktree_root` (see module docstring) —
    this function does not enforce that itself, callers must.
    """
    return (
        "collection",
        "add",
        worktree_root,
        "--name",
        COLLECTION_NAME,
        "--mask",
        COLLECTION_MASK,
    )


# The single, fixed exclude-file line this integration ever adds — see
# module docstring's "Never tracked/committed".
_EXCLUDE_LINE = f"{_QMD_DIR_NAME}/"


def _info_exclude_path(repo_info: RepoInfo) -> str:
    return os.path.join(repo_info.git_common_dir, "info", "exclude")


def _qmd_dir_is_tracked(repo_info: RepoInfo) -> bool:
    result = subprocess.run(
        ["git", "-C", repo_info.worktree_root, "ls-files", "--", _QMD_DIR_NAME],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _qmd_dir_is_ignored(repo_info: RepoInfo) -> bool:
    result = subprocess.run(
        ["git", "-C", repo_info.worktree_root, "check-ignore", "-q", _QMD_DIR_NAME],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _atomic_append_line(path: str, line: str) -> None:
    existing = ""
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()
    sep = "" if not existing or existing.endswith("\n") else "\n"
    new_text = f"{existing}{sep}{line}\n"

    dest_dir = os.path.dirname(path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".bindle-qmd-excludetmp.", dir=dest_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ensure_gitignored(repo_info: RepoInfo) -> None:
    """Best-effort: make sure `.qmd/` is locally ignored for this repository.

    Adds a single `.qmd/` line to the repository's machine-local
    `info/exclude` (never the tracked `.gitignore`) — see module
    docstring's "Never tracked/committed". Silent and idempotent: does
    nothing if `.qmd/` is already tracked, already ignored by some other
    mechanism, or the line is already present. Never raises on a
    filesystem/Git error here — this is a convenience, not a precondition
    for QMD itself working, so a failure here must never surface as a
    `bindle init --qmd` failure.
    """
    try:
        if _qmd_dir_is_tracked(repo_info) or _qmd_dir_is_ignored(repo_info):
            return

        path = _info_exclude_path(repo_info)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                if _EXCLUDE_LINE in f.read().splitlines():
                    return

        _atomic_append_line(path, _EXCLUDE_LINE)
    except OSError:
        pass


def _index_file_path(worktree_root: str) -> str | None:
    for name in _INDEX_FILE_NAMES:
        candidate = os.path.join(worktree_root, _QMD_DIR_NAME, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _parse_collection_paths(index_yml_text: str) -> dict[str, str]:
    """Narrow line-scan for `collections:\\n  <name>:\\n    path: <value>`.

    Matches exactly the shape the installed `qmd` CLI writes (verified
    this session against `qmd collection add`'s real output) — not a
    general YAML parser. Any collection name for which no `path:` line is
    found in the expected shape is simply absent from the returned dict,
    never guessed at. Stops scanning the `collections:` table as soon as a
    line at column 0 is seen (the next top-level key, e.g. `models:`), and
    never raises — a genuinely malformed file just yields an empty or
    partial dict, which `detect_qmd` below treats as "no matching
    collection found" (`conflict`, if `.qmd/index.yml` exists at all but
    isn't recognizable this way).
    """
    lines = index_yml_text.splitlines()
    paths: dict[str, str] = {}

    try:
        start = lines.index("collections:")
    except ValueError:
        return paths

    current_name: str | None = None
    for line in lines[start + 1 :]:
        if line and not line[0].isspace():
            break  # next top-level key (e.g. "models:") — collections table is done

        stripped = line.strip()
        if not stripped:
            continue

        # A collection name line is indented exactly two spaces and is a
        # bare "<name>:" key (QMD never inlines a collection's fields on
        # this line).
        if line.startswith("  ") and not line.startswith("   ") and stripped.endswith(":"):
            current_name = stripped[:-1]
            continue

        if current_name is not None and stripped.startswith("path:"):
            value = stripped[len("path:") :].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            paths[current_name] = value

    return paths


def detect_qmd(repo_info: RepoInfo) -> QmdState:
    """Read-only: this repository's QMD adoption state for its own collection.

    Scoped to `repo_info.worktree_root` only, matching detect_projectmem's
    own worktree-scoping rationale — a linked worktree does not inherit
    another worktree's `.qmd/` state, and QMD's own directory-tree
    auto-adoption (verified this session: any `qmd` command run inside a
    subdirectory finds the nearest ancestor `.qmd/`) makes this the correct
    boundary rather than an approximation of one.
    """
    if qmd_executable() is None:
        return "unavailable"

    qmd_dir = os.path.join(repo_info.worktree_root, _QMD_DIR_NAME)

    # lexists (not exists): a dangling symlink at `qmd_dir` must not read as
    # a clean absence, mirroring detect_projectmem's identical handling.
    if not os.path.lexists(qmd_dir):
        return "not-initialized"
    if not os.path.isdir(qmd_dir):
        return "conflict"

    index_path = _index_file_path(repo_info.worktree_root)
    if index_path is None:
        # `.qmd/` exists but no recognizable index file — an interrupted
        # `qmd init`, or something unrelated created the directory. No
        # "partial" state in this vocabulary (see module docstring):
        # refuse rather than guess.
        return "conflict"

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return "conflict"

    collections = _parse_collection_paths(text)
    if COLLECTION_NAME not in collections:
        return "not-initialized"

    recorded_path = collections[COLLECTION_NAME]
    if os.path.realpath(recorded_path) == os.path.realpath(repo_info.worktree_root):
        return "ready"

    # A collection named COLLECTION_NAME exists but points somewhere else —
    # not Bindle's own (or this worktree's own from before a path/rename
    # change). Ownership is ambiguous; never overwrite or reuse it.
    return "conflict"
