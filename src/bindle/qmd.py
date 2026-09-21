"""Read-only QMD adoption detection and native-CLI lifecycle helpers.

QMD (`tobi/qmd`, published as `@tobilu/qmd`) is a local Markdown search engine:
SQLite FTS5 BM25 full-text search always, optional vector/hybrid retrieval once
embedding models are pulled. This module is the opt-in seam onto it (`bindle
init --qmd`), shaped like projectmem.py (native CLI only, filesystem-native
detection, no vendored dependency) rather than skills/*.py (D033: a third
provider-lifecycle integration gets its own shape rather than forced symmetry).
Bindle declares no `@tobilu/qmd` package dependency; see qmd_executable().

Boundary: Markdown files stay the durable, authoritative knowledge; the QMD
index is derived, rebuildable retrieval state, so deleting it never loses
knowledge. QMD is not a work-coordination system and is not wired to Projectmem,
Symphony, or any agent prompt.

## Project-local mode, not a global named index

QMD has a machine-global collection registry (`~/.config/qmd/<index>.yml`,
default index name `index`, selectable via `--index <name>`) and a project-local
one (`.qmd/index.yml` + `.qmd/index.sqlite`, created by `qmd init`, auto-adopted
by every `qmd` command run anywhere inside that directory tree; verified against
qmd 2.5.3/2.8.3). This integration uses project-local mode exclusively: a global
collection name derived from the repository would collide with unrelated
collections (the developer's real global QMD state already registers an
unrelated personal Obsidian vault as "bindle") or need a second
repository-identity scheme just for QMD. `.qmd/` lives inside the worktree, so
nothing is named globally.

Two verified hazards silently fall back to the machine-global default index
(`~/.config/qmd/index.yml` / `~/.cache/qmd/index.sqlite`) and would register
this repository's collection in the user's global QMD state:

1. `qmd collection add` run WITHOUT a prior `qmd init` in the same directory
   falls back instead of erroring. Every mutating path (see `_apply_qmd` in
   cli.py) therefore runs `qmd init` first, unconditionally, never `collection
   add` alone.
2. QMD resolves its project root from the `PWD` environment variable, not the
   process's real cwd. `subprocess.run(cwd=X)` changes the child's cwd but not
   `PWD` (shell `cd` bookkeeping), so the child resolves against Bindle's own
   `PWD`: `qmd init` reports success without creating `.qmd/`, and `collection
   add` then registers globally. Every `qmd` subprocess MUST use
   `subprocess_env`, never a bare `cwd=info.worktree_root` with inherited
   environment.

## Worktree scope

`.qmd/` is an untracked, worktree-local directory (docs/WORKTREES.md:
"worktree-local files ... exist only where created"), so one worktree's QMD
collection is independent of every other's with no repository-identity-derived
naming (unlike the Codex skill-kit ownership marker, which had to be pinned to
`repo_info.git_dir` for this property).

## Never tracked/committed

`qmd init` records the collection's `path:` as an absolute, machine-specific
path, so a committed `.qmd/index.yml` would be wrong for every other
clone/worktree/machine, and QMD's trust-gating model exists for checked-in
project configs with fields that "reach outside the project."
`ensure_gitignored` therefore adds `.qmd/` to the machine-local
`<git-common-dir>/info/exclude`, never the tracked `.gitignore` (D032's
Claude-layer precedent: a Bindle-added ignore rule must never be inherited by
every clone or carried by a PR). `info/exclude` is shared across linked
worktrees (D018), which is right even though `.qmd/` is worktree-local: "this
repository ignores `.qmd/`" holds in every worktree, unlike Codex skill-kit
materialization (D035) where worktrees can differ. It is add-once, best-effort,
and silent: nothing is touched if `.qmd/` is already tracked or ignored. No
ownership marker is recorded and `bindle remove` never undoes it (it never
removes `.qmd/` either; see cli.py's `_cmd_remove`).

## Collection identity

One fixed `COLLECTION_NAME` indexing a fixed, narrow `COLLECTION_MASK` of
existing durable Markdown: root-level `*.md` (AGENTS.md, CLAUDE.md, PLAN.md,
README.md), `docs/`, `plans/`, and `specs/` (Spec Kit planning authority;
D049), verified against a fixture reproducing the real layout, including a
`src/**/*.md`-style decoy. Deliberately narrower than every `*.md` in the
tree: excludes `.projectmem/`'s generated Markdown, future vendored content,
and anything outside the directories docs/DATA-OWNERSHIP.md treats as
durable. No dedicated knowledge-promotion directory is invented.

## Detection is filesystem-native, not `qmd status`/`--json` parsing

Neither `qmd status` nor `qmd collection list` honors `--format json` (both
print the same plain-text report), so, like detect_projectmem.py, detection
never shells out and parses CLI prose. `.qmd/index.yml` is a small QMD-authored
YAML file (`collections:\n  <name>:\n    path: <value>`);
`_parse_collection_paths` is a narrow line-scan for exactly that shape, not a
YAML parser (no YAML dependency exists or is added). An `index.yml` not matching
it (hand-edited, another tool, a future QMD format change) is never guessed at;
see `detect_qmd`'s `conflict` handling.

## States

Deliberately small, not the full projectmem/skills vocabulary:

  ready            `qmd` is on PATH, `.qmd/index.yml` exists, and its
                   `COLLECTION_NAME` entry's recorded path resolves to this
                   worktree root.
  not-initialized  `qmd` is on PATH, but no project-local index exists yet, or
                   one exists without a `COLLECTION_NAME` entry (another tool's
                   index, or a removed Bindle collection).
  unavailable      `qmd` could not be resolved on PATH; state cannot be
                   determined, distinct from "not-initialized" as in spec_kit.py
                   (D035).
  conflict         `.qmd` is a file or dangling symlink, `index.yml` doesn't
                   match the expected shape, or a `COLLECTION_NAME` entry's path
                   resolves elsewhere (an unrelated collection using the same
                   name). Refuse rather than guess, as detect_projectmem.py does
                   for "partial"/"conflict".

No "partial" state: an interrupted `qmd init` leaves no intermediate state worth
distinguishing from "conflict"; both mean a human should look before proceeding.
"""

