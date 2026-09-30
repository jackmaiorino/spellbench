"""Test fixture: an agent-role bot that plays one land a game, then passes (protocol v2).

Served on stdin and stdout through ``spellbench.bot.serve``; its ``OneLand``
handler reads ``decision.candidates[i].semantic["kind"]`` unchanged on
``bot.Decision``.
"""

from __future__ import annotations

import sys

from spellbench.bot import Decision, GameStart, serve

BOT_NAME = "one-land"
BOT_VERSION = "1.0.0"


class OneLand:
    def __init__(self) -> None:
        self.played = False

    def on_game_start(self, game: GameStart) -> None:
        self.played = False

    def choose(self, decision: Decision) -> int:
        by_kind = {candidate.semantic.get("kind"): candidate.candidate_id for candidate in decision.candidates}
        if not self.played and "play_land" in by_kind:
            self.played = True
            return by_kind["play_land"]
        return by_kind.get("pass", decision.candidates[0].candidate_id)


if __name__ == "__main__":
    sys.exit(serve(OneLand(), name=BOT_NAME, version=BOT_VERSION))
