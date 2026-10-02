"""X4c fixtures: seeded games whose decks reach the callbacks CABT left silent or fail-closed, played through P's host
with the live validator, both seats a scripted bot in process (goldens.py machinery, the spec 16 vector run secret).

- ``chandra``: Chandra, Flameshaper against Grizzly Bears. The bot activates the highest-index loyalty ability it
  can, so Chandra's -4 ("8 damage divided as you choose among any number of target creatures and/or
  planeswalkers") reaches ``chooseTargetAmount``: ``choose_target`` groups, then a ``distribute`` group.
- ``cascade``: Bloodbraid Elf cascading into Bonecrusher Giant. The free cast asks ``chooseUse`` and then
  ``chooseAbilityForCast`` with two castable spell abilities (the creature and its adventure, Stomp), which is posed
  as ``choose_cast_method``.

Quirion Beastcaller's distributed counters come from real games: the X3 face-down soak (Standard-MonoG).

    SPELLBENCH_XMAGE_STATS=DIR PYTHONPATH=<p2>/python python fixtures.py --games 8 -- <engine argv...>

For each fixture, plays games 0, 1, ... of the vector secret until one poses the fixture's decisions, and prints
the ending, the validator verdict and the counts of the decision kinds and purposes posed in that game.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import dataclass

from goldens import Golden, _decisions, play


@dataclass(frozen=True)
class Activator:
    """Plays a land, else activates the non-mana ability with the highest index, else casts a spell, else passes;
    says yes to every yes/no, takes the last cast method, never attacks or blocks; else candidate 0."""

    def pick(self, decision) -> int:
        cands = decision.candidates
        sem = [c.semantic for c in cands]
        kinds = [s["kind"] for s in sem]
        if "mulligan" in kinds:
            return next(c.candidate_id for c in cands if c.semantic.get("keep"))
        if "play_land" in kinds:
            return kinds.index("play_land")
        abilities = [k for k, s in enumerate(sem) if s["kind"] == "activate_ability"]
        if abilities:
            return max(abilities, key=lambda k: sem[k]["ability_index"])
        if "cast_spell" in kinds:
            return kinds.index("cast_spell")
        if kinds[0] == "pass":
            return 0
        if kinds[0] == "choose_boolean":
            return next(k for k, s in enumerate(sem) if s["value"] is True)
        if kinds[0] == "choose_cast_method":
            return cands[-1].candidate_id
        for k, s in enumerate(sem):
            if s["kind"] in ("declare_attack", "declare_block") and (s.get("defender", 1) is None
                                                                      or s.get("attacker", 1) is None):
                return k
        return 0


FIXTURES = {
    "chandra": (Golden((("Mountain", 20), ("Chandra, Flameshaper", 4)), "none", Activator(), "", "",
                       deck1=(("Forest", 14), ("Grizzly Bears", 10))),
                ("distribute",)),
    "cascade": (Golden((("Mountain", 8), ("Forest", 8), ("Bloodbraid Elf", 4), ("Bonecrusher Giant", 8)), "none",
                       Activator(), "", ""),
                ("choose_cast_method",)),
}


def posed(rows) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    for _, sd, _ in _decisions(rows):
        first = sd["candidates"][0]["semantic"]
        counts[first["kind"] + (":" + first["purpose"] if first.get("purpose") else "")] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=8)
    parser.add_argument("--only", default=None)
    raw = sys.argv[1:]
    cut = raw.index("--") if "--" in raw else len(raw)
    args = parser.parse_args(raw[:cut])
    argv = raw[cut + 1:]
    failed = 0
    for name, (golden, wanted) in FIXTURES.items():
        if args.only and name != args.only:
            continue
        reached = None
        for game in range(args.games):
            rows, result = play(f"fixture_{name}", golden, game, argv)
            counts = posed(rows)
            row = {"fixture": name, "game": game, "ending": [result.outcome, result.classification, result.reason],
                   "violation": result.violation, "steps": result.step_count,
                   "posed": dict(sorted(counts.items()))}
            print(json.dumps(row), flush=True)
            if result.violation is not None or result.classification == "halted":
                failed += 1
                break
            if all(any(k.startswith(w) for k in counts) for w in wanted):
                reached = game
                break
        print(json.dumps({"fixture": name, "reached_in_game": reached,
                          "verdict": "PASS" if reached is not None else "NOT_REACHED"}), flush=True)
        failed += 0 if reached is not None else 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
