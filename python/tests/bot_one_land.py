"""Test fixture: an agent-role bot that plays one land a game, then passes.

On the fake arena engine a seat scores one point per land it plays, so this
bot's one point loses every game to ``heuristic`` (two points) and wins
every game against ``first`` (none): whatever the seeds, it has both wins
and losses, so its rating is never a bound.
"""

from __future__ import annotations

import sys

from spellbench.agent_server import serve
from spellbench.models import Decision, GameStartRequest

BOT_NAME = "one-land"
BOT_VERSION = "1.0.0"


class OneLand:
    def __init__(self) -> None:
        self.played = False

    def on_game_start(self, request: GameStartRequest) -> None:
        self.played = False

    def choose(self, decision: Decision) -> int:
        by_kind = {candidate.semantic.get("kind"): candidate.candidate_id for candidate in decision.candidates}
        if not self.played and "play_land" in by_kind:
            self.played = True
            return by_kind["play_land"]
        return by_kind.get("pass", decision.candidates[0].candidate_id)


if __name__ == "__main__":
    sys.exit(serve(OneLand(), bot_name=BOT_NAME, bot_version=BOT_VERSION))
