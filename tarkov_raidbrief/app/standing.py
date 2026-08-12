"""Where your trader standing lives.

Loyalty level is the one input the tool cannot get from anywhere: tarkov.dev
knows what each task *demands*, and TarkovTracker's `/progress` reports levels,
factions and task records but not trader standing. Before this module it came
from the add-on's Configuration tab alone, which meant restarting the add-on
after every trader level-up.

So the panel writes here instead, and the add-on options become the seed:

* the options are the starting point, used until the panel is touched;
* once it is, `standing.json` in /data holds the answer and outranks them,
  because a value someone set two minutes ago beats one set at install time;
* `reset()` drops the file and the options take over again.

Reputation is stored beside the levels for the handful of tasks that compare
against it - the Fence "Compensation for Damage" chain wants standing *below*
a threshold, so it cannot be inferred from a loyalty level.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import DEFAULT_TRADER_LEVEL

log = logging.getLogger("raidbrief.standing")

# Loyalty tiers run 1-4 for the trading traders; Fence's start at 0. Anything
# outside this is a typo in a hand-edited file or a hostile POST body.
LEVEL_RANGE = (0, 4)
# Fence rep runs about -7..+15 in the live reputationLevels table; the others
# sit well inside that. Wide enough not to clip a real value, narrow enough to
# reject nonsense.
REP_RANGE = (-99.0, 99.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class Standing:
    def __init__(self, defaults: dict[str, int], state_path: Path | None = None) -> None:
        self.defaults = dict(defaults)
        self.state_path = state_path
        self.levels: dict[str, int] = dict(defaults)
        self.reputations: dict[str, float] = {}
        # False until the panel has been used, so the UI can say the numbers
        # are still coming from the add-on options.
        self.customised = False
        self._load()

    # -- reads -------------------------------------------------------------

    def level(self, trader: str) -> int:
        # Same default brief.py applies, so the panel never shows a level the
        # availability check is not the one using.
        return self.levels.get(trader, DEFAULT_TRADER_LEVEL)

    def reputation(self, trader: str) -> float:
        return self.reputations.get(trader, 0.0)

    # -- writes ------------------------------------------------------------

    def update(self, levels: dict[str, int] | None = None,
               reputations: dict[str, float] | None = None) -> None:
        """Apply a partial update - the panel sends one trader at a time."""
        for trader, value in (levels or {}).items():
            try:
                self.levels[str(trader)] = int(_clamp(int(value), *LEVEL_RANGE))
            except (TypeError, ValueError):
                log.warning("Ignoring non-numeric level %r for trader %r", value, trader)

        for trader, value in (reputations or {}).items():
            try:
                self.reputations[str(trader)] = round(
                    _clamp(float(value), *REP_RANGE), 2
                )
            except (TypeError, ValueError):
                log.warning("Ignoring non-numeric reputation %r for trader %r", value, trader)

        self.customised = True
        self._save()

    def reset(self) -> None:
        """Go back to the add-on options and forget the stored overrides."""
        self.levels = dict(self.defaults)
        self.reputations = {}
        self.customised = False
        if self.state_path:
            self.state_path.unlink(missing_ok=True)

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not self.state_path:
            return
        try:
            blob = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(blob, dict):
            return
        # Straight through update() so a hand-edited file gets the same
        # clamping as an HTTP request. The path is parked first because that
        # update would otherwise write the file straight back on startup.
        levels = blob.get("levels") if isinstance(blob.get("levels"), dict) else {}
        reps = blob.get("reputations") if isinstance(blob.get("reputations"), dict) else {}
        state_path, self.state_path = self.state_path, None
        self.update(levels, reps)
        self.state_path = state_path
        log.info("Loaded trader standing from %s", state_path)

    def _save(self) -> None:
        if not self.state_path:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "levels": self.levels,
                "reputations": self.reputations,
            }))
            tmp.replace(self.state_path)
        except OSError as exc:
            log.warning("Could not persist trader standing to %s: %s", self.state_path, exc)
