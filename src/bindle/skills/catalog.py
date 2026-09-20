"""The skill-kit catalog: the small, fixed set of kits Bindle knows how to manage.

An in-repo dict, not a registry or remote index (D035). Each entry pairs a
description with the kit module implementing `status()`/`add()`/`remove()`; a
new kit is one more module and one more entry, not a plugin framework.
"""

from __future__ import annotations

import dataclasses

from . import software_engineering, spec_kit


@dataclasses.dataclass(frozen=True)
class KitInfo:
    kit_id: str
    description: str
    source: str
    module: object


CATALOG: dict[str, KitInfo] = {
    "software-engineering": KitInfo(
        kit_id="software-engineering",
        description=(
            "Repo-orientation and slice-review skills for Claude Code and Codex."
        ),
        source="t-step/skills",
        module=software_engineering,
    ),
    "spec-kit": KitInfo(
        kit_id="spec-kit",
        description="GitHub Spec Kit's spec-driven development workflow.",
        source="github/spec-kit",
        module=spec_kit,
    ),
}


class UnknownKitError(ValueError):
    """Raised when a kit ID is not in CATALOG."""


def known_kit_ids() -> list[str]:
    return list(CATALOG)


def require_kit(kit_id: str) -> KitInfo:
    try:
        return CATALOG[kit_id]
    except KeyError:
        known = ", ".join(known_kit_ids())
        raise UnknownKitError(f"unknown kit '{kit_id}' — known kits: {known}") from None
