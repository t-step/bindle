"""Small shared shapes used by every kit module (software_engineering.py, spec_kit.py).

Deliberately minimal, not a provider/component framework (D035).
"""

from __future__ import annotations

import dataclasses

# Per-harness statuses; a pair uses only those with an objective predicate:
#   installed      the projection is present and usable
#   not-installed  nothing is present
#   partial        some but not all of the kit's expected content is present
#   conflict       the integration point is occupied by something that
#                  isn't this kit's own projection
#   unavailable    the required native provider (CLI/source) could not be
#                  resolved on this machine, so state can't even be checked
HarnessState = str


@dataclasses.dataclass(frozen=True)
class KitStatus:
    claude: HarnessState
    codex: HarnessState


@dataclasses.dataclass(frozen=True)
class KitOpOutcome:
    """Result of add()/remove() for one kit.

    `ok` is False only on an unexpected failure, never merely because a
    harness's provider was unavailable (that is reported in `lines`). `lines`
    are ready-to-print result lines.
    """

    ok: bool
    lines: list[str]
