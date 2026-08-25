"""The `spec-kit` skill kit — GitHub Spec Kit, upstream-owned.

Spec Kit remains upstream-owned (github/spec-kit); this module never
reimplements its installer or copies its skill files by hand
(docs/DECISIONS.md D035). Every mutation and every status read goes
through the native `specify` CLI (verified against the installed
`specify-cli` 1.0.1 this session), exactly like guardrails.py shells out
to install-guardrails.sh's own `--status` mode rather than
reimplementing its predicates in Python.

Verified this session, against a realistic repository snapshot (not an
empty scratch directory): `specify integration install claude` and
`specify integration install codex` coexist safely in one project,
`specify integration status --json` gives a stable, parseable
`installed_integrations` list, and `specify integration uninstall <key>`
removes exactly that integration's own tracked files while leaving the
other integration, `.specify/`, and every unrelated repository file
byte-for-byte untouched (confirmed via sha1 comparison before/after).

Spec Kit's own skills are not self-contained: their `SKILL.md` files
declare `compatibility: "Requires spec-kit project structure with
.specify/ directory"` and shell out to `.specify/scripts/...`. So the
"spec-kit" kit is a Spec Kit *integration*, not a folder of skill files —
if the target repository has no `.specify/` yet, `add()` bootstraps it
via Spec Kit's own `specify init --here`, never by hand-constructing
`.specify/`.

`specify bundle` was evaluated as a possible reusable distribution
mechanism and rejected for this purpose: its own `--help` text describes
it as installing "a bundle's full component set through each primitive's
machinery" over Spec Kit's own primitive types (extensions, presets,
steps, workflows) — composition over Spec Kit's own primitives, not a
generic package manager arbitrary content could ride on.

`remove()` only ever runs `specify integration uninstall claude`/`codex`
— it never deletes `.specify/` itself (no such command exists, and other
integrations or the repository's own use of Spec Kit may still depend on
it) and never touches the `specify` executable.

Provider errors are never silently collapsed into absence. `.specify/`
missing is the one case genuinely equivalent to "not installed" — an
objective filesystem fact needing no `specify` binary to observe. Once
`.specify/` exists, "I could not determine state" (no `specify` binary,
or `specify integration status --json` returning genuinely unparseable
output) is reported as `unavailable`, never silently as `not-installed`.
This is deliberately NOT the same as gating on the command's exit code:
verified this session that `specify integration status --json` exits 1
once every integration has been removed, while still emitting a
well-formed, trustworthy `"installed_integrations": []` — trusting that
body is more truthful than exit-code gating would be, not less. The same
distinction applies to `remove()`: it is only ever a clean
no-op when `.specify/` genuinely does not exist; if `.specify/` exists
but the state or the uninstall itself cannot be safely performed (no
`specify` binary, or the CLI errors), the command reports failure and
leaves `.specify/` and its integrations exactly as they are rather than
claiming "nothing to remove".
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

# The integration bindle uses to bootstrap `.specify/` when it doesn't
# exist yet. Arbitrary but deliberate: something must be picked to
# perform the one-shot `specify init`, and this repository always wants
# both harnesses regardless of which one bootstraps the shared scaffolding.
_BOOTSTRAP_INTEGRATION = "claude"
_BOOTSTRAP_SCRIPT = "sh"


def _line(label: str, text: str) -> str:
    return f"{label:<10}{text}"


def _specify_executable() -> str | None:
    return shutil.which("specify")


def _specify_dir(repo_info: RepoInfo) -> str:
    return os.path.join(repo_info.worktree_root, ".specify")


def _installed_integrations(specify: str, repo_info: RepoInfo) -> set[str] | None:
    """Read-only. Returns None when state genuinely could not be determined
    — the caller must never treat that the same as an empty,
    successfully-read set (see module docstring: provider errors are
    never silently collapsed into "not installed").

    Deliberately does NOT gate on the command's exit code: verified this
    session that `specify integration status --json` exits 1 once every
    integration has been removed (`.specify/integration.json` missing,
    `"status": "error"` in the body) while still emitting a well-formed,
    trustworthy `"installed_integrations": []` — a real, structured
    answer ("genuinely zero installed"), not a failed query. Trusting a
    valid `installed_integrations` list whenever the JSON parses as one
    is MORE truthful than exit-code gating would be here, not less —
    exit-code gating would misreport this legitimate all-removed state as
    `unavailable`. Only unparseable/malformed output (a real "can't
    tell") falls back to None.
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
        # Objective filesystem fact, resolvable with no `specify` binary at
        # all: nothing has been bootstrapped here yet.
        return KitStatus(claude="not-installed", codex="not-installed")

    specify = _specify_executable()
    if specify is None:
        # .specify/ exists, but there's no native interface left to
        # interrogate it with on this machine.
        return KitStatus(claude="unavailable", codex="unavailable")

    installed = _installed_integrations(specify, repo_info)
    if installed is None:
        # .specify/ exists, `specify` is present, but the native status
        # command itself failed or returned something unparseable — a
        # real "can't tell" state, not silent absence.
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
    # .specify/ absent is the one case genuinely equivalent to "nothing
    # to remove" — an objective filesystem fact, checked first and
    # requiring no `specify` binary at all. Once .specify/ exists, a
    # missing/failing `specify` means removal cannot be safely performed
    # and must say so, never silently claim success while leaving
    # `.claude/settings.json`-style drift behind (see module docstring).
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
