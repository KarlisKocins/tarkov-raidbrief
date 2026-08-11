"""tarkov-data-overlay client - the corrections tarkov.dev's raw data is missing.

tarkov.dev's task data is wrong in ways that matter for availability, and
TarkovTracker does not consume it raw. Their `server/api/tarkov/tasks-core.get.ts`
pipes every response through `applyOverlay()`, which merges
`tarkovtracker-org/tarkov-data-overlay` on top. Without that merge you are
working from data the reference implementation considers broken.

The gap is not marginal. Overlay v1.57 carries:

    traderRequirements  247   loyalty levels absent from the raw data entirely
    name                 88   corrected task names
    disabled             32   tasks that should not be shown at all
    objectives           13   corrected descriptions/counts/maps
    finishRewards        10   (unused here)
    experience            8   corrected XP
    wikiLink              1

The 247 `traderRequirements` are the big one: json.tarkov.dev ships exactly 17
trader requirements across all 510 tasks, so essentially every loyalty-level
gate in the game is missing until this is applied. "A Shooter Born in Heaven"
needs Mechanic LL4; raw data says it needs nothing.

Two structural notes:

* **The overlay is written against the resolved shape**, not the raw JSON API:
  `"name": "Shooter Born in Heaven"` where json.tarkov.dev has the translation
  key `"5c0bde... name"`, and `trader: {id, name}` where the raw file has a
  bare id string. So it must be applied *after* the client's own resolve step,
  which is why this module takes already-transformed tasks.

* **`objectives` corrections are id-keyed patches applied to a list.** The
  overlay sends `{"<objectiveId>": {...}}` against a `[{id, ...}]` array, and
  TarkovTracker's `deepMerge` special-cases exactly that. `merge()` below does
  the same; a plain dict-merge would replace the whole objective list.

`tasksAdd` is deliberately **not** applied. The six additions carry no
`taskRequirements` and no `minPlayerLevel`, so they would appear for every
player at every level forever - the precise failure mode this module exists to
fix. TarkovTracker can afford them because it renders a complete checklist;
a per-raid brief cannot.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger("raidbrief.overlay")

URL = "https://raw.githubusercontent.com/tarkovtracker-org/tarkov-data-overlay/main/dist/overlay.json"
USER_AGENT = "tarkov-raidbrief/1.4 (Home Assistant add-on)"

# TarkovTracker refetches hourly; the file is regenerated a few times a day.
CACHE_TTL = 3600

# Trader ids are permanent, and the overlay identifies traders by id alone.
# Baked in so the GraphQL fallback - which has no id-bearing trader index of
# its own - can resolve them too. Sourced from json.tarkov.dev/regular/traders.
TRADER_IDS = {
    "54cb50c76803fa8b248b4571": "prapor",
    "54cb57776803fa99248b456e": "therapist",
    "579dc571d53a0658a154fbec": "fence",
    "58330581ace78e27b8b10cee": "skier",
    "5935c25fb3acc3127c3d8cd9": "peacekeeper",
    "5a7c2eca46aef81a7ca2145d": "mechanic",
    "5ac3b934156ae10c4430e83c": "ragman",
    "5c0647fdd443bc2504c2d371": "jaeger",
    "638f541a29ffd1183d187f57": "lightkeeper",
    "656f0f98d80a697f855d34b1": "btr-driver",
    "6617beeaa9cfa777ca915b7c": "ref",
    "688246518448b05efd61d461": "mr-kerman",
    "688246958448b05efd61d462": "voevoda",
    "68fe15910f29ba3fdbba9d54": "taran",
    "68fe15990f29ba3fdbba9d55": "radio-station",
    "69e0d6cc77b63940375b9173": "survivor",
}

# Gates that neither tarkov.dev nor the overlay records, verified against the
# wiki. Applied only to tasks the upstream overlay says nothing about, so each
# entry retires itself the moment the overlay learns about the task.
LOCAL_TASK_CORRECTIONS: dict[str, dict] = {
    # A Helping Hand (Mechanic) unlocks the BTR Driver, so getting it wrong
    # cascades: every BTR task hangs off it. Raw data says level 0 and no
    # prerequisites; it is actually level 20 and needs Saving the Mole, which
    # is itself dialogue-unlocked (`otherRequirements`, a field nothing reads).
    "6752f6d83038f7df520c83e8": {
        "minPlayerLevel": 20,
        "taskRequirements": [
            {"task": {"id": "657315e4a6af4ab4b50f3459"}, "status": ["complete"]},
        ],
    },
}


# --------------------------------------------------------------------------
# merging
# --------------------------------------------------------------------------

def _is_id_keyed_list(value) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(v, dict) and "id" in v for v in value)
    )


def _merge_by_id(entries: list[dict], patches: dict) -> list[dict]:
    """Apply `{id: patch}` to a list of `{id: ...}` entries, as deepMerge does."""
    out = []
    for entry in entries:
        patch = patches.get(str(entry.get("id"))) if entry.get("id") is not None else None
        out.append(merge(entry, patch) if isinstance(patch, dict) else entry)
    return out


def merge(target: dict, source: dict) -> dict:
    """Immutable deep merge with TarkovTracker's id-keyed-array special case."""
    out = dict(target)
    for key, sval in source.items():
        tval = out.get(key)
        if isinstance(sval, dict) and isinstance(tval, dict):
            out[key] = merge(tval, sval)
        elif isinstance(sval, dict) and _is_id_keyed_list(tval):
            out[key] = _merge_by_id(tval, sval)
        else:
            out[key] = sval
    return out


