"""Optional Gemini narration of the brief.

Strictly advisory. This module produces *prose*, and prose never feeds back
into the CARRY IN / KEYS / BRING OUT lists - those come from tarkov.dev data
alone. That separation is the whole safety design: the model is allowed to be
wrong about a route without being able to put a key you don't need onto your
packing checklist.

The model is permitted to use its own Tarkov knowledge (spawns, routes,
extracts), which is what makes the text useful, and is also why the UI labels
the block as AI-written and unverified.

Generation is **on demand only** - a button in the UI, never automatic. Nothing
here runs on startup, on the background poller, or on a page load, so the
add-on cannot quietly spend your quota while you are not looking. Rendering
only ever reads the cache.

Results are cached on a fingerprint of the brief, so asking again for a map
whose outstanding tasks have not changed costs nothing; the button re-serves
the stored text. Changing progress invalidates it naturally.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .models import MapBrief
from .recommend import MapScore

log = logging.getLogger("raidbrief.gemini")

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Cached entries older than this are regenerated even if the brief is unchanged,
# so advice does not silently outlive a game patch.
MAX_AGE = 14 * 24 * 3600

SYSTEM_INSTRUCTION = """\
You are a concise Escape from Tarkov raid advisor. You are writing for a player \
who is standing at their stash choosing a loadout, reading on a phone.

You will be given the player's ACTUAL outstanding task objectives for one map, \
taken from live game data. That data is authoritative.

Rules:
- Never contradict the supplied data. Never invent tasks, items or counts that \
are not listed. If the data says 2 of an item, say 2.
- You MAY add your own knowledge of the map: where things are, sensible routes, \
landmarks, which extracts suit the run. Keep it practical.
- The player CANNOT choose their spawn. Never tell them to spawn anywhere, to \
start from a particular side, or to pick a spawn. If spawn position changes \
the plan, phrase it as a conditional: "if you land near X, do Y first; from \
the other side, reverse it."
- Order the objectives into a route that flows geographically, and say briefly \
why that order.
- Be specific and brief. 120-180 words. No preamble, no headings, no markdown \
lists, no bullet characters. Two or three short paragraphs of plain prose.
- Do not restate the full item list; the player already has it on screen above \
your text. Refer to items naturally in the route.
- If something is genuinely uncertain, say so in a few words rather than \
guessing confidently.
"""

RECOMMEND_INSTRUCTION = """\
You are advising an Escape from Tarkov player which map to run next.

