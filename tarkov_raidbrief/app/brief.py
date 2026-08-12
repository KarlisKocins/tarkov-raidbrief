"""Availability rules and carry/loot/do classification - the point of the tool.

Objective `type` strings are the ones tarkov.dev's own resolver switches on
(`resolvers/taskResolver.mjs`), so this list is exhaustive rather than guessed:

    findQuestItem giveQuestItem plantQuestItem  -> TaskObjectiveQuestItem
    findItem giveItem plantItem sellItem haveItem -> TaskObjectiveItem
    mark extract hideoutStation skill traderLevel taskStatus playerLevel
    experience shoot buildWeapon traderStanding useItem -> their own types
    (anything else: visit, dialogue, globalVariable) -> TaskObjectiveBasic

Cross-checked against the live data dump (json.tarkov.dev/regular/tasks, 510
tasks), which contains exactly these types by frequency:

    giveItem 297, visit 210, shoot 200, findItem 152, plantItem 126,
    findQuestItem 114, extract 104, giveQuestItem 103, mark 99,
    buildWeapon 30, plantQuestItem 13, skill 10, traderLevel 10,
    taskStatus 9, useItem 8, sellItem 5, dialogue 1, experience 1,
    globalVariable 1, traderStanding 1

Two facts from that dump drive the rules below:

* `giveItem` is the single most common objective and 237 of its 297 instances
  are `foundInRaid: true` - so it is by far the biggest contributor to BRING
  OUT, and skipping it (as an earlier prototype did) would gut the loot list.
  The 60 non-FiR ones are flea purchases and are correctly ignored.
* `requiredKeys` appears on `visit` 28 times - and `visit` resolves to
  TaskObjectiveBasic, the fallthrough type. Querying requiredKeys on that
  fragment is therefore load-bearing, not defensive.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from .models import ANY_MAP, DEFAULT_TRADER_LEVEL, Brief, MapBrief, TaskBrief

log = logging.getLogger("raidbrief.brief")

# Must be in the rig/container before you deploy.
CARRY_TYPES = {"plantItem", "plantQuestItem", "mark", "buildWeapon", "useItem"}

# Always comes out of the raid.
LOOT_TYPES = {"findItem", "findQuestItem"}

# Comes out of the raid only when it has to be Found In Raid; otherwise it's a
# flea purchase and has no business on a packing list.
CONDITIONAL_LOOT_TYPES = {"giveItem", "giveQuestItem", "haveItem"}

# Nothing to do about these inside a raid. Excluded from the map view unless
# they happen to carry required keys. `dialogue` (talk to a trader) and
# `globalVariable` (an event flag) both fall through to TaskObjectiveBasic and
# so would otherwise be mistaken for raid activity - confirmed present in the
# live data, one of each across the 510 current tasks.
NON_RAID_TYPES = {
    "traderLevel", "traderStanding", "skill", "playerLevel",
    "taskStatus", "experience", "hideoutStation", "sellItem",
    "dialogue", "globalVariable",
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def flatten(value) -> list[dict]:
    """tarkov.dev returns some item fields as [[Item]] and some as [Item]."""
    out: list = []
    for entry in value or []:
        out.extend(entry if isinstance(entry, list) else [entry])
    return [e for e in out if isinstance(e, dict)]


def label(item: dict | None) -> str:
    if not item:
        return "?"
    return item.get("shortName") or item.get("name") or "?"


# tarkov.dev serves each item's inventory icon under its own id. A few quest
# items have none and 404, so the page hides an image that fails to load
# rather than leaving a broken-image glyph in the middle of a checklist.
ICON_URL = "https://assets.tarkov.dev/{}-icon.webp"


def icon(item: dict | None) -> str:
    if not item or not item.get("id"):
        return ""
    return ICON_URL.format(item["id"])


def only(items: list[dict] | None) -> dict | None:
    """The single item behind a label, or None when the label covers several.

    `any_of` renders interchangeable items as 'A / B / C', and no one icon
    stands for that, so those lines stay iconless.
    """
    unique = {label(i): i for i in items or [] if i}
    return next(iter(unique.values())) if len(unique) == 1 else None


def any_of(items: list[dict], limit: int = 4) -> str:
    """Render a list of interchangeable items as 'A / B / C (+2 more)'."""
    names = sorted({label(i) for i in items if i})
    if not names:
        return ""
    if len(names) <= limit:
        return " / ".join(names)
    return f"{' / '.join(names[:limit])} (+{len(names) - limit} more)"


def _counted(text: str, count: int) -> str:
    return f"{text} x{count}" if count and count > 1 else text


def compare(have: float, compare_method: str | None, wanted: float) -> bool:
    """Evaluate one requirement comparison.

    The JSON API writes these as '>=', '<=', '>', '<', '='; GraphQL wrote the
    same thing as 'moreThan'/'lessThan', which are *strict*. A method we do not
    recognise counts as satisfied - a comparison we cannot read must not
    silently hide a task.
    """
    return {
        ">=": lambda: have >= wanted,
        "<=": lambda: have <= wanted,
        ">": lambda: have > wanted,
        "<": lambda: have < wanted,
        "=": lambda: have == wanted,
        "moreThan": lambda: have > wanted,
        "lessThan": lambda: have < wanted,
        "equals": lambda: have == wanted,
    }.get(compare_method or ">=", lambda: True)()


def _symbol(compare_method: str | None) -> str:
    """Comparison symbols. The JSON API sends '>='/'<=' where GraphQL sent
    'moreThan'/'lessThan', so both spellings are mapped."""
    return {
        "moreThan": ">", "lessThan": "<", "equals": "=",
        ">=": "≥", "<=": "≤", ">": ">", "<": "<", "=": "=",
    }.get(compare_method or "", "")


# --------------------------------------------------------------------------
# availability
# --------------------------------------------------------------------------
#
# Mirrors TarkovTracker's `stores/taskAvailability.ts` - specifically
# `createTeamEvaluator`, which is a *recursive, memoised* evaluation, not a
# precomputed edge graph. That distinction is load-bearing:
#
# * A requirement whose status list does NOT include "active" is satisfied by
#   the required task being complete (or failed - see below).
# * A requirement whose status includes "active" means "hand this in instead"
#   (the Chemical Part 4 / Big Customer / Out of Curiosity branch). It is met
#   when the required task is complete OR would itself be *unlockable*, which
#   TarkovTracker answers by re-entering the same evaluation with completed
#   tasks allowed (`isUnlockable`).
#
#   An earlier version of this module approximated that by copying the
#   required task's parent set. It is not equivalent: it silently discards the
#   required task's level, faction, trader-loyalty and trader-unlock gates. A
#   prerequisite with no parents of its own therefore unlocked its children
#   unconditionally, which is how Shipping Delay Parts 1 and 2 appeared for a
#   level 15 account that had never met the BTR Driver.
#
# * A requirement of exactly ["failed"] demands the prerequisite was failed.
#
# TarkovTracker's `setTaskFailed` writes `complete: true, failed: true`, so a
# failed parent satisfies a "complete" edge there - branch children stay
# reachable whichever way the branch went. `statuses()` maps those records to
# "failed", hence "complete" requirements accept "failed" below.
#
# Mutually exclusive branches are not part of TarkovTracker's unlock check:
# the site marks the alternatives failed at completion time, in the write
# path. We are read-only, so the equivalent is derived from `failConditions`
# ("fails when task X is complete"): once any alternative is complete, the
# task is treated as failed even if the tracker never recorded it.

# Traders who do not exist until a specific task is done. There is no field
# for this in tarkov.dev's data - only Jaeger and Ref have a `traderUnlock`
# reward - so TarkovTracker hardcodes it (`utils/constants.ts`,
# TRADER_UNLOCK_TASKS) and enforces it in `meetsTraderUnlockRequirement`.
# Without it every BTR Driver task shows from level 1 on a fresh account.
TRADER_UNLOCK_TASKS: dict[str, str | dict[str, str]] = {
    "lightkeeper": "625d700cc48e6c62a440fab5",   # Getting Acquainted
    "btr-driver": "6752f6d83038f7df520c83e8",    # A Helping Hand
    "ref": {                                     # Easy Money - Part 1
        "regular": "66058cb22cee99303f1ba067",
        "pve": "6834145ebc1f443d7603c8a7",
    },
}

# A "complete" requirement is met by either, per setTaskFailed above.
_DONE = ("complete", "failed")

# Statuses that take a task out of the running for the player's own list.
_CLOSED = ("complete", "failed", "invalid")

_ACTIVE_WORDS = {"active", "accept", "accepted"}
_COMPLETE_WORDS = {"complete", "completed"}


def alternative_tasks(tasks: list[dict]) -> dict[str, set[str]]:
    """Per task id, the ids whose completion fails it (mutually exclusive branches)."""
    alternatives: dict[str, set[str]] = defaultdict(set)
    for task in tasks:
        tid = task.get("id")
        if not tid:
            continue
        for cond in task.get("failConditions") or []:
            if not isinstance(cond, dict) or cond.get("type") != "taskStatus":
                continue
            other = (cond.get("task") or {}).get("id")
            if other and "complete" in {str(s).lower() for s in (cond.get("status") or [])}:
                alternatives[tid].add(other)
    return alternatives


def blocking_trader(task: dict, trader_levels: dict[str, int],
                    trader_reps: dict[str, float] | None = None) -> str | None:
    """The trader whose standing holds this task back, or None if none does.

    Almost every loyalty gate here comes from the data overlay, which omits
    `requirementType` (its entries are all loyalty levels, values 1-4) where
    the raw API sets it to "level" or "reputation".

    **Reputation is only enforced for a trader the player has actually given a
    number for.** TarkovTracker reads standing from the player's trader state,
    which the progress API does not expose, so an unanswered trader is left
    alone rather than judged against an assumed 0.0 - the reputation gates run
    both ways (the Fence "Compensation for Damage" chain wants standing
    *below* a threshold), so a wrong assumption hides tasks in either
    direction. Once the standing panel supplies a value, it is used.

    A trader missing from `trader_levels` counts as DEFAULT_TRADER_LEVEL: the
    panel and the add-on options between them cover every trader that gates
    anything, so an absent one is a trader we cannot ask about.
    """
    reps = trader_reps or {}
    for req in task.get("traderRequirements") or []:
        kind = (req.get("requirementType") or "level").lower()
        trader = (req.get("trader") or {}).get("normalizedName") or ""
        value = req.get("value") or req.get("level") or 0
        if kind == "level":
            if trader_levels.get(trader, DEFAULT_TRADER_LEVEL) < value:
                return trader
        elif kind == "reputation" and trader in reps:
            if not compare(reps[trader], req.get("compareMethod"), value):
                return trader
    return None


class Availability:
    """Answers "can this account do this task now?", memoised across a task set.

    Construct once per brief and call it per task; the two memo tables mean the
    recursion an "active" requirement triggers is paid at most once per task.
    """

    def __init__(self, tasks: list[dict], statuses: dict[str, str], level: int,
                 faction: str, trader_levels: dict[str, int],
                 game_mode: str = "regular",
                 trader_reps: dict[str, float] | None = None) -> None:
        self.by_id = {t["id"]: t for t in tasks if t.get("id")}
        self.statuses = statuses
        self.level = level
        self.faction = faction
        self.trader_levels = trader_levels
        self.trader_reps = trader_reps or {}
        self.game_mode = game_mode
        self.alternatives = alternative_tasks(tasks)

        self._available: dict[str, bool] = {}
        self._unlockable: dict[str, bool] = {}
        # Shared visit sets, exactly as TarkovTracker does it: re-entering a
        # task mid-evaluation means a requirement cycle, which answers False
        # rather than recursing forever.
        self._visiting_available: set[str] = set()
        self._visiting_unlockable: set[str] = set()

    def __call__(self, task: dict | str) -> bool:
        tid = task.get("id") if isinstance(task, dict) else task
        return self._compute(tid, False, self._available, self._visiting_available)

    # -- individual gates --------------------------------------------------

    def _meets_trader_standing(self, task: dict) -> bool:
        return blocking_trader(task, self.trader_levels, self.trader_reps) is None

    def _trader_unlocked(self, task: dict) -> bool:
        entry = TRADER_UNLOCK_TASKS.get((task.get("trader") or {}).get("normalizedName") or "")
        if isinstance(entry, dict):
            entry = entry.get(self.game_mode)
        # An unlock task absent from this dataset cannot be judged, and a task
        # never gates itself - both are TarkovTracker's own guards.
        if not entry or entry == task.get("id") or entry not in self.by_id:
            return True
        return self.statuses.get(entry) in _DONE

    def _requirement_met(self, req: dict) -> bool:
        rid = (req.get("task") or {}).get("id")
        # A requirement pointing at a task that is not in the dataset counts as
        # met. Most of these are quests BSG retired and the overlay disabled -
        # Farming Part 2, Sanitary Standards Part 2, Signal Parts 3 and 4 and
        # 28 others - whose successors are now reachable directly. Requiring a
        # task that cannot be completed because it no longer exists would lock
        # Painkiller, Broadcast - Part 1 and Bad Habit permanently.
        #
        # This is a deliberate deviation: TarkovTracker's hasRequiredTaskStatus
        # only guards a missing `task.id`, not a task missing from the set, so
        # it answers False here.
        if not rid or rid not in self.by_id:
            return True

        wanted = {str(s).lower() for s in (req.get("status") or [])}
        status = self.statuses.get(rid)

        # No status list at all means "complete", per requiresCompletedStatus.
        if (not wanted or wanted & _COMPLETE_WORDS) and status in _DONE:
            return True
        if "failed" in wanted and status == "failed":
            return True
        if wanted & _ACTIVE_WORDS:
            # The progress API never reports "active", so an unstarted task
            # counts as active when it is reachable - TarkovTracker's own
            # fallback, and the reason this needs the full recursion.
            if status == "complete" or self._is_unlockable(rid):
                return True
        return False

    def _is_unlockable(self, tid: str) -> bool:
        return self._compute(tid, True, self._unlockable, self._visiting_unlockable)

    # -- evaluation --------------------------------------------------------

    def _compute(self, tid: str | None, allow_completed: bool,
                 memo: dict[str, bool], visiting: set[str]) -> bool:
        if not tid:
            return False
        cached = memo.get(tid)
        if cached is not None:
            return cached
        if tid in visiting:
            return False
        task = self.by_id.get(tid)
        if task is None:
            return False

        visiting.add(tid)
        try:
            faction = task.get("factionName")
            checks = (
                lambda: allow_completed or self.statuses.get(tid) not in _CLOSED,
                # Prestige tasks are unreachable without a prestige run, and
                # the progress API reports no prestige level at all.
                lambda: not task.get("requiredPrestige"),
                lambda: (task.get("minPlayerLevel") or 0) <= self.level,
                lambda: not faction or faction in ("Any", self.faction),
                lambda: self._meets_trader_standing(task),
                lambda: self._trader_unlocked(task),
                lambda: all(self._requirement_met(r)
                            for r in task.get("taskRequirements") or []),
                lambda: not any(self.statuses.get(a) == "complete"
                                for a in self.alternatives.get(tid) or ()),
            )
            result = all(check() for check in checks)
        finally:
            visiting.discard(tid)

        memo[tid] = result
        return result


# --------------------------------------------------------------------------
# objective parsing
# --------------------------------------------------------------------------

def objective_maps(obj: dict, task: dict) -> list[str]:
    """Every map this objective can be done on, most specific source first."""
    names = [m["name"] for m in (obj.get("maps") or []) if isinstance(m, dict) and m.get("name")]
    if names:
        return sorted(set(names))

    # `zones` and `possibleLocations` are optional query blocks; when present
    # they pin down objectives whose `maps` list came back empty.
    for source, key in ((obj.get("zones"), "map"), (obj.get("possibleLocations"), "map")):
        names = [
            (z or {}).get(key, {}).get("name")
            for z in (source or [])
            if isinstance(z, dict) and isinstance(z.get(key), dict)
        ]
        names = [n for n in names if n]
        if names:
            return sorted(set(names))

    task_map = task.get("map") or {}
    if task_map.get("name"):
        return [task_map["name"]]
    return [ANY_MAP]


def _conditions(obj: dict) -> list[str]:
    """Extra qualifiers worth showing next to a DO line."""
    bits: list[str] = []

    zones = [z for z in (obj.get("zoneNames") or []) if z]
    if zones:
        bits.append("at " + ", ".join(sorted(set(zones))[:3]))

    parts = [p for p in (obj.get("bodyParts") or []) if p]
    if parts:
        bits.append("hit " + "/".join(sorted(set(parts))))

    # `distance` is present on nearly every shoot objective but reads
    # `>= 0` in 178 of 192 real cases, which means "no requirement". Only a
    # positive threshold is worth screen space.
    dist = obj.get("distance")
    if isinstance(dist, dict) and (dist.get("value") or 0) > 0:
        bits.append(f"{_symbol(dist.get('compareMethod'))}{int(dist['value'])}m")

    # shotType is "kill" 198 times out of 200 - the description already says
    # "Eliminate", so only the rare "hit" adds anything.
    shot = obj.get("shotType")
    if shot and shot != "kill":
        bits.append(shot.replace("_", " "))

    not_wearing = flatten(obj.get("notWearing"))
    if not_wearing:
        bits.append(f"without {any_of(not_wearing, 3)}")

    exits = [e for e in (obj.get("exitStatus") or []) if e]
    if exits:
        bits.append("status " + "/".join(sorted(set(exits))))

    exit_name = obj.get("exitName")
    if exit_name:
        bits.append(f"via {exit_name}")

    return bits


def parse_objective(obj: dict) -> dict:
    """Classify one objective into carry-in / keys / bring-out / do."""
    otype = obj.get("type") or ""
    count = obj.get("count") or 1
    carry: list[str] = []
    loot: list[str] = []
    do: list[str] = []
    icons: dict[str, str] = {}

    def named(text: str, item: dict | None) -> str:
        """Remember which icon a finished label wears, and hand the label back
        so this wraps the append rather than needing a line of its own."""
        url = icon(item)
        if text and url:
            icons[text] = url
        return text

    # Keys are a carry-in requirement regardless of what the objective is.
    keys = sorted({named(label(k), k) for k in flatten(obj.get("requiredKeys"))})

    if otype in ("plantItem", "plantQuestItem"):
        items = obj.get("items") or []
        target = any_of(items) or label(obj.get("questItem"))
        if target and target != "?":
            carry.append(named(_counted(target, count), only(items) or obj.get("questItem")))

    elif otype == "mark":
        marker = obj.get("markerItem")
        if marker:
            carry.append(named(label(marker), marker))

    elif otype == "buildWeapon":
        base = obj.get("item")
        if base:
            carry.append(named(f"{label(base)} (build)", base))
        carry += [named(label(p), p) for p in (obj.get("containsAll") or [])]
        for attr in obj.get("attributes") or []:
            req = attr.get("requirement") or {}
            # A zeroed threshold is "unconstrained", same as distance above.
            if attr.get("name") and (req.get("value") or 0) > 0:
                do.append(f"build: {attr['name']} "
                          f"{_symbol(req.get('compareMethod'))}{req['value']}")

    elif otype == "useItem":
        options = obj.get("useAny") or []
        if options:
            carry.append(named(_counted(any_of(options), count), only(options)))

    elif otype in LOOT_TYPES or otype in CONDITIONAL_LOOT_TYPES:
        fir = bool(obj.get("foundInRaid")) or otype in ("findQuestItem", "giveQuestItem")
        items = obj.get("items") or []
        target = any_of(items) or label(obj.get("questItem"))
        if target and target != "?" and (otype in LOOT_TYPES or fir):
            suffix = " (FiR)" if fir else ""
            loot.append(named(f"{_counted(target, count)}{suffix}",
                              only(items) or obj.get("questItem")))

    elif otype == "shoot":
        # The gun and kit are a loadout constraint: they have to be on you.
        carry += [named(f"weapon: {label(w)}", w) for w in flatten(obj.get("usingWeapon"))[:4]]
        carry += [named(f"mod: {label(m)}", m) for m in flatten(obj.get("usingWeaponMods"))[:4]]
        carry += [named(f"wear: {label(g)}", g) for g in flatten(obj.get("wearing"))[:4]]

    description = (obj.get("description") or otype or "objective").strip()
    conditions = _conditions(obj)
    if conditions:
        description = f"{description} ({'; '.join(conditions)})"
    if obj.get("optional"):
        description = f"[optional] {description}"

    do.insert(0, description)

    return {
        "type": otype,
        "carry": carry,
        "keys": keys,
        "loot": loot,
        "do": do,
        "icons": icons,
        "optional": bool(obj.get("optional")),
    }


def is_raid_relevant(info: dict) -> bool:
    """Non-raid objectives only earn a place on a map if they need a key."""
    if info["keys"]:
        return True
    if info["type"] in NON_RAID_TYPES:
        return False
    # A giveItem/haveItem that isn't FiR contributed nothing to any list.
    if info["type"] in CONDITIONAL_LOOT_TYPES and not info["loot"]:
        return False
    return True


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

class _MaxedTraders(dict):
    """Trader levels for the "if standing were no object" pass below."""

    def get(self, key, default=None):  # noqa: ARG002 - every trader is maxed
        return 99


def locked_by_trader(tasks: list[dict], statuses: dict[str, str], level: int, faction: str,
                     trader_levels: dict[str, int], game_mode: str = "regular",
                     trader_reps: dict[str, float] | None = None) -> dict[str, int]:
    """Per trader, how many tasks their standing alone is holding back.

    Answered by running the availability check twice - once as the account
    really is, once with every loyalty gate wide open - and attributing each
    task the second pass gains to the requirement that failed in the first.
    Everything else about those tasks already checks out, so each number is
    what the brief would gain by levelling that one trader, which is what the
    standing panel puts beside the pips.

    A task blocked only *indirectly*, through a prerequisite that is itself
    trader-gated, has no failing requirement of its own and is left uncounted;
    it reappears in the count of whichever trader is actually blocking it.
    """
    strict = Availability(tasks, statuses, level, faction, trader_levels,
                          game_mode, trader_reps)
    lenient = Availability(tasks, statuses, level, faction, _MaxedTraders(), game_mode, {})

    blocked: dict[str, int] = defaultdict(int)
    for task in tasks:
        if strict(task) or not lenient(task):
            continue
        culprit = blocking_trader(task, trader_levels, trader_reps)
        if culprit:
            blocked[culprit] += 1
    return dict(blocked)


def build_brief(tasks: list[dict], statuses: dict[str, str], level: int, faction: str,
                trader_levels: dict[str, int], kappa_only: bool = False,
                game_mode: str = "regular",
                trader_reps: dict[str, float] | None = None) -> list[MapBrief]:
    """Group every available task's objectives by the map they happen on."""
    buckets: dict[str, dict] = defaultdict(
        lambda: {"normalized": "", "tasks": [], "carry": set(), "keys": set(),
                 "loot": set(), "icons": {}}
    )

    is_available = Availability(tasks, statuses, level, faction, trader_levels,
                                game_mode, trader_reps)

    for task in tasks:
        if kappa_only and not task.get("kappaRequired"):
            continue
        if not is_available(task):
            continue

        # A task lands on a map only if it has an objective to do there, and
        # each copy shows that map's objectives alone.
        per_map: dict[str, list[dict]] = defaultdict(list)
        for obj in task.get("objectives") or []:
            info = parse_objective(obj)
            if not is_raid_relevant(info):
                continue
            for map_name in objective_maps(obj, task):
                per_map[map_name].append(info)

        for map_name, infos in per_map.items():
            entry = TaskBrief(
                id=task.get("id") or task.get("normalizedName") or task["name"],
                name=task["name"],
                trader=(task.get("trader") or {}).get("name") or "?",
                min_level=task.get("minPlayerLevel") or 0,
                xp=task.get("experience") or 0,
                kappa=bool(task.get("kappaRequired")),
                wiki=task.get("wikiLink"),
                carry=sorted({c for i in infos for c in i["carry"]}),
                keys=sorted({k for i in infos for k in i["keys"]}),
                loot=sorted({l for i in infos for l in i["loot"]}),
                do=[d for i in infos for d in i["do"]],
                trader_image=(task.get("trader") or {}).get("imageLink") or "",
            )

            bucket = buckets[map_name]
            bucket["tasks"].append(entry)
            bucket["carry"].update(entry.carry)
            bucket["keys"].update(entry.keys)
            bucket["loot"].update(entry.loot)
            for info in infos:
                bucket["icons"].update(info["icons"])

            map_obj = next(
                (m for o in task.get("objectives") or []
                 for m in (o.get("maps") or []) if m.get("name") == map_name),
                task.get("map") or {},
            )
            if not bucket["normalized"]:
                bucket["normalized"] = map_obj.get("normalizedName") or ""

    maps = [
        MapBrief(
            name=name,
            normalized_name=data["normalized"],
            tasks=sorted(data["tasks"], key=lambda t: (-t.xp, t.name)),
            carry=sorted(data["carry"]),
            keys=sorted(data["keys"]),
            loot=sorted(data["loot"]),
            icons=data["icons"],
        )
        for name, data in buckets.items()
    ]

    # Busiest map first; "Any map" is a catch-all, so it goes last whatever its size.
    maps.sort(key=lambda m: (m.name == ANY_MAP, -m.task_count, m.name))
    return maps


def filter_brief(brief: Brief, map_name: str | None) -> Brief:
    """Narrow an already-built brief to one map, matched loosely."""
    if not map_name:
        return brief
    needle = map_name.strip().lower()
    brief.maps = [
        m for m in brief.maps
        if needle in m.name.lower() or needle == m.normalized_name.lower()
    ]
    return brief
