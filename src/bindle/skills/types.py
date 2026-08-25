"""Small shared shapes used by every kit module (software_engineering.py, spec_kit.py).

Deliberately minimal: a per-harness status string and a result type for
add()/remove(). Not a generic provider/component framework — see
docs/DECISIONS.md D035.
"""

from __future__ import annotations

import dataclasses

# Per-harness status vocabulary. Not every kit/harness pair uses every
# state — only the ones with an objective predicate behind them:
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

    `ok` is False only when something that should have worked failed
    unexpectedly — never merely because a harness's provider was
    unavailable (that is reported in `lines`, not treated as failure).
    `lines` are ready-to-print, human-readable result lines, one (or a
    few) per harness.
    """

    ok: bool
    lines: list[str]
