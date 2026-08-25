"""The `software-engineering` skill kit.

Source of truth: `t-step/skills` (github.com/t-step/skills), `main` branch
— never vendored into Bindle (docs/DECISIONS.md D035). Verified this
session against the live repository: one marketplace (`t-step-skills`)
publishing one plugin (`software-engineering`), whose `skills/` subtree
under `plugins/software-engineering/` contains plain, portable
`SKILL.md`-only directories with no Claude-specific runtime dependency.

Claude Code: uses the kit's own native marketplace/plugin mechanism
end-to-end (`claude plugin marketplace add` / `claude plugin
install|uninstall --scope project`) — verified against the installed
`claude` 2.1.243 CLI this session. Marketplace *registration* is Claude's
own machine-global concept, never project-scoped, regardless of the scope
passed to `plugin install` — `add()` registers it if missing (idempotent,
low-blast-radius, shared infrastructure other repositories on this
machine may also rely on), but `remove()` never unregisters it, mirroring
D032/D033's precedent that a repository-scoped command must never mutate
machine-global state as a side effect. `remove()` also never claims
success it couldn't perform: if `.claude/settings.json` already says the
plugin is enabled but the `claude` CLI is unavailable, removal fails
loudly rather than silently leaving stale configuration behind while
reporting "nothing to remove".

Codex: has no package manager or CLI lifecycle for skills (confirmed this
session against Codex 0.146.0) — the native mechanism is a plain
`.agents/skills/<name>/SKILL.md` directory Codex discovers by repo-local
convention. Bindle materializes each skill directory verbatim from a
fresh shallow clone of `t-step/skills` at `add()` time — a point-in-time
snapshot, not a live sync (no auto-update; see this slice's explicit
non-goals).

Ownership is genuinely worktree-scoped: the materialized files live under
`<worktree>/.agents/skills/<name>/` (worktree-local, per
docs/WORKTREES.md), so the ownership marker recording what Bindle
materialized lives at `<git-dir>/bindle-skills/software-engineering.codex.json`
— `repo_info.git_dir`, NOT `repo_info.git_common_dir`. For an ordinary
checkout these are the same path; for a linked worktree `git_dir` is
Git's own per-worktree administrative directory
(`<git-common-dir>/worktrees/<id>`), which Git itself removes when the
worktree is removed. This means two linked worktrees that both
materialize the kit get independent ownership evidence — one worktree's
`remove()` can never delete or corrupt another worktree's ownership
record, and ownership can never survive its own worktree's actual
disappearance.

`info/exclude`, by contrast, genuinely is shared repository state (not
worktree-local) — so it is reconciled, not owned by any single worktree's
marker: `_reconcile_exclude_block()` recomputes the full set of required
ignore lines from the union of every currently-live worktree's marker
(found by walking `<git-common-dir>/worktrees/*`, which — like the
markers themselves — Git prunes on its own when a worktree goes away) and
rewrites exactly one clearly-delimited, mechanically-owned block in
`info/exclude`, leaving every other line (including a pre-existing
identical entry some other tool or the user added) untouched. One
worktree removing the kit therefore only ever removes the ignore lines no
remaining worktree still needs.

Ownership at removal time requires more than a remembered directory name:
each marker entry pairs a skill name with a deterministic content digest
of what Bindle actually wrote there (`_digest_dir`). `remove()` only ever
deletes a directory whose current content still matches that digest;
anything modified, replaced, or foreign since materialization is left in
place and reported as a conflict, with its ownership evidence retained
in the marker so a future `remove()` (after the user resolves it by hand)
can still act on it safely.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile

from ..repo import RepoInfo
from .types import KitOpOutcome, KitStatus

MARKETPLACE_SOURCE = "t-step/skills"
MARKETPLACE_ID = "t-step-skills"
PLUGIN_ID = "software-engineering"
PLUGIN_SPEC = f"{PLUGIN_ID}@{MARKETPLACE_ID}"

_SKILLS_GIT_URL = "https://github.com/t-step/skills.git"
_SKILLS_SUBTREE = os.path.join("plugins", "software-engineering", "skills")
_CODEX_SKILLS_DIR = ".agents/skills"

_MARKER_RELPATH = os.path.join("bindle-skills", "software-engineering.codex.json")

_EXCLUDE_BLOCK_BEGIN = "# BEGIN bindle-managed (software-engineering codex skills) — do not edit by hand"
_EXCLUDE_BLOCK_END = "# END bindle-managed (software-engineering codex skills)"


def _line(label: str, text: str) -> str:
    return f"{label:<10}{text}"


def _atomic_write_text(path: str, text: str) -> None:
    dest_dir = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".bindle-skillstmp.", dir=dest_dir)
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


# --- worktree-scoped ownership marker ------------------------------------


def _marker_path_for_git_dir(git_dir: str) -> str:
    return os.path.join(git_dir, _MARKER_RELPATH)


def _marker_path(repo_info: RepoInfo) -> str:
    # repo_info.git_dir, not git_common_dir: the marker describes THIS
    # worktree's own materialization, and must live somewhere Git itself
    # tears down along with the worktree (see module docstring).
    return _marker_path_for_git_dir(repo_info.git_dir)


def _read_marker_at(git_dir: str) -> dict | None:
    path = _marker_path_for_git_dir(git_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_marker(repo_info: RepoInfo) -> dict | None:
    return _read_marker_at(repo_info.git_dir)


def _write_marker(repo_info: RepoInfo, skills: dict[str, str]) -> None:
    path = _marker_path(repo_info)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write_text(path, json.dumps({"skills": skills}, indent=2) + "\n")


def _remove_marker(repo_info: RepoInfo) -> None:
    try:
        os.unlink(_marker_path(repo_info))
    except FileNotFoundError:
        pass


def _all_worktree_git_dirs(repo_info: RepoInfo) -> list[str]:
    # The main checkout's own git_dir equals git_common_dir (verified:
    # `git rev-parse --git-dir` and `--git-common-dir` return the same
    # path from the main worktree). Each linked worktree's git_dir is a
    # subdirectory of git_common_dir/worktrees/ — walking that directory
    # finds every worktree Git currently knows about, live or not,
    # without shelling out to `git worktree list` and without assuming
    # any of them still has a working directory.
    dirs = [repo_info.git_common_dir]
    worktrees_dir = os.path.join(repo_info.git_common_dir, "worktrees")
    if os.path.isdir(worktrees_dir):
        for entry in sorted(os.scandir(worktrees_dir), key=lambda e: e.name):
            if entry.is_dir():
                dirs.append(entry.path)
    return dirs


# --- content-identity digest ----------------------------------------------


def _digest_dir(path: str) -> str:
    """Deterministic content digest of every regular file under `path`.

    Covers relative path and content for every file, so it changes if
    anything is added, removed, renamed, or edited — the exact predicate
    `remove()` needs to tell "still Bindle's own, unmodified" apart from
    "touched since materialization" without needing network access to
    re-fetch the original source.
    """
    entries = []
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, path).replace(os.sep, "/")
            with open(fpath, "rb") as f:
                content_hash = hashlib.sha256(f.read()).hexdigest()
            entries.append(f"{rel}\0{content_hash}")
    manifest = "\n".join(sorted(entries))
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


# --- Claude harness ------------------------------------------------------


def _claude_executable() -> str | None:
    return shutil.which("claude")


def _claude_settings_path(repo_info: RepoInfo) -> str:
    return os.path.join(repo_info.worktree_root, ".claude", "settings.json")


def _claude_status(repo_info: RepoInfo) -> str:
    path = _claude_settings_path(repo_info)
    if not os.path.isfile(path):
        return "not-installed"
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return "not-installed"
    if not isinstance(doc, dict):
        return "not-installed"
    enabled = doc.get("enabledPlugins")
    if not isinstance(enabled, dict):
        return "not-installed"
    return "installed" if enabled.get(PLUGIN_SPEC) is True else "not-installed"


def _claude_marketplace_registered(claude: str) -> bool:
    result = subprocess.run(
        [claude, "plugin", "marketplace", "list", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    try:
        marketplaces = json.loads(result.stdout)
    except ValueError:
        return False
    if not isinstance(marketplaces, list):
        return False
    return any(isinstance(m, dict) and m.get("name") == MARKETPLACE_ID for m in marketplaces)


def _claude_add(repo_info: RepoInfo) -> tuple[bool, str]:
    claude = _claude_executable()
    if claude is None:
        return True, _line("Claude", "unavailable (claude CLI not found on PATH)")

    if _claude_status(repo_info) == "installed":
        return True, _line("Claude", "already installed — left unchanged")

    if not _claude_marketplace_registered(claude):
        result = subprocess.run(
            [claude, "plugin", "marketplace", "add", MARKETPLACE_SOURCE],
            cwd=repo_info.worktree_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            return False, _line("Claude", f"failed to register marketplace {MARKETPLACE_SOURCE}: {detail}")

    result = subprocess.run(
        [claude, "plugin", "install", PLUGIN_SPEC, "--scope", "project", "-y"],
        cwd=repo_info.worktree_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        return False, _line("Claude", f"install failed: {detail}")
    return True, _line("Claude", "installed")


def _claude_remove(repo_info: RepoInfo) -> tuple[bool, str]:
    installed = _claude_status(repo_info) == "installed"
    claude = _claude_executable()

    if claude is None:
        if not installed:
            return True, _line("Claude", "unavailable (claude CLI not found on PATH) — nothing to remove")
        return False, _line(
            "Claude",
            "unavailable (claude CLI not found on PATH) — .claude/settings.json still shows it "
            "enabled; install the claude CLI to detach it safely, configuration left as-is",
        )

    if not installed:
        return True, _line("Claude", "already not installed — left unchanged")

    result = subprocess.run(
        [claude, "plugin", "uninstall", PLUGIN_SPEC, "--scope", "project", "-y"],
        cwd=repo_info.worktree_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        return False, _line("Claude", f"uninstall failed: {detail}")
    return True, _line("Claude", "removed (marketplace registration left in place)")


# --- Codex harness ---------------------------------------------------------


def _codex_skills_root(repo_info: RepoInfo) -> str:
    return os.path.join(repo_info.worktree_root, _CODEX_SKILLS_DIR)


def _codex_status(repo_info: RepoInfo) -> str:
    marker = _read_marker(repo_info)
    if marker is None:
        return "not-installed"
    skills = marker.get("skills") or {}
    if not skills:
        return "not-installed"

    root = _codex_skills_root(repo_info)
    present = 0
    conflict = 0
    for name, digest in skills.items():
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        if _digest_dir(path) == digest:
            present += 1
        else:
            conflict += 1

    if conflict:
        return "conflict"
    if present == len(skills):
        return "installed"
    if present == 0:
        return "not-installed"
    return "partial"


def _clone_skills_source(tmp_dir: str) -> tuple[bool, str]:
    git = shutil.which("git")
    if git is None:
        return False, "git not found on PATH"
    result = subprocess.run(
        [git, "clone", "--depth", "1", "--branch", "main", _SKILLS_GIT_URL, tmp_dir],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip()
    return True, ""


def _discover_skill_dirs(clone_dir: str) -> list[str]:
    subtree = os.path.join(clone_dir, _SKILLS_SUBTREE)
    if not os.path.isdir(subtree):
        return []
    return sorted(
        entry.name
        for entry in os.scandir(subtree)
        if entry.is_dir() and os.path.isfile(os.path.join(entry.path, "SKILL.md"))
    )


# --- shared info/exclude reconciliation -----------------------------------


def _info_exclude_path(repo_info: RepoInfo) -> str:
    return os.path.join(repo_info.git_common_dir, "info", "exclude")


def _is_tracked(repo_info: RepoInfo, rel_path: str) -> bool:
    result = subprocess.run(
        ["git", "-C", repo_info.worktree_root, "ls-files", "--error-unmatch", rel_path],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _is_ignored(repo_info: RepoInfo, rel_path: str) -> bool:
    result = subprocess.run(
        ["git", "-C", repo_info.worktree_root, "check-ignore", "-q", rel_path],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _all_required_exclude_lines(repo_info: RepoInfo) -> set[str]:
    required: set[str] = set()
    for git_dir in _all_worktree_git_dirs(repo_info):
        marker = _read_marker_at(git_dir)
        if not marker:
            continue
        for name in marker.get("skills") or {}:
            required.add(f"{_CODEX_SKILLS_DIR}/{name}/")
    return required


def _split_exclude_block(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    try:
        begin = lines.index(_EXCLUDE_BLOCK_BEGIN)
        end = lines.index(_EXCLUDE_BLOCK_END, begin)
    except ValueError:
        return lines, [], []
    return lines[:begin], lines[begin + 1 : end], lines[end + 1 :]


def _reconcile_exclude_block(repo_info: RepoInfo) -> None:
    """Rewrite exactly Bindle's own delimited block in info/exclude to
    match the union of every live worktree's current ownership marker.

    Never touches a line outside the block: a pre-existing identical
    entry (this repository's own .gitignore, or a foreign info/exclude
    line) is recognized and left alone rather than duplicated into the
    block. Lines already inside the block are kept as long as any
    worktree still requires them, without re-running the tracked/ignored
    check against them (which would be self-referential — the block's
    own presence is exactly why `git check-ignore` would say "yes").
    """
    required = sorted(_all_required_exclude_lines(repo_info))
    path = _info_exclude_path(repo_info)

    lines: list[str] = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    before, existing_block, after = _split_exclude_block(lines)
    foreign = set(before) | set(after)
    existing_block_set = set(existing_block)

    block_lines = []
    for candidate in required:
        if candidate in foreign:
            continue
        if candidate in existing_block_set:
            block_lines.append(candidate)
            continue
        rel = candidate.rstrip("/")
        if _is_tracked(repo_info, rel) or _is_ignored(repo_info, rel):
            continue
        block_lines.append(candidate)

    if block_lines:
        new_lines = [*before, _EXCLUDE_BLOCK_BEGIN, *block_lines, _EXCLUDE_BLOCK_END, *after]
    else:
        new_lines = [*before, *after]

    if not new_lines:
        # before/after (everything outside Bindle's own block) are both
        # empty, and nothing requires the block anymore. The file must
        # still be rewritten empty here, not left as-is: if info/exclude
        # never existed before Bindle created it containing only its own
        # block, "nothing to write" would otherwise mean "return without
        # touching a file that currently holds nothing but stale
        # Bindle-owned content." Clearing it (never unlinking — the file
        # is Git infrastructure, not Bindle's to remove) leaves no
        # Bindle-owned line behind while staying inside the same
        # conservative ownership boundary as the rest of this function.
        if os.path.exists(path):
            _atomic_write_text(path, "")
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write_text(path, "\n".join(new_lines) + "\n")


def _codex_add(repo_info: RepoInfo) -> tuple[bool, str]:
    current = _codex_status(repo_info)
    if current == "installed":
        return True, _line("Codex", "already installed — left unchanged")
    if current == "conflict":
        return False, _line(
            "Codex",
            "conflict: one or more materialized skills were modified since Bindle created "
            "them — resolve or remove them by hand, then retry",
        )

    existing_marker = _read_marker(repo_info) or {}
    existing_skills: dict[str, str] = dict(existing_marker.get("skills") or {})
    root = _codex_skills_root(repo_info)

    with tempfile.TemporaryDirectory(prefix="bindle-skills-clone-") as tmp:
        ok, detail = _clone_skills_source(tmp)
        if not ok:
            return True, _line("Codex", f"unavailable (could not fetch {MARKETPLACE_SOURCE}: {detail})")

        skill_dirs = _discover_skill_dirs(tmp)
        if not skill_dirs:
            return True, _line("Codex", f"unavailable ({MARKETPLACE_SOURCE} published no skills at the expected path)")

        # Names newly seen, or previously owned but currently missing from
        # disk (e.g. deleted by hand) — both need (re)materializing. A
        # name already owned with matching content was excluded by the
        # "installed"/"conflict" status gate above.
        to_write = [
            name
            for name in skill_dirs
            if name not in existing_skills or not os.path.isdir(os.path.join(root, name))
        ]

        conflicts = [name for name in to_write if os.path.lexists(os.path.join(root, name))]
        if conflicts:
            paths = ", ".join(f"{_CODEX_SKILLS_DIR}/{n}" for n in conflicts)
            return False, _line("Codex", f"conflict: {paths} already exist and are not Bindle-owned — refusing to overwrite")

        new_digests: dict[str, str] = {}
        for name in to_write:
            dst = os.path.join(root, name)
            shutil.copytree(os.path.join(tmp, _SKILLS_SUBTREE, name), dst)
            new_digests[name] = _digest_dir(dst)

    all_skills = {**existing_skills, **new_digests}
    _write_marker(repo_info, all_skills)
    _reconcile_exclude_block(repo_info)
    return True, _line("Codex", f"installed ({len(all_skills)} skill(s) materialized from {MARKETPLACE_SOURCE})")


def _codex_remove(repo_info: RepoInfo) -> tuple[bool, str]:
    marker = _read_marker(repo_info)
    if marker is None:
        return True, _line("Codex", "already not installed — left unchanged")

    skills: dict[str, str] = dict(marker.get("skills") or {})
    root = _codex_skills_root(repo_info)

    removed: list[str] = []
    conflicted: list[str] = []
    remaining: dict[str, str] = {}

    for name, digest in skills.items():
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            # Already gone — nothing to preserve, nothing to remove.
            removed.append(name)
            continue
        if _digest_dir(path) == digest:
            shutil.rmtree(path)
            removed.append(name)
        else:
            # Modified/replaced since materialization: preserve it, and
            # keep its ownership evidence so a future remove (after the
            # user resolves it) can still act on it safely.
            conflicted.append(name)
            remaining[name] = digest

    if remaining:
        _write_marker(repo_info, remaining)
    else:
        _remove_marker(repo_info)

    _reconcile_exclude_block(repo_info)

    if conflicted:
        paths = ", ".join(f"{_CODEX_SKILLS_DIR}/{n}" for n in conflicted)
        return False, _line(
            "Codex",
            f"conflict: {paths} modified since materialization — preserved, not removed "
            f"({len(removed)} unmodified skill(s) detached; resolve by hand and retry)",
        )

    detail = f"{len(removed)} skill(s) detached" if removed else "no materialized files remained"
    return True, _line("Codex", f"removed ({detail})")


# --- public API --------------------------------------------------------


def status(repo_info: RepoInfo) -> KitStatus:
    return KitStatus(claude=_claude_status(repo_info), codex=_codex_status(repo_info))


def add(repo_info: RepoInfo) -> KitOpOutcome:
    claude_ok, claude_line = _claude_add(repo_info)
    codex_ok, codex_line = _codex_add(repo_info)
    return KitOpOutcome(ok=claude_ok and codex_ok, lines=[claude_line, codex_line])


def remove(repo_info: RepoInfo) -> KitOpOutcome:
    claude_ok, claude_line = _claude_remove(repo_info)
    codex_ok, codex_line = _codex_remove(repo_info)
    return KitOpOutcome(ok=claude_ok and codex_ok, lines=[claude_line, codex_line])
