#!/usr/bin/env python3
"""Trader-progression gates (`otherRequirements`) are carried and flagged.

Offline, hand-built fixtures.

The 1.x trader rework put a gate on 173 of the 516 live tasks - more than
carry `traderRequirements` - and the add-on was dropping the field in
`tarkovjson._transform`, so those tasks were offered as if nothing gated them.
That is the "it shows tasks I do not have" report.

The gates cannot be *evaluated*: nothing publishes the player's side. So what
is checked here is the honest half - the field survives the transform, tasks
carrying one are flagged, and tasks without one are not. If a source for the
player's variable state ever turns up, this file is where the evaluation
cases go.

    python3 tests/test_story_gates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tarkov_raidbrief"))

from app.brief import build_brief, story_gates  # noqa: E402


def task(tid: str, gates: list[dict] | None = None) -> dict:
    return {
        "id": tid,
        "name": tid,
        "experience": 10000,
        "minPlayerLevel": 1,
        "trader": {"name": "Skier"},
        "taskRequirements": [],
        "otherRequirements": gates or [],
        "objectives": [{
            "id": f"o-{tid}",
            "type": "findItem",
            "description": f"Find the {tid} thing",
            "count": 1,
            "items": [{"id": f"i-{tid}", "name": tid, "shortName": tid}],
            "maps": [{"name": "Streets of Tarkov", "normalizedName": "streets-of-tarkov"}],
        }],
    }


# The two shapes seen live: 161 globalVariable gates and 12 dialogue ones.
VARIABLE = {"id": "g1", "type": "globalVariable",
            "variableId": "6a5a111de1f417ac80a163e5",
            "compareMethod": ">=", "value": 3}
DIALOGUE = {"id": "g2", "type": "dialogue",
            "traders": ["58330581ace78e27b8b10cee"]}
# Anything else must not be mistaken for a gate.
UNKNOWN = {"id": "g3", "type": "somethingNewBSGAdded"}

TASKS = [
    task("ungated"),
    task("variable-gated", [VARIABLE]),
    task("dialogue-gated", [DIALOGUE]),
    task("doubly-gated", [VARIABLE, DIALOGUE]),
    task("unknown-requirement", [UNKNOWN]),
]


def check(label: str, got, expected) -> int:
    ok = got == expected
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + ("" if ok else f"  [{got!r} != {expected!r}]"))
    return 0 if ok else 1


def test_counting() -> int:
    failures = 0
    print("counting gates on a task")
    failures += check("no otherRequirements, no gate", story_gates(task("x")), 0)
    failures += check("a globalVariable counts", story_gates(task("x", [VARIABLE])), 1)
    failures += check("so does a dialogue", story_gates(task("x", [DIALOGUE])), 1)
    failures += check("both count", story_gates(task("x", [VARIABLE, DIALOGUE])), 2)
    failures += check("an unrecognised type does not",
                      story_gates(task("x", [UNKNOWN])), 0)
    failures += check("a missing field is not an error", story_gates({"id": "x"}), 0)
    return failures


def test_flagging() -> int:
    failures = 0
    print("\nflagging them on the brief")
    maps = build_brief(TASKS, {}, 99, "USEC", {})
    streets = next(m for m in maps if m.name == "Streets of Tarkov")
    flagged = {t.name for t in streets.tasks if t.story_gated}

    failures += check("every task is still listed - a gate never hides one",
                      len(streets.tasks), len(TASKS))
    failures += check("exactly the gated ones are flagged", flagged,
                      {"variable-gated", "dialogue-gated", "doubly-gated"})
    failures += check("an unrecognised requirement does not flag a task",
                      any(t.story_gated for t in streets.tasks
                          if t.name == "unknown-requirement"), False)
    return failures


def main() -> int:
    failures = test_counting() + test_flagging()
    print("\nALL CASES PASS" if not failures else f"\n{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
