"""Deterministic neutral-observation heuristic bot (smoke-test baseline).

This bot reads only the offered candidate list (the entire neutral
observation in v1 is ``state_summary``; it does not need it). Priority order:

1. ``play_land`` — the first such candidate;
2. ``cast_spell`` — the first such candidate;
3. ``activate_mana_ability`` or ``activate_ability`` — the first of either;
4. ``choose_attacker_inclusion`` with ``include: true``;
5. ``choose_blocker_inclusion`` with ``include: false``;
6. otherwise candidate 0 (which for pass-only decisions is ``pass``).

It is deterministic, stateless across decisions, and intended as a
smoke-test baseline, not as a measure of play strength.
"""

from __future__ import annotations

from ... import models

BOT_NAME = "heuristic"
BOT_VERSION = "1.0.0"

_ABILITY_KINDS = frozenset({"activate_mana_ability", "activate_ability"})


class HeuristicBot:
    """Implements the builtin-agent call sequence (see bots/uniform.py)."""

    name = BOT_NAME
    version = BOT_VERSION

    def on_game_start(self, request: models.GameStartRequest) -> None:
        return None

    def choose(self, decision: models.Decision) -> int:
        candidates = decision.candidates

        def first_of(predicate) -> int | None:
            for candidate in candidates:
                if predicate(candidate.semantic):
                    return candidate.candidate_id
            return None

        for kind in ("play_land", "cast_spell"):
            picked = first_of(lambda semantic, kind=kind: semantic["kind"] == kind)
            if picked is not None:
                return picked
        picked = first_of(lambda semantic: semantic["kind"] in _ABILITY_KINDS)
        if picked is not None:
            return picked
        picked = first_of(
            lambda semantic: semantic["kind"] == "choose_attacker_inclusion" and semantic["include"] is True
        )
        if picked is not None:
            return picked
        picked = first_of(
            lambda semantic: semantic["kind"] == "choose_blocker_inclusion" and semantic["include"] is False
        )
        if picked is not None:
            return picked
        return 0

    def on_game_over(self, request: models.GameOverRequest) -> None:
        return None


def main() -> int:
    """Serve the heuristic bot as an agent-role subprocess."""
    from ... import agent_server

    return agent_server.serve(HeuristicBot(), bot_name=BOT_NAME, bot_version=BOT_VERSION)


if __name__ == "__main__":
    import sys

    sys.exit(main())
