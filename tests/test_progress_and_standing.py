#!/usr/bin/env python3
"""Objective-level progress, the extract panel, and the standing estimate.

All offline: every fixture is hand-built, because what is being checked is the
arithmetic, not the shape of anyone's live data (test_objective_coverage.py is
the one that watches upstream).

    python3 tests/test_progress_and_standing.py

The three features share a test file because they share a premise - data that
was already being downloaded and thrown away:

* `taskObjectivesProgress` rides along in the same `/progress` response the
  tracker client already reads.
* extracts ride along in the `maps` dataset already fetched for map names.
* `finishRewards.traderStanding` rides along in the `tasks` dataset.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tarkov_raidbrief"))

from app.brief import build_brief  # noqa: E402
from app.models import TraderLevelInfo  # noqa: E402
from app.recommend import score_maps  # noqa: E402
from app.standing import derive_level, derive_reputations  # noqa: E402
from app.tracker import Tracker  # noqa: E402


def item(iid: str, name: str) -> dict:
    return {"id": iid, "name": name, "shortName": name}


def on_map(name: str) -> list[dict]:
    return [{"name": name, "normalizedName": name.lower()}]


# A task split across two maps: bolts on Woods, a marker on Customs behind a
# key. Finishing the Customs half should take the key, the marker and the whole
# Customs placement with it - which is what makes the task finishable in one
# raid on Woods.
SPLIT_TASK = {
    "id": "split", "name": "Split", "experience": 10000, "minPlayerLevel": 1,
    "trader": {"name": "Prapor"}, "taskRequirements": [],
    "objectives": [
        {"id": "o-woods", "type": "findItem", "description": "Find bolts", "count": 5,
         "items": [item("i1", "Bolts")], "maps": on_map("Woods")},
        {"id": "o-customs", "type": "mark", "description": "Mark the car", "count": 1,
         "markerItem": item("i2", "MS2000"),
         "requiredKeys": [[item("k1", "Dorm key")]], "maps": on_map("Customs")},
    ],
}


def maps_by_name(briefs) -> dict:
    return {m.name: m for m in briefs}


def check(label: str, got, expected) -> int:
    ok = got == expected
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + ("" if ok else f"  [{got!r} != {expected!r}]"))
    return 0 if ok else 1


def test_objective_progress() -> int:
    failures = 0
    print("objective-level progress")

    # Baseline: no token, so nothing is filtered.
    base = maps_by_name(build_brief([SPLIT_TASK], {}, 99, "USEC", {}))
    failures += check("without progress the task lands on both maps",
                      sorted(base), ["Customs", "Woods"])
    failures += check("...and its key is listed", base["Customs"].keys, ["Dorm key"])
    failures += check("...at the full count", base["Woods"].loot, ["Bolts x5"])

    progress = {"o-customs": {"done": True, "count": 0},
                "o-woods": {"done": False, "count": 2}}
    part = maps_by_name(build_brief([SPLIT_TASK], {}, 99, "USEC", {},
                                    objective_progress=progress))
    failures += check("a finished objective drops its map entirely",
                      sorted(part), ["Woods"])
    failures += check("...taking the key it needed with it",
                      [m.keys for m in part.values()], [[]])
    failures += check("a partial count shows what is left, not what was asked",
                      part["Woods"].loot, ["Bolts x3 (2/5 done)"])
    failures += check("the do-line carries the same progress",
                      part["Woods"].tasks[0].do, ["Find bolts (2/5 done)"])
    failures += check("the task card counts banked objectives",
                      (part["Woods"].tasks[0].objectives_done,
                       part["Woods"].tasks[0].objectives_total), (1, 2))

    # The ranking consequence: "finishable in one raid" is decided by how many
    # maps a task still touches, so closing the Customs half changes the score.
    before = {s.name: s.completable for s in score_maps(list(base.values()))}
    after = {s.name: s.completable for s in score_maps(list(part.values()))}
    failures += check("a split task is finishable nowhere while both halves stand",
                      before.get("Woods"), 0)
    failures += check("...and finishable on Woods once the other half is done",
                      after.get("Woods"), 1)

    # A task with nothing left to do in a raid should not be on any map, even
    # though it is still open (the hand-in itself happens at the trader).
    all_done = {"o-woods": {"done": True, "count": 0},
                "o-customs": {"done": True, "count": 0}}
    failures += check("a task with every objective banked leaves the brief",
                      build_brief([SPLIT_TASK], {}, 99, "USEC", {},
                                  objective_progress=all_done), [])
    return failures


def test_tracker_parsing() -> int:
    failures = 0
    print("\ntracker objective records")
    tracker = Tracker("", "pvp")
    tracker.progress = {"taskObjectivesProgress": [
        {"id": "a", "complete": True},
        {"id": "b", "complete": False, "count": 3},
        {"id": "c", "complete": False, "invalid": True},
        {"id": "d", "complete": False},
        {"no-id": True},
    ]}
    got = tracker.objectives()
    failures += check("complete is done", got["a"], {"done": True, "count": 0})
    failures += check("a count is carried through", got["b"], {"done": False, "count": 3})
    failures += check("invalid counts as done", got["c"], {"done": True, "count": 0})
    failures += check("an absent count is zero", got["d"], {"done": False, "count": 0})
    failures += check("records without an id are dropped", "no-id" in got, False)
    failures += check("no progress at all is an empty dict", Tracker("", "pvp").objectives(), {})
    return failures


def test_extracts() -> int:
    failures = 0
    print("\nextract panel")
    details = {"customs": {
        "extracts": [
            {"name": "ZB-013", "faction": "pmc", "switch": True},
            {"name": "Crossroads", "faction": "shared", "switch": False},
            {"name": "Administration Gate", "faction": "scav", "switch": False},
            {"name": "Dorms V-Ex", "faction": "pmc", "switch": False},
        ],
        "bosses": [{"name": "Reshala", "chance": 0.45}],
        "raid_duration": 35, "players": "10-12",
    }}
    task = {
        "id": "e", "name": "Leave", "experience": 100, "minPlayerLevel": 1,
        "trader": {"name": "Prapor"}, "taskRequirements": [],
        "objectives": [{"id": "oe", "type": "extract", "description": "Extract",
                        "exitName": "Dorms V-Ex", "count": 1, "maps": on_map("Customs")}],
    }
    brief = build_brief([task], {}, 99, "USEC", {}, map_details=details)[0]
    names = [e.name for e in brief.extracts]
    failures += check("scav-only exfils are not offered to a PMC",
                      "Administration Gate" in names, False)
    failures += check("the exit a task names sorts first", names[0], "Dorms V-Ex")
    failures += check("...and is flagged", brief.extracts[0].required, True)
    failures += check("switch-gated exits are marked",
                      [e.switch for e in brief.extracts if e.name == "ZB-013"], [True])
    failures += check("raid context comes through",
                      (brief.raid_duration, brief.players), (35, "10-12"))
    failures += check("boss chances render as percentages",
                      brief.bosses[0].percent, 45)

    # Once the extract objective is banked, the exit stops being an instruction.
    done = build_brief([task], {}, 99, "USEC", {}, map_details=details,
                       objective_progress={"oe": {"done": True, "count": 0}})
    failures += check("a completed extract objective leaves no map behind", done, [])

    # No details at all (the GraphQL fallback) must simply render nothing.
    bare = build_brief([task], {}, 99, "USEC", {})[0]
    failures += check("no map details means no panel, not a crash",
                      (bare.extracts, bare.bosses, bare.raid_duration), ([], [], 0))
    return failures


def test_standing_estimate() -> int:
    failures = 0
    print("\nstanding estimated from completed tasks")

    tasks = [
        {"id": "t1", "rewardStanding": [{"trader": "prapor", "standing": 0.2}],
         "failStanding": []},
        {"id": "t2", "rewardStanding": [{"trader": "prapor", "standing": 0.3},
                                        {"trader": "therapist", "standing": 0.1}],
         "failStanding": []},
        {"id": "t3", "rewardStanding": [{"trader": "skier", "standing": 5.0}],
         "failStanding": [{"trader": "skier", "standing": -0.5}]},
        {"id": "t4", "rewardStanding": [{"trader": "fence", "standing": 0.5}],
         "failStanding": []},
        {"id": "t5", "rewardStanding": [{"trader": "ragman", "standing": 0.4}],
         "failStanding": []},
        # Untouched: nothing here should reach the estimate.
        {"id": "t6", "rewardStanding": [{"trader": "jaeger", "standing": 9.9}],
         "failStanding": []},
    ]
    statuses = {"t1": "complete", "t2": "complete", "t3": "failed",
                "t4": "complete", "t5": "complete"}
    reps = derive_reputations(tasks, statuses)
    failures += check("completed tasks add their reward standing",
                      reps["prapor"], 0.5)
    failures += check("...per trader", reps["therapist"], 0.1)
    failures += check("a failed task pays its penalty, not its reward",
                      reps["skier"], -0.5)
    failures += check("Fence is excluded - their rep is scav karma",
                      "fence" in reps, False)
    failures += check("a task you have not done contributes nothing",
                      "jaeger" in reps, False)
    failures += check("an untouched account estimates at nothing",
                      derive_reputations(tasks, {}), {})

    # A trader whose gains and losses cancel is still an answer, and must not
    # be mistaken for a trader we know nothing about.
    net_zero = derive_reputations(
        [{"id": "z", "rewardStanding": [{"trader": "ref", "standing": 0.5}],
          "failStanding": [{"trader": "ref", "standing": -0.5}]},
         {"id": "y", "rewardStanding": [{"trader": "ref", "standing": -0.5}],
          "failStanding": []}],
        {"z": "complete", "y": "complete"},
    )
    failures += check("a net-zero total is reported, not dropped",
                      net_zero, {"ref": 0.0})
    failures += check("...and is not a negative zero",
                      str(net_zero["ref"]), "0.0")

    tiers = [
        TraderLevelInfo(1, 0, 0.0),
        TraderLevelInfo(2, 15, 0.2),
        TraderLevelInfo(3, 22, 0.3),
        TraderLevelInfo(4, 35, 0.5),
    ]
    failures += check("reputation picks the tier", derive_level(tiers, 0.35, 99), 3)
    failures += check("...and player level caps it", derive_level(tiers, 0.35, 20), 2)
    failures += check("exactly on the threshold counts", derive_level(tiers, 0.3, 22), 3)
    failures += check("below every threshold is still LL1", derive_level(tiers, 0.0, 1), 1)
    failures += check("no tiers, no estimate", derive_level([], 5.0, 99), 0)
    return failures


def main() -> int:
    failures = (test_objective_progress() + test_tracker_parsing()
                + test_extracts() + test_standing_estimate())
    print("\nALL CASES PASS" if not failures else f"\n{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
