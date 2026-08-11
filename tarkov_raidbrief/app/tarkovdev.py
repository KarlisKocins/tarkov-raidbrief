"""tarkov.dev GraphQL client with a composable query and a disk cache.

The schema moves between patches, so the query is assembled from named blocks.
If the full query is rejected we drop one optional block at a time and retry,
logging exactly which block went. Losing `requiredKeys` costs us the KEYS
section; it must never cost us the whole app.

Schema facts this module is built against (verified against
the-hideout/tarkov-api `schema-static.mjs`):

* `tasks(faction, lang, gameMode, limit, offset)` - `GameMode` is `regular|pve`.
* `requiredKeys: [[Item]]` lives on the CONCRETE objective types, not on the
  `TaskObjective` interface. Asking for it at interface level fails the whole
  query - which is why it must go inside each inline fragment.
* It is present on Basic, Extract, Item, Mark, QuestItem, Shoot and UseItem,
  and absent on BuildItem, HideoutStation, PlayerLevel, Skill, TaskStatus,
  TraderLevel, TraderStanding and Experience.
* `Task.neededKeys` is deprecated in favour of the above.
* `TaskObjectiveItem.item` is deprecated in favour of `items`.
* `wearing`/`usingWeaponMods` are `[[Item]]`; `usingWeapon`/`notWearing` are `[Item]`.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger("raidbrief.tarkovdev")

ENDPOINT = "https://api.tarkov.dev/graphql"
CACHE_TTL = 24 * 3600
USER_AGENT = "tarkov-raidbrief/1.0 (Home Assistant add-on)"

# Objective types whose concrete GraphQL type exposes requiredKeys.
_KEYED = ("Basic", "Extract", "Item", "Mark", "QuestItem", "Shoot", "UseItem")

# Optional blocks, listed in the order they get sacrificed. Least valuable first;
# requiredKeys is last because the KEYS panel is the whole point of the carry list.
DEGRADE_ORDER = ("questItemLocations", "shootDetail", "zones", "requiredKeys")
ALL_BLOCKS = frozenset(DEGRADE_ORDER)


def _keys(enabled: frozenset[str], concrete: str) -> str:
    if "requiredKeys" not in enabled or concrete not in _KEYED:
        return ""
    return "requiredKeys { id name shortName }"


def build_query(enabled: frozenset[str] = ALL_BLOCKS, game_mode: str | None = None) -> str:
    """Assemble the tasks query from the currently-enabled optional blocks."""
    zones = "zones { map { name normalizedName } }" if "zones" in enabled else ""
    locations = (
        "possibleLocations { map { name normalizedName } }"
        if "questItemLocations" in enabled
        else ""
    )
    shoot_detail = (
        """
        shotType
        bodyParts
        distance { compareMethod value }
        usingWeapon { id name shortName }
        usingWeaponMods { id name shortName }
        wearing { id name shortName }
        notWearing { id name shortName }
        """
        if "shootDetail" in enabled
        else ""
    )

    arg = f"(gameMode: {game_mode})" if game_mode else ""

    # TaskObjectiveBasic has nothing beyond the interface fields except the two
    # optional blocks, so once both are dropped the fragment would be an empty
    # selection set - a syntax error that would take the whole query down at
    # the very last rung of the fallback ladder. Omit it instead.
    basic = (
        f"... on TaskObjectiveBasic {{ {_keys(enabled, 'Basic')} {zones} }}"
        if ("requiredKeys" in enabled or "zones" in enabled)
        else ""
    )

    return f"""
{{
  tasks{arg} {{
    id
    name
    normalizedName
    experience
    minPlayerLevel
    kappaRequired
    lightkeeperRequired
    factionName
    wikiLink
    trader {{ name normalizedName }}
    map {{ name normalizedName }}
    taskRequirements {{ task {{ id name }} status }}
    traderRequirements {{ trader {{ normalizedName }} requirementType compareMethod value }}
    objectives {{
      id
      type
      description
      optional
      maps {{ name normalizedName }}

      {basic}

      ... on TaskObjectiveItem {{
        items {{ id name shortName }}
        count
        foundInRaid
        dogTagLevel
        {_keys(enabled, 'Item')}
        {zones}
      }}

      ... on TaskObjectiveQuestItem {{
        questItem {{ id name shortName }}
        count
        {_keys(enabled, 'QuestItem')}
        {zones}
        {locations}
      }}

      ... on TaskObjectiveMark {{
        markerItem {{ id name shortName }}
        {_keys(enabled, 'Mark')}
        {zones}
      }}

      ... on TaskObjectiveBuildItem {{
        item {{ id name shortName }}
        containsAll {{ id name shortName }}
        containsCategory {{ id name }}
        attributes {{ name requirement {{ compareMethod value }} }}
      }}

      ... on TaskObjectiveShoot {{
        targetNames
        count
        zoneNames
        {shoot_detail}
        {_keys(enabled, 'Shoot')}
        {zones}
      }}

      ... on TaskObjectiveExtract {{
        exitStatus
        exitName
        zoneNames
        count
        {_keys(enabled, 'Extract')}
      }}

      ... on TaskObjectiveUseItem {{
        useAny {{ id name shortName }}
        count
        zoneNames
        {_keys(enabled, 'UseItem')}
        {zones}
      }}

      ... on TaskObjectivePlayerLevel {{ playerLevel }}
      ... on TaskObjectiveTraderLevel {{ trader {{ name normalizedName }} level }}
      ... on TaskObjectiveTraderStanding {{
        trader {{ name normalizedName }} compareMethod value
      }}
      ... on TaskObjectiveSkill {{ skillLevel {{ name level }} }}
      ... on TaskObjectiveTaskStatus {{ task {{ id name }} status }}
      ... on TaskObjectiveExperience {{ count healthEffect {{ time {{ compareMethod value }} }} }}
    }}
  }}
}}
"""


INTROSPECTION = """
{
  objective: __type(name: "TaskObjectiveItem") { fields { name } }
  iface: __type(name: "TaskObjective") { fields { name } }
  query: __type(name: "Query") { fields(includeDeprecated: false) { name args { name } } }
}
"""


class TarkovDevError(RuntimeError):
    """The API answered, but not with data we can use."""


class TarkovDev:
    def __init__(self, cache_path: Path, game_mode: str = "regular") -> None:
        self.cache_path = cache_path
        self.game_mode = game_mode
        self.dropped_blocks: list[str] = []
        self.supports_game_mode: bool | None = None
        # Set whenever we served the cache because the API would not answer, so
        # the UI can say so even while the cache is still inside its TTL.
        self.serving_stale: str | None = None
        self._introspected = False

    # -- transport ---------------------------------------------------------

    async def _post(self, client: httpx.AsyncClient, query: str) -> dict:
        resp = await client.post(
            ENDPOINT,
            json={"query": query},
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            timeout=httpx.Timeout(60.0, connect=15.0),
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise TarkovDevError(json.dumps(payload["errors"])[:500])
        data = payload.get("data")
        if not data:
            raise TarkovDevError("response contained no data")
        return data

    async def introspect(self, client: httpx.AsyncClient) -> None:
        """Log which optional fields the live schema actually has. Best effort."""
        if self._introspected:
            return
        self._introspected = True
        try:
            data = await self._post(client, INTROSPECTION)
        except (httpx.HTTPError, TarkovDevError, ValueError) as exc:
            log.warning("Schema introspection unavailable (%s); "
                        "relying on the query fallback ladder instead.", exc)
            return

        obj_fields = {f["name"] for f in (data.get("objective") or {}).get("fields") or []}
        iface_fields = {f["name"] for f in (data.get("iface") or {}).get("fields") or []}
        query_fields = {
            f["name"]: {a["name"] for a in f.get("args") or []}
            for f in (data.get("query") or {}).get("fields") or []
        }

        self.supports_game_mode = "gameMode" in query_fields.get("tasks", set())
        log.info(
            "Schema introspection: requiredKeys on TaskObjectiveItem=%s, "
            "on TaskObjective interface=%s, tasks(gameMode:)=%s",
            "requiredKeys" in obj_fields,
            "requiredKeys" in iface_fields,
            self.supports_game_mode,
        )
        if "requiredKeys" in iface_fields:
            log.info("Interface-level requiredKeys is available - the per-fragment "
                     "form we send remains valid either way.")

    # -- fetching ----------------------------------------------------------

    async def _fetch_with_fallback(self, client: httpx.AsyncClient) -> tuple[list[dict], list[str]]:
        enabled = set(ALL_BLOCKS)
        dropped: list[str] = []
        use_game_mode = self.supports_game_mode is not False

        while True:
            mode = self.game_mode if use_game_mode else None
            try:
                data = await self._post(client, build_query(frozenset(enabled), mode))
                if dropped:
                    log.warning("Task query succeeded after dropping: %s", ", ".join(dropped))
                return data["tasks"], dropped
            except TarkovDevError as exc:
                # A gameMode-less schema is the one failure that isn't a block.
                if use_game_mode and "gameMode" in str(exc):
                    log.warning("Schema rejected tasks(gameMode:); retrying without it. "
                                "Progress will still be filtered for %s.", self.game_mode)
                    use_game_mode = False
                    continue

                nxt = next((b for b in DEGRADE_ORDER if b in enabled), None)
                if nxt is None:
                    raise
                enabled.discard(nxt)
                dropped.append(nxt)
                log.warning("Task query rejected (%s); retrying without block %r", exc, nxt)

    async def get_tasks(self, force: bool = False) -> tuple[list[dict], float, list[str]]:
        """Return (tasks, fetched_at, dropped_blocks), preferring a fresh fetch.

        Falls back to the on-disk cache - however stale - when the API is
        unreachable, so a patch-day outage degrades to yesterday's data with a
        banner rather than an error page.
        """
        cached = self._read_cache()
        if not force and cached and time.time() - cached["fetched"] < CACHE_TTL:
            self.dropped_blocks = cached.get("dropped", [])
            return cached["tasks"], cached["fetched"], self.dropped_blocks

        self.serving_stale = None

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                await self.introspect(client)
                tasks, dropped = await self._fetch_with_fallback(client)
        except (httpx.HTTPError, TarkovDevError, ValueError, KeyError) as exc:
            if cached:
                log.warning("tarkov.dev unreachable (%s); serving cache from %s",
                            exc, time.strftime("%Y-%m-%d %H:%M", time.localtime(cached["fetched"])))
                self.dropped_blocks = cached.get("dropped", [])
                self.serving_stale = str(exc)[:200]
                return cached["tasks"], cached["fetched"], self.dropped_blocks
            raise TarkovDevError(f"tarkov.dev unreachable and no cache available: {exc}") from exc

        fetched = time.time()
        self.dropped_blocks = dropped
        self._write_cache(tasks, fetched, dropped)
        log.info("Fetched %d tasks from tarkov.dev (mode=%s)", len(tasks), self.game_mode)
        return tasks, fetched, dropped

    # -- cache -------------------------------------------------------------

    def _read_cache(self) -> dict | None:
        try:
            blob = json.loads(self.cache_path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(blob.get("tasks"), list) or not blob["tasks"]:
            return None
        # A cache built for the other game mode is not ours to serve.
        if blob.get("game_mode") != self.game_mode:
            return None
        blob.setdefault("fetched", 0.0)
        return blob

    def _write_cache(self, tasks: list[dict], fetched: float, dropped: list[str]) -> None:
        payload = {
            "fetched": fetched,
            "game_mode": self.game_mode,
            "dropped": dropped,
            "tasks": tasks,
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self.cache_path)  # atomic: a killed container can't half-write it
        except OSError as exc:
            log.warning("Could not write task cache to %s: %s", self.cache_path, exc)
