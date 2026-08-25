"""Repository-scoped desired state for skill kits: `bindle.toml`.

`bindle.toml` is the one piece of tracked, repository-owned configuration
this slice introduces (docs/DECISIONS.md D035). It records only what a
repository *wants*:

    [skills]
    kits = ["software-engineering", "spec-kit"]

This is desired state, not history, not ownership bookkeeping, and not a
lockfile — it says nothing about whether a kit is actually usable on any
given machine right now (see the individual kit modules'
`status()`/`add()`/`remove()` for that). It is an ordinary tracked file,
just like AGENTS.md: read and written at `repo_info.worktree_root`, so it
follows the branch checked out in whichever worktree Bindle is invoked
from (docs/WORKTREES.md's "Branch-specific tracked files" row) — no
special worktree handling is needed here.

Reading uses `tomllib` (stdlib, Python 3.11+) so existing file content is
always validated, never guessed at. Writing never uses a general TOML
serializer: the schema is intentionally one table with one key, so writes
are a targeted line-level patch of exactly the `[skills]` table's `kits`
line, leaving every other byte of the file untouched. This satisfies "no
formatting rewrite explosion" and "unrelated future/unknown config content
is preserved" without adding a TOML-writing dependency to a project that
currently has none.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib

_CONFIG_FILENAME = "bindle.toml"

_TABLE_HEADER_RE = re.compile(r"^\[(?P<name>[A-Za-z0-9_-]+)\]\s*(#.*)?$")
_KITS_KEY_RE = re.compile(r"^kits\s*=")


class SkillsConfigError(RuntimeError):
    """Raised when bindle.toml exists but cannot be safely read or edited."""


def config_path(worktree_root: str) -> str:
    return os.path.join(worktree_root, _CONFIG_FILENAME)


def _read_raw(worktree_root: str) -> str:
    path = config_path(worktree_root)
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _parse(raw: str) -> dict:
    if not raw.strip():
        return {}
    try:
        return tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise SkillsConfigError(f"bindle.toml is not valid TOML: {exc}") from exc


def read_desired_kits(worktree_root: str) -> list[str]:
    """Read-only: the repository's currently desired kit IDs, in file order.

    Missing file, missing [skills] table, or missing kits key all mean "no
    kits desired yet" — an empty list, not an error. A malformed file, or
    a [skills]/kits shape that doesn't match the one supported schema
    (kits must be an array of strings), raises SkillsConfigError rather
    than guessing.
    """
    doc = _parse(_read_raw(worktree_root))
    skills = doc.get("skills", {})
    if not isinstance(skills, dict):
        raise SkillsConfigError("bindle.toml: [skills] must be a table")

    kits = skills.get("kits", [])
    if not isinstance(kits, list) or not all(isinstance(k, str) for k in kits):
        raise SkillsConfigError("bindle.toml: skills.kits must be an array of strings")

    return list(kits)


def _format_kits_line(kits: list[str]) -> str:
    inner = ", ".join(json.dumps(k) for k in kits)
    return f"kits = [{inner}]"


def _atomic_write(path: str, text: str) -> None:
    dest_dir = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".bindle-tomltmp.", dir=dest_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_kits(worktree_root: str, kits: list[str]) -> None:
    """Rewrite only the [skills] table's kits line; preserve everything else."""
    raw = _read_raw(worktree_root)
    new_line = _format_kits_line(kits)
    path = config_path(worktree_root)

    if not raw.strip():
        _atomic_write(path, f"[skills]\n{new_line}\n")
        return

    lines = raw.splitlines(keepends=True)
    skills_header_idx = None
    skills_end_idx = len(lines)  # exclusive end of the [skills] table's body

    for i, line in enumerate(lines):
        match = _TABLE_HEADER_RE.match(line.rstrip("\n"))
        if not match:
            continue
        if skills_header_idx is None:
            if match.group("name") == "skills":
                skills_header_idx = i
            continue
        # First header after [skills]: that table's body ends here.
        skills_end_idx = i
        break

    if skills_header_idx is None:
        # No [skills] table yet — append one as a new trailing section,
        # preserving every existing byte.
        sep = "" if raw.endswith("\n") else "\n"
        blank = "\n" if raw.strip() else ""
        _atomic_write(path, f"{raw}{sep}{blank}[skills]\n{new_line}\n")
        return

    kits_line_idx = None
    for i in range(skills_header_idx + 1, skills_end_idx):
        if _KITS_KEY_RE.match(lines[i].rstrip("\n")):
            kits_line_idx = i
            break

    if kits_line_idx is not None:
        lines[kits_line_idx] = new_line + "\n"
    else:
        lines.insert(skills_header_idx + 1, new_line + "\n")

    _atomic_write(path, "".join(lines))


def add_desired_kit(worktree_root: str, kit_id: str) -> bool:
    """Idempotent: add kit_id to desired state. Returns True iff it changed."""
    kits = read_desired_kits(worktree_root)
    if kit_id in kits:
        return False
    _write_kits(worktree_root, [*kits, kit_id])
    return True


def remove_desired_kit(worktree_root: str, kit_id: str) -> bool:
    """Idempotent: remove kit_id from desired state. Returns True iff it changed.

    Once a [skills] table exists, removing the last kit leaves an explicit
    `kits = []` rather than deleting the table — a deliberate, visible
    "nothing desired" rather than a file that silently reverts to looking
    unconfigured.
    """
    kits = read_desired_kits(worktree_root)
    if kit_id not in kits:
        return False
    _write_kits(worktree_root, [k for k in kits if k != kit_id])
    return True
