#!/usr/bin/env python3
"""Unit-check the TarkovTracker-style availability rules, offline.

The fixture is the Chemical questline branch, the shape that forced the graph
logic in the first place: Chemical - Part 4 unlocks after Part 3, and Big
Customer / Out of Curiosity require Part 4 to be *active* (you hand the flash
drive to a different trader instead). Completing any one branch fails the
others, which the data expresses as failConditions of type taskStatus.

    python3 tests/test_availability.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tarkov_raidbrief"))

from app.brief import is_available, unlock_graph  # noqa: E402


def task(tid: str, requires=(), fails_on=(), level: int = 1, **extra) -> dict:
    return {
        "id": tid,
        "name": tid,
        "minPlayerLevel": level,
        "taskRequirements": [
            {"task": {"id": rid}, "status": list(statuses)}
            for rid, statuses in requires
        ],
        "failConditions": [
            {"type": "taskStatus", "task": {"id": rid}, "status": ["complete"]}
            for rid in fails_on
        ],
        **extra,
    }


TASKS = [
    task("chem3"),
    task("chem4", requires=[("chem3", ["complete"])],
         fails_on=["big", "curiosity"]),
    task("big", requires=[("chem4", ["active"])],
         fails_on=["chem4", "curiosity"], level=11),
    task("curiosity", requires=[("chem4", ["active"])],
         fails_on=["chem4", "big"]),
    # Downstream of the branch point: unlocks however chem4 ended.
    task("downstream", requires=[("chem4", ["complete", "failed"])]),
    # A make-amends-style task: only exists if its prerequisite was failed.
    task("amends", requires=[("chem4", ["failed"])]),
]

PARENTS, ALTERNATIVES = unlock_graph(TASKS)


def available(tid: str, statuses: dict[str, str], level: int = 99) -> bool:
    t = next(t for t in TASKS if t["id"] == tid)
    return is_available(t, statuses, level, "USEC", {}, PARENTS, ALTERNATIVES)


CASES = [
    # (label, task, statuses, level, expected)
    ("root task starts available",
     "chem3", {}, 99, True),
    ("active-req task locked until the shared parent is done",
     "big", {}, 99, False),
    ("branch opens when chem3 completes",
     "big", {"chem3": "complete"}, 99, True),
    ("so does the required task itself",
     "chem4", {"chem3": "complete"}, 99, True),
    ("and the other branch",
     "curiosity", {"chem3": "complete"}, 99, True),
    ("player level still gates",
     "big", {"chem3": "complete"}, 10, False),
    ("completing an alternative kills the branch even without a fail record",
     "big", {"chem3": "complete", "chem4": "complete"}, 99, False),
    ("a tracker-recorded fail also kills it",
     "big", {"chem3": "complete", "big": "failed"}, 99, False),
    ("taking this branch keeps it available until turned in",
     "big", {"chem3": "complete", "chem4": "failed"}, 99, True),
    ("downstream unlocks off a completed parent",
     "downstream", {"chem3": "complete", "chem4": "complete"}, 99, True),
    ("downstream unlocks off a failed parent too",
     "downstream", {"chem3": "complete", "chem4": "failed"}, 99, True),
    ("downstream stays locked while the branch is open",
     "downstream", {"chem3": "complete"}, 99, False),
    ("failed-only requirement needs an actual fail",
     "amends", {"chem3": "complete", "chem4": "complete"}, 99, False),
    ("failed-only requirement met",
     "amends", {"chem3": "complete", "chem4": "failed"}, 99, True),
]


def main() -> int:
    failures = 0
    for label, tid, statuses, level, expected in CASES:
        got = available(tid, statuses, level)
        mark = "ok  " if got == expected else "FAIL"
        if got != expected:
            failures += 1
        print(f"  {mark}  {label} [{tid}: {got}]")

    # The graph itself: Big Customer's parent is chem3, not chem4.
    if PARENTS["big"] != {"chem3"}:
        failures += 1
        print(f"  FAIL  big should inherit chem4's parents, got {PARENTS['big']}")
    if ALTERNATIVES["big"] != {"chem4", "curiosity"}:
        failures += 1
        print(f"  FAIL  big's alternatives wrong: {ALTERNATIVES['big']}")

    print("\nALL CASES PASS" if not failures else f"\n{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
