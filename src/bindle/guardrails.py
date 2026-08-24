"""Guardrail installer access + read-only status inspection.

`installer_path`/`installer_env` locate and configure Bindle's guardrail
installer (install-guardrails.sh) — shared by cli.py's `bindle init`/`bindle
remove`/`bindle migrate-legacy-global` (which mutate) and the
`detect_git_guardrails`/`detect_claude_guardrails` functions below (which
never do).

Detection never reimplements install-guardrails.sh's ownership/intactness
predicates in Python: it shells out to the installer's own `--status` mode,
which computes each layer's state using the exact same functions
(hooks_dir_is_intact, pretooluse_entry_present, valid-json,
read_owned_json, the tracked-file check) that `--apply`/`--uninstall`
already rely on — so `bindle status` can never drift from what `bindle
init`/`bindle remove` actually enforce. See install-guardrails.sh's
detect_git_status/detect_claude_status for the state definitions.

Five states:
  installed      — the complete expected Bindle-owned configuration is
                   present and intact.
  not-installed  — no relevant Bindle configuration exists.
  partial        — recognizable Bindle-owned state exists, but the
                   installation is incomplete.
  conflict       — the integration point is occupied by something that is
                   not Bindle-owned (a foreign core.hooksPath for Git; a
                   tracked, team-shared settings.local.json for Claude).
  invalid        — Bindle-owned-looking state exists but is malformed or
                   broken enough that ownership/operation cannot safely be
                   established (e.g. settings.local.json isn't valid
                   JSON, or the owned-deny bookkeeping file is unreadable
                   as a JSON array).

There is no separate "invalid" state for the Git layer: install-guardrails.sh
never validates the dispatcher's actual script content (only its executable
bit and each hook symlink's target name), so a content-corrupted-but-
correctly-shaped dispatcher is indistinguishable from a good one, and
anything that fails the shape check already reports as "partial" — there is
no remaining, objectively-observable signal that would let this tell
"malformed" apart from "incomplete" for Git.
"""

from __future__ import annotations

import importlib.resources
import os
import subprocess
import sys
from pathlib import Path

from .repo import RepoInfo

GuardrailState = str

_VALID_STATES = frozenset({"installed", "not-installed", "partial", "conflict", "invalid"})


class GuardrailDetectionError(RuntimeError):
    """Raised when guardrail status could not be determined at all."""


def installer_path() -> Path:
    # Package-owned runtime asset (src/bindle/_bin/), included in every
    # wheel/sdist build and resolved through the installed package's own
    # location — not relative to cwd or a Bindle source checkout, so this
    # works identically for `uv run bindle` (editable/dev) and a normally
    # installed `bindle` release alike.
    return Path(str(importlib.resources.files("bindle") / "_bin" / "install-guardrails.sh"))


def installer_env() -> dict[str, str]:
    # The installer's Claude-layer settings.local.json merge (and, for
    # detection, its JSON reads) needs generic JSON structural operations
    # (settings_json.py, package-owned) but no external tool: BINDLE_PYTHON
    # tells it to reuse the exact interpreter already running `bindle`
    # itself, so this works identically whether `bindle` is invoked via
    # `uv run` or from a normally installed package, with no new runtime
    # prerequisite beyond Python itself.
    return {**os.environ, "BINDLE_PYTHON": sys.executable}


def _detect(repo_info: RepoInfo, *, only_flag: str, status_key: str) -> GuardrailState:
    installer = installer_path()
    if not installer.is_file():
        raise GuardrailDetectionError(f"guardrail installer not found at {installer}")

    result = subprocess.run(
        ["bash", str(installer), "--status", only_flag, "--repo", repo_info.worktree_root],
        env=installer_env(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GuardrailDetectionError(f"install-guardrails.sh --status failed: {detail}")

    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key == status_key and value in _VALID_STATES:
            return value

    raise GuardrailDetectionError(
        f"install-guardrails.sh --status produced no recognizable {status_key} line"
    )


def detect_git_guardrails(repo_info: RepoInfo) -> GuardrailState:
    """Read-only: the current Git guardrail layer's state for repo_info."""
    return _detect(repo_info, only_flag="--git-only", status_key="GIT_STATUS")


def detect_claude_guardrails(repo_info: RepoInfo) -> GuardrailState:
    """Read-only: the current Claude guardrail layer's state for repo_info."""
    return _detect(repo_info, only_flag="--claude-only", status_key="CLAUDE_STATUS")