# --------------------------------------------------------------------------
# normalisation
# --------------------------------------------------------------------------

def _normalize_trader_requirements(task: dict, traders: dict[str, str]) -> None:
    """Give overlay-shaped trader refs the `normalizedName` the rules match on.

    The overlay writes `{"trader": {"id", "name"}, "value": n}` with no
    `requirementType`; the raw API writes `{"trader": {...}, "requirementType":
    "level"|"reputation", "value": n}`. Both have to come out the same shape.
    """
    requirements = task.get("traderRequirements")
    if not isinstance(requirements, list):
        return

    out = []
    for req in requirements:
        if not isinstance(req, dict):
            continue
        trader = dict(req.get("trader") or {})
        if not trader.get("normalizedName"):
            trader["normalizedName"] = (
                traders.get(str(trader.get("id")))
                or str(trader.get("name") or "").strip().lower().replace(" ", "-")
            )
        out.append({**req, "trader": trader})
    task["traderRequirements"] = out


def _normalize_maps(task: dict, maps: dict[str, dict]) -> None:
    """Overlay objective maps arrive as `{id, name}`; the brief wants normalizedName."""
    for obj in task.get("objectives") or []:
        if not isinstance(obj, dict) or not isinstance(obj.get("maps"), list):
            continue
        out = []
        for entry in obj["maps"]:
            if not isinstance(entry, dict):
                continue
            if entry.get("normalizedName"):
                out.append(entry)
                continue
            known = maps.get(str(entry.get("id"))) or {}
            out.append({
                "name": entry.get("name") or known.get("name") or "?",
                "normalizedName": known.get("normalizedName") or "",
            })
        obj["maps"] = out


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------

