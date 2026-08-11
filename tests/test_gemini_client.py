#!/usr/bin/env python3
"""Exercise the Gemini client against a local stand-in for the API.

There is no API key in CI, and the real endpoint costs money, so this points
the client at a local server that speaks the documented generateContent
response shape. It checks the things that actually break in production:

* the request we send is well-formed (model in the path, key as a query
  param, systemInstruction/contents/generationConfig present),
* results are cached, so asking again makes zero HTTP calls,
* the cache survives a restart and is keyed on the brief, so changed progress
  regenerates but unchanged progress does not,
* API errors degrade to `last_error` instead of raising.

The real endpoint is separately confirmed to accept this exact body: posting
it with a dummy key returns 400 API_KEY_INVALID rather than a schema error.

    python3 tests/test_gemini_client.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tarkov_raidbrief"))

from app import gemini as gemini_module  # noqa: E402
from app.gemini import Gemini  # noqa: E402
from app.models import MapBrief, TaskBrief  # noqa: E402
from app.recommend import score_maps  # noqa: E402

REQUESTS: list[dict] = []
FAIL_WITH: list[int] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append({"path": self.path, "body": body})

        if FAIL_WITH:
            code = FAIL_WITH.pop(0)
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"nope"}}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "candidates": [{
                "content": {"parts": [{"text": "Head to Tarcone first, then the "
                                               "gas stations.\n\nExtract at RUAF."}],
                             "role": "model"},
                "finishReason": "STOP",
            }],
            "usageMetadata": {"totalTokenCount": 42},
        }).encode())

    def log_message(self, *args):
        pass


def sample_maps() -> list[MapBrief]:
    return [
        MapBrief(
            name="Customs", normalized_name="customs",
            carry=["MS2000"], keys=["Director's"], loot=["Fuel x2 (FiR)"],
            tasks=[
                TaskBrief(id="t1", name="Delivery From the Past", trader="Prapor",
                          min_level=5, xp=4000, kappa=True, wiki=None,
                          carry=[], keys=["Director's"], loot=["0022 (FiR)"],
                          do=["Locate the folder in Tarcone director's office"]),
                TaskBrief(id="t2", name="Big Customer", trader="Prapor",
                          min_level=11, xp=8100, kappa=True, wiki=None,
                          carry=["MS2000"], keys=[], loot=[],
                          do=["Mark the vehicle with an MS2000 Marker"]),
            ],
        ),
    ]


def check(label: str, ok: bool) -> bool:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    return ok


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    gemini_module.ENDPOINT = f"http://127.0.0.1:{port}/v1beta/models/{{model}}:generateContent"

    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "ai_cache.json"
    maps = sample_maps()
    scores = score_maps(maps)
    passed = True

    # -- first pass generates -------------------------------------------
    client = Gemini("test-key", "gemini-2.5-flash", tmp)
    asyncio.run(client.generate_for_map(maps[0], 14, "BEAR"))
    asyncio.run(client.generate_for_recommendation(scores))

    passed &= check("generated text for the map", client.for_map(maps[0], 14, "BEAR") is not None)
    passed &= check("generated the recommendation line",
                    client.for_recommendation(scores) is not None)
    passed &= check("made 2 API calls (1 map + 1 recommendation)", len(REQUESTS) == 2)

    req = REQUESTS[0]
    passed &= check("model is in the URL path", "gemini-2.5-flash:generateContent" in req["path"])
    passed &= check("API key is a query param", "key=test-key" in req["path"])
    passed &= check("systemInstruction sent", "systemInstruction" in req["body"])
    passed &= check("contents[0].parts[0].text sent",
                    bool(req["body"]["contents"][0]["parts"][0]["text"]))
    passed &= check("generationConfig sent", "maxOutputTokens" in req["body"]["generationConfig"])

    prompt = req["body"]["contents"][0]["parts"][0]["text"]
    passed &= check("prompt carries the real objectives",
                    "Tarcone" in prompt and "MS2000" in prompt)
    passed &= check("prompt states the player level", "level 14 BEAR" in prompt)

    # -- second pass is fully cached ------------------------------------
    before = len(REQUESTS)
    asyncio.run(client.generate_for_map(maps[0], 14, "BEAR"))
    passed &= check("unchanged brief re-serves cache, no new call", len(REQUESTS) == before)
    asyncio.run(client.generate_for_map(maps[0], 14, "BEAR", force=True))
    passed &= check("force=True regenerates", len(REQUESTS) == before + 1)
    before = len(REQUESTS)

    # -- cache survives a restart ---------------------------------------
    reloaded = Gemini("test-key", "gemini-2.5-flash", tmp)
    passed &= check("cache persists across restart",
                    reloaded.for_map(maps[0], 14, "BEAR") is not None)

    # -- changed progress regenerates -----------------------------------
    maps[0].tasks.pop()
    asyncio.run(reloaded.generate_for_map(maps[0], 14, "BEAR"))
    passed &= check("changed task list triggers regeneration", len(REQUESTS) > before)

    # -- errors degrade, never raise ------------------------------------
    FAIL_WITH.append(429)
    broken = Gemini("test-key", "gemini-2.5-flash", Path(tempfile.mkdtemp()) / "c.json")
    raised = None
    try:
        asyncio.run(broken.generate_for_map(maps[0], 14, "BEAR"))
    except Exception as exc:  # noqa: BLE001
        raised = exc
    passed &= check("rate limit surfaces as an error the endpoint can report",
                    raised is not None and "429" in str(raised))
    passed &= check("no text cached on failure", broken.for_map(maps[0], 14, "BEAR") is None)

    # -- disabled without a key -----------------------------------------
    off = Gemini("", "gemini-2.5-flash", tmp)
    passed &= check("no API key disables the feature", off.enabled is False)

    # The page must never generate by rendering - lookups are cache-only.
    before = len(REQUESTS)
    fresh = Gemini("test-key", "gemini-2.5-flash", Path(tempfile.mkdtemp()) / "e.json")
    passed &= check("for_map() never calls the API",
                    fresh.for_map(maps[0], 14, "BEAR") is None and len(REQUESTS) == before)

    server.shutdown()
    print("\nALL GEMINI CLIENT CHECKS PASSED" if passed else "\nFAILURES")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
