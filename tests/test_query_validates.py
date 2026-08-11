#!/usr/bin/env python3
"""Validate every query variant against tarkov.dev's real schema, offline.

The whole fallback ladder is only useful if each rung is itself a legal
document - a rung with a syntax error turns "degrade gracefully" into "crash
on patch day". This validates all of them without touching the network.

    pip install graphql-core
    python3 tests/test_query_validates.py            # uses the vendored SDL
    python3 tests/test_query_validates.py --update   # refresh the SDL first

The SDL is vendored at tests/schema-static.graphql, pulled from
https://github.com/the-hideout/tarkov-api (schema-static.mjs).
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tarkov_raidbrief"))

from graphql import build_schema, parse, validate  # noqa: E402

from app.tarkovdev import ALL_BLOCKS, DEGRADE_ORDER, INTROSPECTION, build_query  # noqa: E402

SDL_PATH = Path(__file__).parent / "schema-static.graphql"
SDL_URL = "https://raw.githubusercontent.com/the-hideout/tarkov-api/main/schema-static.mjs"


def update_sdl() -> None:
    with urllib.request.urlopen(SDL_URL, timeout=60) as resp:
        raw = resp.read().decode()
    # schema-static.mjs is `export default \`<SDL>\``
    sdl = raw[raw.index("`") + 1: raw.rindex("`")]
    SDL_PATH.write_text(sdl)
    print(f"Updated {SDL_PATH} ({len(sdl):,} bytes)")


def main() -> int:
    if "--update" in sys.argv:
        update_sdl()

    if not SDL_PATH.exists():
        print(f"Missing {SDL_PATH}; run with --update", file=sys.stderr)
        return 2

    schema = build_schema(SDL_PATH.read_text())
    failures = 0

    def check(label: str, query: str) -> None:
        nonlocal failures
        try:
            errors = validate(schema, parse(query))
        except Exception as exc:  # syntax errors surface here
            errors = [exc]
        if errors:
            failures += 1
            print(f"  FAIL  {label}")
            for err in errors[:5]:
                print(f"          -> {getattr(err, 'message', err)}")
        else:
            print(f"  ok    {label}")

    for mode in ("regular", "pve", None):
        check(f"full query (gameMode={mode})", build_query(ALL_BLOCKS, mode))

    # Every rung of the degradation ladder, down to nothing optional left.
    enabled = set(ALL_BLOCKS)
    for block in DEGRADE_ORDER:
        enabled.discard(block)
        check(f"dropped {block!r}, remaining {sorted(enabled) or 'none'}",
              build_query(frozenset(enabled), "regular"))

    check("introspection query", INTROSPECTION)

    print("\nALL QUERIES VALID" if not failures else f"\n{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
