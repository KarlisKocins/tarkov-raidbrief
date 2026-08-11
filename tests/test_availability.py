#!/usr/bin/env python3
"""Unit-check the TarkovTracker-style availability rules, offline.

Two fixtures.

`TASKS` is the Chemical questline branch, the shape that forced the graph
logic in the first place: Chemical - Part 4 unlocks after Part 3, and Big
Customer / Out of Curiosity require Part 4 to be *active* (you hand the flash
drive to a different trader instead). Completing any one branch fails the
others, which the data expresses as failConditions of type taskStatus.

`GATES` is the BTR Driver chain, which is what the branch logic got wrong in
practice: A Helping Hand unlocks the BTR Driver and Shipping Delay - Part 2
needs it *active*, so an "active" requirement that does not re-check the
required task's own gates lets both escape onto a fresh account's brief.

    python3 tests/test_availability.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tarkov_raidbrief"))

from app.brief import Availability, alternative_tasks  # noqa: E402


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


def available(tid: str, statuses: dict[str, str], level: int = 99) -> bool:
    return Availability(TASKS, statuses, level, "USEC", {})(tid)


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


# --------------------------------------------------------------------------
# The real regression: gates that an "active" requirement must not skip.
# --------------------------------------------------------------------------

HELPING_HAND = "6752f6d83038f7df520c83e8"

GATES = [
    # Real ids, because TRADER_UNLOCK_TASKS is keyed on them.
    task("657315e4a6af4ab4b50f3459"),                          # Saving the Mole
    task(HELPING_HAND, requires=[("657315e4a6af4ab4b50f3459", ["complete"])],
         level=20, trader={"normalizedName": "mechanic"}),     # A Helping Hand
    task("shipping1", requires=[(HELPING_HAND, ["active"])],
         trader={"normalizedName": "btr-driver"}),
    task("shipping2", requires=[(HELPING_HAND, ["active"])],
         trader={"normalizedName": "btr-driver"}),
    task("sticktoit", trader={"normalizedName": "btr-driver"}),
    # Loyalty gate, the overlay's shape: no requirementType, value is the level.
    task("shooter", level=14, trader={"normalizedName": "mechanic"},
         traderRequirements=[{"trader": {"normalizedName": "mechanic"}, "value": 4}]),
    task("prestige_only", requiredPrestige="672df12f97f0469cea52f55e"),
    # Successor of a quest BSG retired: the prerequisite id survives in the
    # data but the task itself was dropped as disabled, so it can never be
    # completed and must not lock this one out forever.
    task("successor", requires=[("farming-part-2-removed", ["complete"])]),
]

DONE_HAND = {"657315e4a6af4ab4b50f3459": "complete", HELPING_HAND: "complete"}


def gated(tid: str, statuses: dict[str, str], level: int = 99,
          trader_levels: dict[str, int] | None = None) -> bool:
    return Availability(GATES, statuses, level, "USEC", trader_levels or {})(tid)


GATE_CASES = [
    ("BTR tasks are hidden until A Helping Hand is done",
     "sticktoit", {}, 99, None, False),
    ("...including one gated on it being active",
     "shipping2", {}, 99, None, False),
    ("an active-req does not skip its target's level gate",
     "shipping1", {"657315e4a6af4ab4b50f3459": "complete"}, 15, None, False),
    ("...and the trader-unlock gate still holds even at level 20",
     "shipping1", {"657315e4a6af4ab4b50f3459": "complete"}, 20, None, False),
    ("BTR opens once A Helping Hand is complete",
     "sticktoit", DONE_HAND, 99, None, True),
    ("and so does the active-req chain",
     "shipping1", DONE_HAND, 99, None, True),
    ("A Helping Hand itself needs Saving the Mole and level 20",
     HELPING_HAND, {}, 99, None, False),
    ("...level 15 is not enough",
     HELPING_HAND, {"657315e4a6af4ab4b50f3459": "complete"}, 15, None, False),
    ("...level 20 with the prerequisite is",
     HELPING_HAND, {"657315e4a6af4ab4b50f3459": "complete"}, 20, None, True),
    ("overlay loyalty gate hides the task at LL1",
     "shooter", {}, 99, {"mechanic": 1}, False),
    ("...and clears at LL4",
     "shooter", {}, 99, {"mechanic": 4}, True),
    ("an unconfigured trader never hides a task",
     "shooter", {}, 99, {}, True),
    ("prestige-only tasks never show",
     "prestige_only", {}, 99, None, False),
    ("a prerequisite retired from the game does not lock its successor",
     "successor", {}, 99, None, True),
]


def main() -> int:
    failures = 0
    print("branch logic (Chemical questline)")
    for label, tid, statuses, level, expected in CASES:
        got = available(tid, statuses, level)
        failures += got != expected
        print(f"  {'ok  ' if got == expected else 'FAIL'}  {label} [{tid}: {got}]")

    print("\ngates an 'active' requirement must not skip (BTR chain)")
    for label, tid, statuses, level, levels, expected in GATE_CASES:
        got = gated(tid, statuses, level, levels)
        failures += got != expected
        print(f"  {'ok  ' if got == expected else 'FAIL'}  {label} [{tid}: {got}]")

    # Mutually exclusive branches are still derived from failConditions.
    alternatives = alternative_tasks(TASKS)
    if alternatives["big"] != {"chem4", "curiosity"}:
        failures += 1
        print(f"  FAIL  big's alternatives wrong: {alternatives['big']}")

    # A requirement cycle must terminate rather than blow the stack.
    cyclic = [task("a", requires=[("b", ["active"])]),
              task("b", requires=[("a", ["active"])])]
    if Availability(cyclic, {}, 99, "USEC", {})("a") is not False:
        failures += 1
        print("  FAIL  a requirement cycle should resolve to False")

    print("\nALL CASES PASS" if not failures else f"\n{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
