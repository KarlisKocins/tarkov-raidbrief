"""tarkov.dev JSON API client - the primary data source.

The GraphQL API (api.tarkov.dev/graphql) has been returning
`{"errors":["GraphQL server unavailable. Try again later."]}` continuously
since 2026-07-21 (the-hideout/tarkov-api#474, still open). A maintainer's
answer on that issue is unambiguous:

    "The GraphQL API is down for the moment, but you have the Json API who
     alive (https://json.tarkov.dev/endpoints). Tarkov.dev is based on this
     Json API and not on the GraphQL."

So this module is the primary source and `tarkovdev.py` is the fallback, not
the other way round.

Two things make the JSON API harder to consume than GraphQL, and both are
handled here so that the rest of the app sees the GraphQL shape it already
understands:

1. **It is unresolved.** Every reference is a bare id: `trader` is a trader id,
   `items` is a list of item ids, `maps` is a list of map ids. This module
   fetches items/maps/traders and joins them.

2. **It is untranslated.** Text fields hold *translation keys*, not text - a
   task's `name` is literally `"657315ddab5a49b71f098853 name"`. Each endpoint
   has a sibling `<path>_<lang>` file mapping those keys to strings, and the
   rule (copied from the site's own `src/modules/api-request.mjs`) is simply
   `lang[value] ?? value` on the field's own value. No key formats to guess.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from .overlay import Overlay

log = logging.getLogger("raidbrief.tarkovjson")

BASE = "https://json.tarkov.dev"
USER_AGENT = "tarkov-raidbrief/1.1 (Home Assistant add-on)"
CACHE_TTL = 24 * 3600

# json.tarkov.dev speaks "regular" and "pve" like the GraphQL enum did.
DATASETS = ("tasks", "items", "maps", "traders")


class TarkovJsonError(RuntimeError):
    """The JSON API answered, but not with data we can use."""


def _as_list(value) -> list:
    """Endpoints return collections as either a list or an id-keyed object."""
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, dict)]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


class TarkovJson:
    def __init__(self, cache_path: Path, game_mode: str = "regular",
                 language: str = "en") -> None:
        self.cache_path = cache_path
        self.game_mode = game_mode if game_mode in ("regular", "pve") else "regular"
        self.language = language
        self.dropped_blocks: list[str] = []
        self.serving_stale: str | None = None
        # Raw tarkov.dev data is missing nearly every trader loyalty gate; the
        # overlay is what makes availability match TarkovTracker. See overlay.py.
        self.overlay = Overlay(cache_path.with_name("overlay.json"), self.game_mode)

    # -- transport ---------------------------------------------------------

    async def _get(self, client: httpx.AsyncClient, path: str) -> dict:
        resp = await client.get(
            f"{BASE}/{path}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=httpx.Timeout(120.0, connect=15.0),
        )
        resp.raise_for_status()
        return resp.json()

    async def _fetch_all(self) -> tuple[dict[str, dict], dict[str, str]]:
        """Fetch each dataset plus its translation file, concurrently."""
        async with httpx.AsyncClient(follow_redirects=True) as client:
            wanted = [f"{self.game_mode}/{name}" for name in DATASETS]
            wanted += [f"{self.game_mode}/{name}_{self.language}" for name in DATASETS]
            results = await asyncio.gather(
                *(self._get(client, p) for p in wanted), return_exceptions=True
            )

        data: dict[str, dict] = {}
        lang: dict[str, str] = {}
        for path, result in zip(wanted, results):
            name = path.split("/", 1)[1]
            if isinstance(result, BaseException):
                # A missing translation file costs us readable names, not the app.
                if name.endswith(f"_{self.language}"):
                    log.warning("Translation file %s unavailable (%s); "
                                "names may show as raw keys", name, result)
                    continue
                raise TarkovJsonError(f"{path}: {result}") from result
            if name.endswith(f"_{self.language}"):
                lang.update(result.get("data") or {})
            else:
                data[name.split("_")[0]] = result.get("data") or {}

        if "tasks" not in data:
            raise TarkovJsonError("tasks dataset missing from response")
        return data, lang

    # -- joining -----------------------------------------------------------

    def _build_indexes(self, data: dict, lang: dict) -> dict:
        def tr(value):
            """Resolve a translation key to text, exactly as the site does."""
            if isinstance(value, str):
                return lang.get(value, value)
            return value

        items = {}
        for item in _as_list((data.get("items") or {}).get("items")):
            if item.get("id"):
                items[item["id"]] = {
                    "id": item["id"],
                    "name": tr(item.get("name")) or item.get("normalizedName"),
                    "shortName": tr(item.get("shortName")) or None,
                }

        quest_items = {}
        for item in _as_list((data.get("tasks") or {}).get("questItems")):
            if item.get("id"):
                quest_items[item["id"]] = {
                    "id": item["id"],
                    "name": tr(item.get("name")) or item.get("normalizedName"),
                    "shortName": tr(item.get("shortName")) or None,
                }

        maps = {}
        for entry in _as_list((data.get("maps") or {}).get("maps")):
            if entry.get("id"):
                maps[entry["id"]] = {
                    "name": tr(entry.get("name")) or entry.get("normalizedName") or "?",
                    "normalizedName": entry.get("normalizedName") or "",
                }

        traders = {}
        for entry in _as_list(data.get("traders")):
            if entry.get("id"):
                traders[entry["id"]] = {
                    "name": tr(entry.get("name")) or entry.get("normalizedName") or "?",
                    "normalizedName": entry.get("normalizedName") or "",
                }

        log.info("Indexed %d items, %d quest items, %d maps, %d traders",
                 len(items), len(quest_items), len(maps), len(traders))
        return {"tr": tr, "items": items, "questItems": quest_items,
                "maps": maps, "traders": traders}

    @staticmethod
    def _overlay_indexes(idx: dict) -> dict:
        """The id-keyed lookups the overlay needs to resolve its own refs."""
        return {
            "traders": {tid: t.get("normalizedName") or ""
                        for tid, t in (idx.get("traders") or {}).items()},
            "maps": idx.get("maps") or {},
        }

    # -- transformation to the GraphQL shape -------------------------------

    def _transform(self, data: dict, idx: dict) -> list[dict]:
        tr, items, quest_items = idx["tr"], idx["items"], idx["questItems"]
        maps, traders = idx["maps"], idx["traders"]

        def item_ref(value):
            if not isinstance(value, str):
                return None
            return items.get(value) or quest_items.get(value) or {"id": value, "name": value}

        def item_list(values) -> list[dict]:
            out = []
            for value in values or []:
                ref = item_ref(value)
                if ref:
                    out.append(ref)
            return out

        def nested_item_list(values) -> list[list[dict]]:
            """requiredKeys / wearing / usingWeaponMods are [[id]]."""
            out = []
            for group in values or []:
                if isinstance(group, list):
                    out.append(item_list(group))
                elif isinstance(group, str):
                    ref = item_ref(group)
                    if ref:
                        out.append([ref])
            return out

        def map_list(values) -> list[dict]:
            return [maps[v] for v in values or [] if isinstance(v, str) and v in maps]

        out: list[dict] = []
        for task in _as_list((data.get("tasks") or {}).get("tasks")):
            objectives = []
            for obj in task.get("objectives") or []:
                new = {
                    "id": obj.get("id"),
                    "type": obj.get("type"),
                    "description": tr(obj.get("description")),
                    "optional": bool(obj.get("optional")),
                    "count": obj.get("count"),
                    "foundInRaid": obj.get("foundInRaid"),
                    "maps": map_list(obj.get("maps")),
                }

                if obj.get("items"):
                    new["items"] = item_list(obj["items"])
                if obj.get("questItem"):
                    new["questItem"] = item_ref(obj["questItem"])
                if obj.get("markerItem"):
                    new["markerItem"] = item_ref(obj["markerItem"])
                if obj.get("item"):
                    new["item"] = item_ref(obj["item"])
                if obj.get("containsAll"):
                    new["containsAll"] = item_list(obj["containsAll"])
                if obj.get("useAny"):
                    new["useAny"] = item_list(obj["useAny"])
                if obj.get("requiredKeys"):
                    new["requiredKeys"] = nested_item_list(obj["requiredKeys"])

                # shoot
                if obj.get("targetNames"):
                    new["targetNames"] = [tr(t) for t in obj["targetNames"]]
                for key in ("shotType", "zoneNames", "timeFromHour", "timeUntilHour"):
                    if obj.get(key) is not None:
                        new[key] = obj[key]
                if obj.get("bodyParts"):
                    new["bodyParts"] = [tr(b) for b in obj["bodyParts"]]
                if obj.get("distance"):
                    new["distance"] = obj["distance"]
                if obj.get("usingWeapon"):
                    new["usingWeapon"] = item_list(obj["usingWeapon"])
                if obj.get("usingWeaponMods"):
                    new["usingWeaponMods"] = nested_item_list(obj["usingWeaponMods"])
                if obj.get("wearing"):
                    new["wearing"] = nested_item_list(obj["wearing"])
                if obj.get("notWearing"):
                    new["notWearing"] = item_list(obj["notWearing"])

                # extract
                if obj.get("exitStatus"):
                    new["exitStatus"] = [tr(s) for s in obj["exitStatus"]]
                if obj.get("exitName"):
                    new["exitName"] = tr(obj["exitName"])

                # buildWeapon: dict of name -> {value, compareMethod}
                attributes = obj.get("buildAttributes")
                if isinstance(attributes, dict):
                    new["attributes"] = [
                        {"name": name, "requirement": req}
                        for name, req in attributes.items()
                        if isinstance(req, dict) and req.get("value")
                    ]

                # zones / possibleLocations only matter as a map fallback
                zones = [
                    {"map": maps[z["map"]]}
                    for z in obj.get("zones") or []
                    if isinstance(z, dict) and z.get("map") in maps
                ]
                if zones:
                    new["zones"] = zones
                locations = [
                    {"map": maps[p["map"]]}
                    for p in obj.get("possibleLocations") or []
                    if isinstance(p, dict) and p.get("map") in maps
                ]
                if locations:
                    new["possibleLocations"] = locations

                objectives.append(new)

            out.append({
                "id": task.get("id"),
                "name": tr(task.get("name")) or task.get("normalizedName") or "?",
                "normalizedName": task.get("normalizedName"),
                "experience": task.get("experience"),
                "minPlayerLevel": task.get("minPlayerLevel"),
                "kappaRequired": task.get("kappaRequired"),
                "lightkeeperRequired": task.get("lightkeeperRequired"),
                # Set on the prestige-only variants of New Beginning et al.
                # Nothing in the progress API reports a prestige level, so
                # brief.py treats any value here as unreachable.
                "requiredPrestige": task.get("requiredPrestige"),
                "factionName": task.get("factionName"),
                "wikiLink": task.get("wikiLink"),
                "trader": traders.get(task.get("trader"), {"name": "?", "normalizedName": ""}),
                "map": maps.get(task.get("map")),
                "taskRequirements": [
                    {"task": {"id": req.get("task")}, "status": req.get("status") or []}
                    for req in task.get("taskRequirements") or []
                    if isinstance(req, dict)
                ],
                # Only the taskStatus conditions matter downstream: "fails when
                # task X is complete" marks X as a mutually exclusive branch.
                "failConditions": [
                    {"type": "taskStatus", "task": {"id": cond.get("task")},
                     "status": cond.get("status") or []}
                    for cond in task.get("failConditions") or []
                    if isinstance(cond, dict) and cond.get("type") == "taskStatus"
                ],
                "traderRequirements": [
                    {
                        "trader": {
                            "normalizedName":
                                traders.get(req.get("trader"), {}).get("normalizedName", "")
                        },
                        "requirementType": req.get("requirementType"),
                        "compareMethod": req.get("compareMethod"),
                        "value": req.get("value"),
                    }
                    for req in task.get("traderRequirements") or []
                    if isinstance(req, dict)
                ],
                "objectives": objectives,
            })
        return out

    # -- public ------------------------------------------------------------

    async def get_tasks(self, force: bool = False) -> tuple[list[dict], float, list[str]]:
        # The overlay is fetched on its own hourly clock so a correction lands
        # without waiting out the 24h task TTL; the cache below therefore holds
        # uncorrected tasks and the merge happens on every call.
        await self.overlay.fetch(force=force)

        cached = self._read_cache()
        if not force and cached and time.time() - cached["fetched"] < CACHE_TTL:
            return self._corrected(cached), cached["fetched"], []

        self.serving_stale = None
        try:
            data, lang = await self._fetch_all()
            idx = self._build_indexes(data, lang)
            tasks = self._transform(data, idx)
            if not tasks:
                raise TarkovJsonError("transformed to zero tasks")
        except (httpx.HTTPError, TarkovJsonError, ValueError, KeyError, TypeError) as exc:
            if cached:
                log.warning("json.tarkov.dev unreachable (%s); serving cache from %s", exc,
                            time.strftime("%Y-%m-%d %H:%M", time.localtime(cached["fetched"])))
                self.serving_stale = str(exc)[:200]
                return self._corrected(cached), cached["fetched"], []
            raise TarkovJsonError(f"json.tarkov.dev unavailable and no cache: {exc}") from exc

        fetched = time.time()
        blob = {"tasks": tasks, "fetched": fetched, **self._overlay_indexes(idx)}
        self._write_cache(blob)
        log.info("Loaded %d tasks from json.tarkov.dev (mode=%s, lang=%s)",
                 len(tasks), self.game_mode, self.language)
        return self._corrected(blob), fetched, []

    def _corrected(self, blob: dict) -> list[dict]:
        return self.overlay.apply(blob["tasks"], blob.get("traders"), blob.get("maps"))

    # -- cache -------------------------------------------------------------

    def _read_cache(self) -> dict | None:
        try:
            blob = json.loads(self.cache_path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(blob.get("tasks"), list) or not blob["tasks"]:
            return None
        # "json-v2" caches carry the trader/map id indexes the overlay needs;
        # the bump discards pre-overlay caches instead of half-correcting them.
        if blob.get("game_mode") != self.game_mode or blob.get("source") != "json-v2":
            return None
        blob.setdefault("fetched", 0.0)
        return blob

    def _write_cache(self, blob: dict) -> None:
        payload = {"game_mode": self.game_mode, "source": "json-v2", **blob}
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self.cache_path)
        except OSError as exc:
            log.warning("Could not write task cache to %s: %s", self.cache_path, exc)
