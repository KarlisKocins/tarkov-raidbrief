"""Which map is worth your next raid - computed, not guessed.

This is deliberately NOT an AI feature. Ranking maps by progression value is
arithmetic over data we already hold, so doing it in code makes it instant,
free, reproducible, and incapable of inventing a task that isn't there. The
language model's job (in gemini.py) is to *explain* this ranking, never to
compute it.

The score is a weighted sum of five terms, all of which are surfaced in the
output so a human can disagree with the weighting and see exactly why:

* XP from tasks you could actually FINISH on this map, in one raid. This is
  the term that matters most - progress you can bank today.
* XP from tasks that only advance here (their other objectives are elsewhere).
  Discounted, because it does not close anything out.
* A bonus per Kappa-required task, since those are mandatory eventually.
* A penalty per distinct key needed, because a key you don't own turns an
  objective into a shopping trip. We cannot see your stash, so this is
  friction, not a blocker.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import ANY_MAP, MapBrief

# Weights. Tuned so that "one finishable 20k task" outranks "five tasks you can
# only chip at", which is how people actually pick a map.
W_COMPLETABLE_XP = 1.0
W_PARTIAL_XP = 0.35
W_KAPPA = 1500.0
W_KEY_PENALTY = 400.0


@dataclass
class MapScore:
    name: str
    normalized_name: str
    score: float = 0.0
    tasks: int = 0
    completable: int = 0
    completable_xp: int = 0
    partial_xp: int = 0
    kappa: int = 0
    keys: int = 0
    carry_items: int = 0
    reasons: list[str] = field(default_factory=list)


def _task_is_completable(task_id: str, map_name: str, task_maps: dict[str, set[str]]) -> bool:
    """True if every map this task touches is this one (or unmapped)."""
    touched = task_maps.get(task_id, set())
    return touched <= {map_name, ANY_MAP}


def score_maps(maps: list[MapBrief]) -> list[MapScore]:
    """Rank maps by how much progression a single raid there could yield."""
    # A task can appear under several maps; to know whether it is finishable in
    # one raid we need the full set of maps it touches.
    task_maps: dict[str, set[str]] = {}
    for map_brief in maps:
        for task in map_brief.tasks:
            task_maps.setdefault(task.id, set()).add(map_brief.name)

    scored: list[MapScore] = []
    for map_brief in maps:
        entry = MapScore(name=map_brief.name, normalized_name=map_brief.normalized_name)
        entry.tasks = len(map_brief.tasks)
        entry.keys = len(map_brief.keys)
        entry.carry_items = len(map_brief.carry)

        for task in map_brief.tasks:
            if task.kappa:
                entry.kappa += 1
            if _task_is_completable(task.id, map_brief.name, task_maps):
                entry.completable += 1
                entry.completable_xp += task.xp
            else:
                entry.partial_xp += task.xp

        entry.score = (
            W_COMPLETABLE_XP * entry.completable_xp
            + W_PARTIAL_XP * entry.partial_xp
            + W_KAPPA * entry.kappa
            - W_KEY_PENALTY * entry.keys
        )

        # "Any map" is a bucket of location-agnostic hand-ins, not a destination.
        if map_brief.name == ANY_MAP:
            entry.score = 0.0
            entry.reasons.append("not a real destination - these travel with you")
        else:
            if entry.completable:
                entry.reasons.append(
                    f"{entry.completable} task{'' if entry.completable == 1 else 's'} "
                    f"finishable here ({entry.completable_xp:,} XP)"
                )
            if entry.partial_xp:
                entry.reasons.append(f"{entry.tasks - entry.completable} more to advance")
            if entry.kappa:
                entry.reasons.append(f"{entry.kappa} Kappa")
            if entry.keys:
                entry.reasons.append(
                    f"needs {entry.keys} key{'' if entry.keys == 1 else 's'}"
                )

        scored.append(entry)

    scored.sort(key=lambda s: (-s.score, s.name))
    return scored


def recommendation(maps: list[MapBrief]) -> MapScore | None:
    """The single best map to run next, or None if there's nothing to do."""
    scored = [s for s in score_maps(maps) if s.name != ANY_MAP and s.tasks]
    return scored[0] if scored else None
