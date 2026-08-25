"""Skill kits: repository-scoped adoption of agent-facing skill collections.

A skill kit is a named collection of agent-facing skills/capabilities
Bindle can make available to Claude Code and Codex through each harness's
own native mechanism (docs/DECISIONS.md D035). This package is the third
lifecycle specimen after repo-local guardrails and Projectmem — see
`catalog.py` for the fixed, tiny set of known kits and `config.py` for
where a repository's desired kits are recorded.
"""

from __future__ import annotations

from .catalog import CATALOG, KitInfo, UnknownKitError, known_kit_ids, require_kit
from .config import add_desired_kit, read_desired_kits, remove_desired_kit
from .types import KitOpOutcome, KitStatus

__all__ = [
    "CATALOG",
    "KitInfo",
    "KitOpOutcome",
    "KitStatus",
    "UnknownKitError",
    "add_desired_kit",
    "known_kit_ids",
    "read_desired_kits",
    "remove_desired_kit",
    "require_kit",
]
