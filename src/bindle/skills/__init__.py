"""Skill kits: repository-scoped adoption of agent-facing skill collections.

A kit is a named collection of agent-facing skills Bindle makes available to
Claude Code and Codex through each harness's native mechanism (D035).
`catalog.py` holds the fixed set of known kits; `config.py` records a
repository's desired kits.
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
