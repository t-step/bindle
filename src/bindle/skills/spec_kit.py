"""The `spec-kit` skill kit: GitHub Spec Kit, upstream-owned.

This module never reimplements Spec Kit's installer or copies its skill files by
hand (D035). Every mutation and status read goes through the native `specify`
CLI, as guardrails.py shells out to install-guardrails.sh's `--status` rather
than reimplementing its predicates.

Observed `specify-cli` 1.0.1 behavior: installing the claude and codex
integrations coexist in one project; `integration status --json` gives a
parseable `installed_integrations` list; `integration uninstall <key>` removes
only that integration's tracked files.

Spec Kit's skills are not self-contained: their `SKILL.md` declares
`compatibility: "Requires spec-kit project structure with .specify/ directory"`
and shells out to `.specify/scripts/...`. So this kit is a Spec Kit
*integration*, not a folder of skill files: when `.specify/` is absent `add()`
bootstraps it with `specify init --here`, never by hand.

`specify bundle` was evaluated as a reusable distribution mechanism and
rejected: it composes Spec Kit's own primitives (extensions, presets, steps,
workflows) and is not a generic package manager.

`remove()` only runs `specify integration uninstall claude`/`codex`. It never
deletes `.specify/` (no such command exists, and other integrations or the
repository's own Spec Kit use may depend on it) and never touches the `specify`
executable.

Provider errors are never collapsed into absence. A missing `.specify/` is the
one case equivalent to "not installed" (a filesystem fact needing no `specify`
binary). Once it exists, a missing `specify` binary or unparseable status output
reports `unavailable`, never `not-installed`; see `_installed_integrations` for
why the exit code is deliberately not gated on. `remove()` is a clean no-op only
when `.specify/` is absent; otherwise a state or uninstall it cannot safely
perform reports failure and leaves `.specify/` and its integrations as they are.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

from ..repo import RepoInfo
from .types import KitOpOutcome, KitStatus

_HARNESS_KEYS = ("claude", "codex")
_HARNESS_LABELS = {"claude": "Claude", "codex": "Codex"}

# Arbitrary: `specify init` needs one integration; both harnesses get installed.
_BOOTSTRAP_INTEGRATION = "claude"
_BOOTSTRAP_SCRIPT = "sh"


def _line(label: str, text: str) -> str:
    return f"{label:<10}{text}"


def _specify_executable() -> str | None:
    return shutil.which("specify")


def _specify_dir(repo_info: RepoInfo) -> str:
    return os.path.join(repo_info.worktree_root, ".specify")


def _installed_integrations(specify: str, repo_info: RepoInfo) -> set[str] | None:
    """Read-only; None means state could not be determined (not an empty set).

    Deliberately does NOT gate on the exit code: `specify integration status
    --json` exits 1 once every integration is removed
    (`.specify/integration.json` missing, `"status": "error"`) yet still emits a
    trustworthy `"installed_integrations": []`, so gating would misreport that
    state as `unavailable`. Only unparseable or malformed output falls back to
    None.
    """
    result = subprocess.run(
        [specify, "integration", "status", "--json"],
        cwd=repo_info.worktree_root,
        capture_output=True,
        text=True,
    )
    try:
        doc = json.loads(result.stdout)
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    installed = doc.get("installed_integrations")
    if not isinstance(installed, list):
        return None
    return {i for i in installed if isinstance(i, str)}


def status(repo_info: RepoInfo) -> KitStatus:
    if not os.path.isdir(_specify_dir(repo_info)):
        return KitStatus(claude="not-installed", codex="not-installed")

    specify = _specify_executable()
    if specify is None:
        return KitStatus(claude="unavailable", codex="unavailable")

    installed = _installed_integrations(specify, repo_info)
    if installed is None:
        return KitStatus(claude="unavailable", codex="unavailable")

    return KitStatus(
        claude="installed" if "claude" in installed else "not-installed",
        codex="installed" if "codex" in installed else "not-installed",
    )


def _install_one(specify: str, repo_info: RepoInfo, key: str) -> tuple[bool, str]:
    label = _HARNESS_LABELS[key]
    installed = _installed_integrations(specify, repo_info)
    if installed is not None and key in installed:
        return True, _line(label, "already installed — left unchanged")

    result = subprocess.run(
        [specify, "integration", "install", key],
        cwd=repo_info.worktree_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        return False, _line(label, f"install failed: {detail}")
    return True, _line(label, "installed")


def add(repo_info: RepoInfo) -> KitOpOutcome:
    specify = _specify_executable()
    if specify is None:
        return KitOpOutcome(
            ok=True,
            lines=[
                _line(_HARNESS_LABELS[key], "unavailable (specify CLI not found on PATH)")
                for key in _HARNESS_KEYS
            ],
        )

    lines: list[str] = []
    ok = True

    if not os.path.isdir(_specify_dir(repo_info)):
        result = subprocess.run(
            [
                specify,
                "init",
                "--here",
                "--force",
                "--non-interactive",
                "--integration",
                _BOOTSTRAP_INTEGRATION,
                "--script",
                _BOOTSTRAP_SCRIPT,
            ],
            cwd=repo_info.worktree_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            return KitOpOutcome(
                ok=False,
                lines=[
                    _line(_HARNESS_LABELS[_BOOTSTRAP_INTEGRATION], f"bootstrap failed ('specify init'): {detail}"),
                    _line(
                        _HARNESS_LABELS[[k for k in _HARNESS_KEYS if k != _BOOTSTRAP_INTEGRATION][0]],
                        "not attempted (bootstrap failed)",
                    ),
                ],
            )
        lines.append(_line(_HARNESS_LABELS[_BOOTSTRAP_INTEGRATION], "installed (via 'specify init')"))
        remaining = [k for k in _HARNESS_KEYS if k != _BOOTSTRAP_INTEGRATION]
    else:
        remaining = list(_HARNESS_KEYS)

    for key in remaining:
        key_ok, line = _install_one(specify, repo_info, key)
        ok = ok and key_ok
        lines.append(line)

    return KitOpOutcome(ok=ok, lines=lines)


def remove(repo_info: RepoInfo) -> KitOpOutcome:
    # Only an absent .specify/ is a clean no-op; else report failure.
    if not os.path.isdir(_specify_dir(repo_info)):
        return KitOpOutcome(
            ok=True,
            lines=[_line(_HARNESS_LABELS[key], "already not installed — left unchanged") for key in _HARNESS_KEYS],
        )

    specify = _specify_executable()
    if specify is None:
        return KitOpOutcome(
            ok=False,
            lines=[
                _line(
                    _HARNESS_LABELS[key],
                    "unavailable (specify CLI not found on PATH) — .specify/ is present; "
                    "install the specify CLI to detach it safely, project state left as-is",
                )
                for key in _HARNESS_KEYS
            ],
        )

    installed = _installed_integrations(specify, repo_info)
    if installed is None:
        return KitOpOutcome(
            ok=False,
            lines=[
                _line(
                    _HARNESS_LABELS[key],
                    "unavailable (`specify integration status` failed) — could not safely "
                    "determine what to remove; project state left as-is",
                )
                for key in _HARNESS_KEYS
            ],
        )

    lines: list[str] = []
    ok = True
    for key in _HARNESS_KEYS:
        label = _HARNESS_LABELS[key]
        if key not in installed:
            lines.append(_line(label, "already not installed — left unchanged"))
            continue
        result = subprocess.run(
            [specify, "integration", "uninstall", key],
            cwd=repo_info.worktree_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            ok = False
            lines.append(_line(label, f"uninstall failed: {detail}"))
            continue
        lines.append(_line(label, "removed (.specify/ left in place)"))

    return KitOpOutcome(ok=ok, lines=lines)
