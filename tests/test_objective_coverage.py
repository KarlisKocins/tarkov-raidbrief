#!/usr/bin/env python3
"""Check the objective taxonomy against the live task dump.

`brief.py` sorts objectives into carry / loot / do by their `type` string. If
a patch introduces a new type, it silently falls into the "do" bucket and, if
it is not a raid activity, clutters every map. This fetches the current dump
and fails when it sees a type the classifier does not explicitly know about.

    python3 tests/test_objective_coverage.py

Uses the REST mirror (json.tarkov.dev), which serves the raw backing data and
needs no auth or GraphQL.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tarkov_raidbrief"))

from app.brief import (  # noqa: E402
    CARRY_TYPES,
    CONDITIONAL_LOOT_TYPES,
    LOOT_TYPES,
    NON_RAID_TYPES,
)

URL = "https://json.tarkov.dev/regular/tasks"

# Types the classifier handles without naming in one of the sets above.
OTHER_KNOWN = {"shoot", "extract", "visit"}

KNOWN = CARRY_TYPES | LOOT_TYPES | CONDITIONAL_LOOT_TYPES | NON_RAID_TYPES | OTHER_KNOWN


def main() -> int:
    # The CDN 403s a bare urllib User-Agent.
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "tarkov-raidbrief-tests/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"Could not fetch {URL}: {exc}", file=sys.stderr)
        print("SKIPPED (network unavailable)")
        return 0

    tasks = data["data"]["tasks"]
    tasks = list(tasks.values()) if isinstance(tasks, dict) else tasks

    counts = Counter(
        obj.get("type") for task in tasks for obj in task.get("objectives") or []
    )
    print(f"{len(tasks)} tasks, {sum(counts.values())} objectives\n")

    unknown = {t: n for t, n in counts.items() if t not in KNOWN}
    for otype, n in counts.most_common():
        mark = "  <-- UNKNOWN" if otype in unknown else ""
        print(f"  {n:5d}  {otype}{mark}")

    # requiredKeys on the fallthrough type is load-bearing; assert it's still there.
    basic_keyed = sum(
        1
        for task in tasks
        for obj in task.get("objectives") or []
        if obj.get("type") not in KNOWN - OTHER_KNOWN | {"visit"}
        and (obj.get("requiredKeys") or [])
    )
    visit_keyed = sum(
        1
        for task in tasks
        for obj in task.get("objectives") or []
        if obj.get("type") == "visit" and (obj.get("requiredKeys") or [])
    )
    print(f"\n'visit' objectives carrying requiredKeys: {visit_keyed} "
          f"(these need the TaskObjectiveBasic fragment)")
    if basic_keyed:
        print(f"other fallthrough types carrying requiredKeys: {basic_keyed}")

    if unknown:
        print(f"\nFAIL: {len(unknown)} unclassified objective type(s): "
              f"{', '.join(sorted(unknown))}")
        print("Add each to the appropriate set in app/brief.py.")
        return 1

    print("\nAll objective types are classified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