from __future__ import annotations

import os
import shutil

from . import git_local_exclude
from .repo import RepoInfo

QmdState = str

_VALID_STATES = frozenset({"ready", "not-initialized", "unavailable", "conflict"})

_QMD_DIR_NAME = ".qmd"
# `qmd init` writes index.yml; index.yaml is also documented as accepted.
_INDEX_FILE_NAMES = ("index.yml", "index.yaml")

# Installed separately (`npm install -g @tobilu/qmd`); not a Bindle dependency.
_QMD_BINARY = "qmd"

COLLECTION_NAME = "repo"

# Not comma-joined: that silently matches zero files on qmd 2.5.3 (ok on 2.8.3).
COLLECTION_MASK = "{*.md,docs/**/*.md,plans/**/*.md,specs/**/*.md}"

# Idempotent; must run before `collection add` (see module docstring).
QMD_INIT_ARGS = ("init",)


def qmd_executable() -> str | None:
    """Absolute path to the `qmd` CLI on PATH, or None if it isn't installed.

    Bindle never constructs `.qmd/` state itself; this only locates the CLI to
    invoke.
    """
    return shutil.which(_QMD_BINARY)


def subprocess_env(worktree_root: str) -> dict[str, str]:
    """Environment for every `qmd` subprocess: sets `PWD`, which QMD resolves
    its project root from.

    MUST be used for every `qmd` invocation; `worktree_root` must equal that
    call's `cwd=`.
    """
    return {**os.environ, "PWD": worktree_root}


def collection_add_args(worktree_root: str) -> tuple[str, ...]:
    """`qmd collection add <worktree_root> --name <COLLECTION_NAME> --mask <COLLECTION_MASK>`.

    Only safe after QMD_INIT_ARGS has succeeded against the same
    `worktree_root`; callers must enforce that.
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


_EXCLUDE_LINE = f"{_QMD_DIR_NAME}/"


def _qmd_dir_is_tracked(repo_info: RepoInfo) -> bool:
    return git_local_exclude.is_path_tracked(repo_info.worktree_root, _QMD_DIR_NAME)


def _qmd_dir_is_ignored(repo_info: RepoInfo) -> bool:
    return git_local_exclude.is_path_ignored(repo_info.worktree_root, _QMD_DIR_NAME)


def ensure_gitignored(repo_info: RepoInfo) -> None:
    """Best-effort: make sure `.qmd/` is locally ignored for this repository.

    Adds `.qmd/` to the machine-local `info/exclude` (module docstring, "Never
    tracked/committed"); does nothing if already tracked, ignored, or present.
    Never raises on filesystem/Git errors: this is a convenience, so a failure
    must never fail `bindle init --qmd`.
    """
    try:
        if _qmd_dir_is_tracked(repo_info) or _qmd_dir_is_ignored(repo_info):
            return
        git_local_exclude.ensure_line_excluded(repo_info.git_common_dir, _EXCLUDE_LINE)
    except OSError:
        pass


def _index_file_path(worktree_root: str) -> str | None:
    for name in _INDEX_FILE_NAMES:
        candidate = os.path.join(worktree_root, _QMD_DIR_NAME, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _parse_collection_paths(index_yml_text: str) -> dict[str, str]:
    """Narrow line-scan for `collections:\\n  <name>:\\n    path: <value>`; not
    a general YAML parser.

    Matches the shape the `qmd` CLI writes. A collection with no `path:` line in
    that shape is absent from the result, never guessed at. Stops at the first
    column-0 line after `collections:` (next top-level key, e.g. `models:`).
    Never raises: a malformed file yields an empty or partial dict, which
    `detect_qmd` treats as no matching collection.
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
            break

        stripped = line.strip()
        if not stripped:
            continue

        # Name line: 2-space indent, bare "<name>:" (fields never inline).
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

    Scoped to `repo_info.worktree_root` only, as in detect_projectmem: a linked
    worktree does not inherit another's `.qmd/`, and QMD's tree auto-adoption
    (any `qmd` command in a subdirectory finds the nearest ancestor `.qmd/`)
    makes this the correct boundary.
    """
    if qmd_executable() is None:
        return "unavailable"

    qmd_dir = os.path.join(repo_info.worktree_root, _QMD_DIR_NAME)

    # lexists, not exists: a dangling symlink must not read as absent.
    if not os.path.lexists(qmd_dir):
        return "not-initialized"
    if not os.path.isdir(qmd_dir):
        return "conflict"

    index_path = _index_file_path(repo_info.worktree_root)
    if index_path is None:
        # Interrupted `qmd init` or a foreign directory; no "partial" state.
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

    # Same name, other path: ownership is ambiguous; never overwrite/reuse.
    return "conflict"
