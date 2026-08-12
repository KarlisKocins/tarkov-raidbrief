#!/usr/bin/env python3
"""The Kappa filter refuses to run on a degraded `kappaRequired` flag.

Offline, hand-built fixtures. What is being checked is the decision, not
anyone's live data - though the decision exists because of live data:
json.tarkov.dev currently flags 16 of 516 tasks and tarkovtracker.org's own
merged feed flags 17 of 490, in both cases the transitive closure of
Collector's taskRequirements rather than the Kappa list. Setup, The Punisher -
Part 1, Wet Job - Part 1 and Psycho Sniper all come back false.

    python3 tests/test_kappa_flag.py

Three properties, because a half-applied guard is worse than none:

* the filter is dropped, so "Kappa only" shows everything rather than a wrong
  short list;
* no task reports `kappa`, so the "K" badge never asserts that Setup is
  optional;
* and therefore recommend.py's Kappa bonus contributes nothing, rather than
  ranking maps on sixteen arbitrary tasks.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tarkov_raidbrief"))

from app.brief import KAPPA_FLAG_FLOOR, build_brief, kappa_flag_usable  # noqa: E402
from app.recommend import score_maps  # noqa: E402


def task(tid: str, kappa: bool) -> dict:
    """One always-available task with a single Woods objective."""
    return {
        "id": tid,
        "name": tid,
        "experience": 10000,
        "minPlayerLevel": 1,
        "kappaRequired": kappa,
        "trader": {"name": "Prapor"},
        "taskRequirements": [],
        "objectives": [{
            "id": f"o-{tid}",
            "type": "findItem",
            "description": f"Find the {tid} thing",
            "count": 1,
            "items": [{"id": f"i-{tid}", "name": tid, "shortName": tid}],
            "maps": [{"name": "Woods", "normalizedName": "woods"}],
        }],
    }


def dataset(flagged: int, total: int = 400) -> list[dict]:
    return [task(f"t{i}", i < flagged) for i in range(total)]


# What the live sources actually look like right now, and what a healthy
# dataset looked like before the GraphQL API went down.
DEGRADED = dataset(flagged=16)
HEALTHY = dataset(flagged=250)


def check(label: str, got, expected) -> int:
    ok = got == expected
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + ("" if ok else f"  [{got!r} != {expected!r}]"))
    return 0 if ok else 1


def woods(tasks: list[dict], kappa_only: bool):
    briefs = build_brief(tasks, {}, 99, "USEC", {}, kappa_only=kappa_only)
    return next(m for m in briefs if m.name == "Woods")


def test_detection() -> int:
    failures = 0
    print("detecting a degraded flag")
    failures += check("the live shape is rejected", kappa_flag_usable(DEGRADED), False)
    failures += check("a populated one is accepted", kappa_flag_usable(HEALTHY), True)
    failures += check("no flags at all is degraded, not 'nothing is Kappa'",
                      kappa_flag_usable(dataset(flagged=0)), False)
    failures += check("the floor itself passes",
                      kappa_flag_usable(dataset(flagged=KAPPA_FLAG_FLOOR)), True)
    failures += check("one below it does not",
                      kappa_flag_usable(dataset(flagged=KAPPA_FLAG_FLOOR - 1)), False)
    return failures


def test_filter_dropped() -> int:
    failures = 0
    print("\nthe filter on a degraded flag")
    degraded = woods(DEGRADED, kappa_only=True)
    failures += check("shows every task, not the flagged 16", len(degraded.tasks), 400)
    failures += check("and none of them claims to be Kappa",
                      any(t.kappa for t in degraded.tasks), False)

    off = woods(DEGRADED, kappa_only=False)
    failures += check("which is the same list the filter-off view gives",
                      len(off.tasks), len(degraded.tasks))
    return failures


def test_filter_honoured() -> int:
    failures = 0
    print("\nthe filter on a healthy flag")
    healthy = woods(HEALTHY, kappa_only=True)
    failures += check("keeps only the flagged tasks", len(healthy.tasks), 250)
    failures += check("and they all still report it",
                      all(t.kappa for t in healthy.tasks), True)

    off = woods(HEALTHY, kappa_only=False)
    failures += check("with the filter off the flag survives on the flagged ones",
                      sum(1 for t in off.tasks if t.kappa), 250)
    return failures


def test_ranking() -> int:
    failures = 0
    print("\nthe ranking bonus follows the flag")
    degraded = score_maps([woods(DEGRADED, kappa_only=False)])[0]
    failures += check("degraded: no Kappa term", degraded.kappa, 0)
    failures += check("and no Kappa reason on screen",
                      any("Kappa" in r for r in degraded.reasons), False)

    healthy = score_maps([woods(HEALTHY, kappa_only=False)])[0]
    failures += check("healthy: the term is counted", healthy.kappa, 250)
    failures += check("and the score is higher for it",
                      healthy.score > degraded.score, True)
    return failures


def main() -> int:
    failures = (test_detection() + test_filter_dropped()
                + test_filter_honoured() + test_ranking())
    print("\nALL CASES PASS" if not failures else f"\n{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
