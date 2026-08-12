"""Where your trader standing lives, and the estimate that fills it in for you.

Loyalty level is the one input the tool cannot read directly: tarkov.dev knows
what each task *demands*, and TarkovTracker's `/progress` reports levels,
factions and task records but not trader standing. Before this module it came
from the add-on's Configuration tab alone, which meant restarting the add-on
after every trader level-up.

It can, however, be *estimated*. Nearly every point of PMC trader reputation
comes from handing in tasks, and the task data says exactly how much each one
pays (`finishRewards.traderStanding`, present on 366 of the 516 live tasks).
Summing that over the tasks TarkovTracker says you have completed gives a
reputation figure, and each trader's own loyalty tiers say what reputation and
player level unlock which level. That is `derive_reputations` and
`derive_level` below.

The estimate is deliberately **advisory only** - shown in the panel with an
Apply button, never fed straight into availability. Three things it cannot see:

* `requiredCommerce`. Loyalty needs roubles spent as well as reputation, and
  nothing in either API reports it, so a derived level is an upper bound.
* Game edition starting bonuses (EOD and Unheard begin above zero).
* Fence, whose standing moves on scav karma - kills, insurance returns, extract
  behaviour - and barely at all on tasks. It is excluded outright.

Enforcing a number with those holes in it would hide tasks on arithmetic
nobody checked, which is the exact failure this add-on's overlay exists to
prevent. Suggesting one costs nothing and saves the player ten fields of typing.

The panel writes here, and the add-on options become the seed:

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
from collections import defaultdict
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


# Traders whose reputation does not come from handing in tasks. Fence moves on
# scav karma, so a quest-derived figure for them would be confidently wrong -
# and their rep gates run *downwards* (the "Compensation for Damage" chain
# wants standing below a threshold), so a wrong number there hides tasks.
NO_QUEST_REP = frozenset({"fence"})


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def derive_reputations(tasks: list[dict], statuses: dict[str, str]) -> dict[str, float]:
    """Estimate each trader's reputation from the tasks already handed in.

    Completed tasks pay their `rewardStanding`; failed ones pay the
    `failStanding` penalty instead, which is how the chains you can fail
    (Fence's, and the Chemical branch) land the right way round. Tasks the
    tracker has not recorded contribute nothing, so a fresh account estimates
    at zero across the board - correct, barring the edition bonus noted above.
    """
    reps: dict[str, float] = defaultdict(float)
    for task in tasks:
        status = statuses.get(task.get("id") or "")
        if status == "complete":
            rewards = task.get("rewardStanding") or []
        elif status == "failed":
            rewards = task.get("failStanding") or []
        else:
            continue
        for reward in rewards:
            trader = reward.get("trader")
            if trader and trader not in NO_QUEST_REP:
                try:
                    reps[trader] += float(reward.get("standing") or 0)
                except (TypeError, ValueError):
                    continue
    # Every trader a completed task touched is reported, including one whose
    # gains and losses cancel out: a net of zero is a reputation we computed,
    # not a reputation we failed to compute, and the difference is what the
    # panel shows. Traders no completed task mentions are simply absent, and
    # get no estimate at all. `+ 0.0` normalises round()'s negative zero, which
    # would otherwise print as "-0.00".
    #
    # Rounded to the two decimals the game shows, which are also the two the
    # panel's rep field round-trips, so applying an estimate is idempotent.
    return {trader: round(value, 2) + 0.0 for trader, value in reps.items()}


def derive_level(levels: list, reputation: float, player_level: int) -> int:
    """The highest loyalty tier this reputation and player level could unlock.

    `levels` is a trader's tier list - objects with `.level`, `.reputation` and
    `.player_level`. An upper bound, because `requiredCommerce` is invisible to
    both APIs: a player with the reputation but not the spend sits one tier
    lower than this says, which is why the caller offers it rather than
    applying it.
    """
    best = 0
    for tier in levels or []:
        if reputation + 1e-9 >= (tier.reputation or 0) and player_level >= (tier.player_level or 0):
            best = max(best, tier.level)
    return best


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
