"""The ``heuristic`` builtin bot: a fixed preference over candidate kinds (spec 7.2, 7.3).

It reads only the offered candidates' ``semantic`` and answers, in this order:

1. ``mulligan`` with ``keep: true`` (it always keeps);
2. the first ``play_land``;
3. the first ``cast_spell``;
4. the first ``activate_mana_ability`` or ``activate_ability``;
5. the first ``declare_attack`` with a non-null ``defender`` (every creature attacks);
6. a ``declare_block`` with ``attacker: null`` (it blocks only when it must);
7. ``choose_starting_player`` naming its own seat (it takes the first turn);
8. otherwise the first candidate (``pass`` whenever passing is legal, spec 7.1).

It reads leniently (spec 4.2), a missing field counting as null. It is
deterministic, a smoke-test baseline and not a measure of play strength.
"""

from __future__ import annotations

import sys
from typing import Any

from ..bot import Decision, GameOver, GameStart, serve

BOT_NAME = "heuristic"
BOT_VERSION = "2.0.0"

_USAGE = "usage: python -m spellbench.builtins.heuristic (no arguments)"

_ABILITY_KINDS = ("activate_mana_ability", "activate_ability")  # a tuple: a lenient read may meet an unhashable kind


def _rank(semantic: dict[str, Any], seat: str | None) -> int:
    """The semantic's place in the order above, from 0; 7 when no preference matches it."""
    kind = semantic.get("kind")
    preferences = (
        kind == "mulligan" and semantic.get("keep") is True,
        kind == "play_land",
        kind == "cast_spell",
        kind in _ABILITY_KINDS,
        kind == "declare_attack" and semantic.get("defender") is not None,
        kind == "declare_block" and semantic.get("attacker") is None,
        kind == "choose_starting_player" and seat is not None and semantic.get("player") == seat,
    )
    return preferences.index(True) if True in preferences else len(preferences)


class HeuristicBot:
    """Answers the first candidate of the most preferred kind (the order above)."""

    name = BOT_NAME
    version = BOT_VERSION

    def __init__(self) -> None:
        self._seat: str | None = None

    def on_game_start(self, game: GameStart) -> None:
        self._seat = game.seat

    def choose(self, decision: Decision) -> int:
        ranks = [_rank(candidate.semantic, self._seat) for candidate in decision.candidates]
        return decision.candidates[ranks.index(min(ranks))].candidate_id

    def on_game_over(self, game_over: GameOver) -> None:
        self._seat = None


def main() -> int:
    """Serve the heuristic bot over stdin and stdout; exit code 2 for any argument."""
    if sys.argv[1:]:
        print(_USAGE, file=sys.stderr)
        return 2
    return serve(HeuristicBot(), name=BOT_NAME, version=BOT_VERSION)


if __name__ == "__main__":
    sys.exit(main())
