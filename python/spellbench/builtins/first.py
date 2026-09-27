"""The ``first`` builtin bot: it always answers the first candidate (spec 10.6).

A fully deterministic conformance bot: the first candidate is ``pass``
whenever passing is legal (spec 7.1).
"""

from __future__ import annotations

import sys

from ..bot import Decision, GameOver, GameStart, serve

BOT_NAME = "first"
BOT_VERSION = "2.0.0"


class FirstBot:
    """Answers the first offered candidate's ``candidate_id``."""

    name = BOT_NAME
    version = BOT_VERSION

    def on_game_start(self, game: GameStart) -> None:
        return None

    def choose(self, decision: Decision) -> int:
        return decision.candidates[0].candidate_id

    def on_game_over(self, game_over: GameOver) -> None:
        return None


def main() -> int:
    """Serve the first-candidate bot over stdin and stdout."""
    return serve(FirstBot(), name=BOT_NAME, version=BOT_VERSION)


if __name__ == "__main__":
    sys.exit(main())