class Overlay:
    """Fetches the overlay, caches it on disk, and applies it to a task list.

    Never fatal: if the overlay cannot be fetched and nothing is cached, tasks
    pass through untouched and `status` says so, so the app degrades to raw
    tarkov.dev data with a banner rather than an error page.
    """

    def __init__(self, cache_path: Path, game_mode: str = "regular") -> None:
        self.cache_path = cache_path
        self.game_mode = game_mode
        self.data: dict | None = None
        self.fetched_at: float = 0.0
        self.version: str | None = None
        self.status: str = "missing"  # fresh | cached | stale | missing
        self.error: str | None = None

        self._load_cache()

    # -- transport ---------------------------------------------------------

    async def fetch(self, force: bool = False) -> dict | None:
        if not force and self.data and (time.time() - self.fetched_at) < CACHE_TTL:
            self.status = "cached"
            return self.data

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(
                    URL,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    timeout=httpx.Timeout(30.0, connect=10.0),
                )
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            self.error = str(exc)[:200]
            self.status = "stale" if self.data else "missing"
            log.warning("Could not fetch the data overlay (%s); %s", exc,
                        f"using the cached copy (v{self.version})" if self.data
                        else "serving uncorrected tarkov.dev data")
            return self.data

        # A file without $meta.version is not the overlay; keep what we have
        # rather than wiping good corrections with a redirect or an error page.
        if not isinstance(payload, dict) or not isinstance(payload.get("$meta"), dict) \
                or not payload["$meta"].get("version"):
            self.error = "overlay failed validation ($meta.version missing)"
            self.status = "stale" if self.data else "missing"
            log.warning("Data overlay failed validation; keeping the previous copy")
            return self.data

        self.data = payload
        self.version = str(payload["$meta"]["version"])
        self.fetched_at = time.time()
        self.status = "fresh"
        self.error = None
        self._save_cache()
        log.info("Loaded data overlay v%s (%d task corrections)",
                 self.version, len(payload.get("tasks") or {}))
        return self.data

    # -- application -------------------------------------------------------

    def corrections(self) -> dict[str, dict]:
        """Shared corrections with this game mode's overrides merged on top."""
        if not self.data:
            return {}
        shared = self.data.get("tasks") or {}
        mode = ((self.data.get("modes") or {}).get(self.game_mode) or {}).get("tasks") or {}
        out = {tid: dict(patch) for tid, patch in shared.items() if isinstance(patch, dict)}
        for tid, patch in mode.items():
            if isinstance(patch, dict):
                out[tid] = merge(out[tid], patch) if tid in out else dict(patch)
        return out

    def apply(self, tasks: list[dict], traders: dict[str, str] | None = None,
              maps: dict[str, dict] | None = None) -> list[dict]:
        """Correct, then drop anything the overlay marks disabled.

        `traders` maps trader id -> normalizedName and `maps` maps map id ->
        `{name, normalizedName}`; both fall back to the baked-in table so a
        client without indexes of its own still gets usable output.
        """
        traders = {**TRADER_IDS, **(traders or {})}
        maps = maps or {}
        patches = self.corrections()

        out: list[dict] = []
        applied = dropped = local = 0
        for task in tasks:
            tid = task.get("id")
            patch = patches.get(tid)
            if patch:
                task = merge(task, patch)
                applied += 1
            elif tid in LOCAL_TASK_CORRECTIONS:
                # Only where upstream is silent, so these entries self-retire.
                task = merge(task, LOCAL_TASK_CORRECTIONS[tid])
                local += 1

            if task.get("disabled"):
                dropped += 1
                continue

            _normalize_trader_requirements(task, traders)
            _normalize_maps(task, maps)
            out.append(task)

        if patches:
            log.info("Overlay v%s: corrected %d tasks, dropped %d disabled, "
                     "%d local corrections", self.version, applied, dropped, local)
        else:
            log.warning("No overlay corrections available - trader loyalty gates "
                        "and disabled tasks will not be applied")
        return out

    # -- cache -------------------------------------------------------------

    def _load_cache(self) -> None:
        try:
            blob = json.loads(self.cache_path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(blob.get("overlay"), dict):
            return
        self.data = blob["overlay"]
        self.fetched_at = blob.get("fetched") or 0.0
        self.version = ((self.data.get("$meta") or {}).get("version"))
        self.status = "cached"
        log.info("Restored data overlay v%s from disk", self.version)

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"fetched": self.fetched_at, "overlay": self.data}))
            tmp.replace(self.cache_path)
        except OSError as exc:
            log.warning("Could not persist the data overlay: %s", exc)
