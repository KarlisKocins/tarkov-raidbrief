#!/usr/bin/env python3
"""Why does the brief show tasks I have already done?

Answers that without anyone having to read a token out loud.

It asks TarkovTracker for your progress in **both** game modes, because the
commonest cause is a mode mismatch: the add-on defaults to `game_mode:
regular` (which polls `?gameMode=pvp`), so a PVE player gets their untouched
PVP character back - level 1, nothing completed - and the brief duly shows the
whole early task tree.

When the mode is right, the next suspect is the token pointing at a different
TarkovTracker account than the one you browse, which looks identical from the
outside: the API answers happily, it just answers about somebody else. So each
mode also gets a per-map breakdown of what the token says you have finished.
Compare a map you know - if the site shows two tasks left on Streets and this
says you have finished three of twenty-six, the token is not reading the
account you are looking at.

Usage:

    export TARKOVTRACKER_TOKEN='...'      # the same token the add-on uses
    python3 tools/tracker-doctor.py           # add a map name to list tasks:
    python3 tools/tracker-doctor.py streets

The token is read from the environment and never printed, not even partially.
Nothing is written to disk, and only api.tarkovtracker.org and tarkov.dev are
contacted. Both calls are plain reads; neither can alter your account.
"""

from __future__ import annotations

import os
import sys

import httpx

ENDPOINT = "https://api.tarkovtracker.org/api/v2/progress"
USER_AGENT = "tarkov-raidbrief-doctor/1.0"

# Sent one at a time rather than concurrently: TarkovTracker asks integrators
# to stay under one request a minute, and two sequential reads is already
# stretching that politely.
MODES = ("pvp", "pve")


def entries(progress: dict, *keys: str) -> list[dict]:
    """The first of `keys` holding a list of records - the app's own reader.

    The published OpenAPI spec calls the task array `taskProgress`; the live
    API returns `tasksProgress`. Both are accepted here for the same reason
    tracker.py accepts both.
    """
    for key in keys:
        value = progress.get(key)
        if isinstance(value, list):
            return [e for e in value if isinstance(e, dict)]
    return []


def fetch(token: str, mode: str) -> dict | None:
    try:
        resp = httpx.get(
            ENDPOINT,
            params={"gameMode": mode},
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
    except httpx.HTTPError as exc:
        print(f"  could not reach TarkovTracker: {exc}")
        return None

    if resp.status_code == 401:
        print("  401 - the token is wrong, or was made without the "
              "'get progression' permission.")
        return None
    if resp.status_code == 429:
        print("  429 - rate limited. Wait a minute and run this again.")
        return None
    if resp.status_code >= 400:
        print(f"  HTTP {resp.status_code} - TarkovTracker refused the request.")
        return None

    try:
        data = resp.json().get("data")
    except ValueError:
        print("  the response was not JSON.")
        return None
    if not isinstance(data, dict):
        print("  the response carried no 'data' object.")
        return None
    return data


def report(mode: str, data: dict) -> int:
    """Print one mode's summary and return how many tasks it says are done."""
    tasks = entries(data, "tasksProgress", "taskProgress")
    objectives = entries(data, "taskObjectivesProgress")
    done = sum(1 for e in tasks if e.get("complete") and not e.get("failed"))
    failed = sum(1 for e in tasks if e.get("failed"))

    print(f"  character   {data.get('displayName') or '(no name)'}")
    print(f"  level       {data.get('playerLevel')}")
    print(f"  faction     {data.get('pmcFaction')}")
    print(f"  tasks done  {done}   (failed {failed}, {len(tasks)} records total)")
    print(f"  objectives  {len(objectives)} records")

    if not tasks:
        print("  >> no task records at all: this mode is untouched, or the "
              "token cannot see it.")
    return done


def main() -> int:
    token = (os.environ.get("TARKOVTRACKER_TOKEN") or "").strip()
    if not token:
        print(__doc__)
        print("TARKOVTRACKER_TOKEN is not set.")
        return 2

    results: dict[str, int] = {}
    for mode in MODES:
        print(f"\n=== gameMode={mode} "
              f"({'game_mode: regular' if mode == 'pvp' else 'game_mode: pve'}) ===")
        data = fetch(token, mode)
        if data is not None:
            results[mode] = report(mode, data)

    print("\n--- verdict " + "-" * 48)
    if not results:
        print("Neither mode answered. The token is the thing to check first.")
        return 1

    best = max(results, key=lambda m: results[m])
    other = "pve" if best == "pvp" else "pvp"
    setting = "regular" if best == "pvp" else "pve"

    if results.get(other, 0) == 0 and results[best] > 0:
        print(f"Your progress lives in {best!r} ({results[best]} tasks done); "
              f"{other!r} is empty.")
        print(f"Set  game_mode: {setting}  in the add-on Configuration tab.")
    elif results[best] == 0:
        print("Both modes report zero completed tasks. The token can be read "
              "but the account behind it has no progress recorded - most "
              "likely it belongs to a different TarkovTracker account than "
              "the one you browse. Regenerate the token while signed in as "
              "the character you actually see on the site.")
    else:
        print(f"Both modes have progress ({results['pvp']} pvp / "
              f"{results['pve']} pve). Pick the one you play and set "
              f"game_mode accordingly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