The ranking has ALREADY been decided by the app from live task data. Your job \
is only to explain it in one short, natural sentence (max 30 words). Do not \
re-rank, do not suggest a different map, do not invent numbers. Plain prose, \
no markdown.
"""


@dataclass
class AiText:
    text: str
    generated_at: float
    model: str


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:20]


def _map_key(map_brief: MapBrief, level: int, faction: str) -> str:
    """Cache key: the same map with the same outstanding tasks reuses its text."""
    return _fingerprint("map", map_brief.name, str(level), faction,
                        *sorted(t.id for t in map_brief.tasks))


def _rec_key(real: list[MapScore]) -> str:
    return _fingerprint("rec", real[0].name, *[s.name for s in real[1:3]],
                        str(int(real[0].score)))


class Gemini:
    def __init__(self, api_key: str, model: str, cache_path: Path) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model or "gemini-2.5-flash"
        self.cache_path = cache_path
        self.last_error: str | None = None
        self._cache: dict[str, dict] = self._load()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    # -- cache -------------------------------------------------------------

    def _load(self) -> dict:
        try:
            blob = json.loads(self.cache_path.read_text())
            return blob if isinstance(blob, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache))
            tmp.replace(self.cache_path)
        except OSError as exc:
            log.warning("Could not persist AI cache: %s", exc)

    def get_cached(self, key: str) -> AiText | None:
        entry = self._cache.get(key)
        if not entry or entry.get("model") != self.model:
            return None
        if time.time() - entry.get("generated_at", 0) > MAX_AGE:
            return None
        return AiText(entry["text"], entry["generated_at"], entry["model"])

    # -- generation --------------------------------------------------------

    async def _generate(self, client: httpx.AsyncClient, system: str, prompt: str,
                        max_tokens: int) -> str:
        resp = await client.post(
            ENDPOINT.format(model=self.model),
            params={"key": self.api_key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": max_tokens,
                    "topP": 0.9,
                },
            },
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(60.0, connect=15.0),
        )
        if resp.status_code == 400:
            raise RuntimeError("Gemini rejected the request (400) - check the API key")
        if resp.status_code == 403:
            raise RuntimeError("Gemini denied the key (403) - is the API enabled for it?")
        if resp.status_code == 429:
            raise RuntimeError("Gemini rate limit hit (429) - free tier quota exhausted")
        resp.raise_for_status()

        payload = resp.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            # Usually a safety block or an empty completion.
            raise RuntimeError(f"Gemini returned no candidates: {str(payload)[:200]}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return text

    # -- prompts -----------------------------------------------------------

    @staticmethod
    def _map_prompt(map_brief: MapBrief, level: int, faction: str) -> str:
        lines = [
            f"Map: {map_brief.name}",
            f"Player: level {level} {faction}",
            "",
            "Outstanding objectives on this map:",
        ]
        for task in map_brief.tasks:
            lines.append(f"- {task.name} ({task.trader}, {task.xp:,} XP"
                         f"{', Kappa' if task.kappa else ''}):")
            for objective in task.do:
                lines.append(f"    * {objective}")
            if task.carry:
                lines.append(f"    carry in: {', '.join(task.carry)}")
            if task.keys:
                lines.append(f"    keys: {', '.join(task.keys)}")
            if task.loot:
                lines.append(f"    bring out: {', '.join(task.loot)}")

        if map_brief.carry or map_brief.keys:
            lines.append("")
            lines.append(f"Full carry list: {', '.join(map_brief.carry) or 'nothing'}")
            lines.append(f"Keys: {', '.join(map_brief.keys) or 'none'}")

        lines.append("")
        lines.append("Write the route briefing.")
        return "\n".join(lines)

    @staticmethod
    def _recommend_prompt(best: MapScore, runners_up: list[MapScore]) -> str:
        lines = [f"Chosen map: {best.name}", f"Why it won: {'; '.join(best.reasons)}", ""]
        if runners_up:
            lines.append("Next best:")
            for entry in runners_up[:2]:
                lines.append(f"- {entry.name}: {'; '.join(entry.reasons) or 'little on offer'}")
        lines.append("")
        lines.append("Explain the choice in one sentence.")
        return "\n".join(lines)

    # -- public ------------------------------------------------------------

    async def _run(self, key: str, system: str, prompt: str, max_tokens: int) -> AiText:
        """Generate one piece of text and cache it. Raises on failure."""
        log.info("Generating AI text with %s", self.model)
        async with httpx.AsyncClient() as client:
            text = await self._generate(client, system, prompt, max_tokens)
        entry = {"text": text, "generated_at": time.time(), "model": self.model}
        self._cache[key] = entry
        self._save()
        self.last_error = None
        return AiText(text, entry["generated_at"], self.model)

    async def generate_for_map(self, map_brief: MapBrief, level: int, faction: str,
                               force: bool = False) -> AiText:
        """On demand: one map's route briefing. Costs one API call."""
        key = _map_key(map_brief, level, faction)
        if not force:
            cached = self.get_cached(key)
            if cached:
                return cached
        return await self._run(key, SYSTEM_INSTRUCTION,
                               self._map_prompt(map_brief, level, faction), 600)

    async def generate_for_recommendation(self, scores: list[MapScore],
                                          force: bool = False) -> AiText:
        real = [s for s in scores if s.tasks and s.score > 0]
        if not real:
            raise RuntimeError("nothing to recommend")
        key = _rec_key(real)
        if not force:
            cached = self.get_cached(key)
            if cached:
                return cached
        return await self._run(key, RECOMMEND_INSTRUCTION,
                               self._recommend_prompt(real[0], real[1:3]), 120)

    # Lookups are cache-only: the page never triggers an API call by rendering.
    # Text appears only if it was generated earlier by an explicit request.

    def for_map(self, map_brief: MapBrief, level: int, faction: str) -> AiText | None:
        return self.get_cached(_map_key(map_brief, level, faction))

    def for_recommendation(self, scores: list[MapScore]) -> AiText | None:
        real = [s for s in scores if s.tasks and s.score > 0]
        return self.get_cached(_rec_key(real)) if real else None
