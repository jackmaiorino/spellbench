"""Public MageZero v0.2 frontend with explicit search and deck bindings.

The original typed search and combat bridge shares the qualified public history
and lifecycle transport. Trained weights and full games remain unqualified.
"""
from __future__ import annotations

import copy

from xmage_neural_agent import NeuralAgent
from xmage_magezero_combat import CombatPlan
from xmage_magezero_search import budget, validate_settings


def profile(settings: dict) -> dict:
    settings = validate_settings(settings)
    return {
        "name": "magezero-v02-permitted-worlds-" + settings["profile"] + "-v1",
        "architecture": "magezero-v02",
        "policy_width": 128,
        "feature_hash_bins": 2147483647,
        "tree": "fresh per received root",
        "search_budget": budget(settings),
        "settings": settings,
        "search_clock": "shared host decision clock; abort incomplete work",
        "opponent_hand_encoding": False,
        "mulligan": "original constructor default allowMulligans=false",
        "modes": "original conditional stop option and numeric mode ordinals",
        "cleanup": "recorded end-step pass, public completed passes and full observation comparison",
        "full_game_qualified": False,
    }


class SettingsSession:
    """Keep the common frontend's budget bound to every original operation."""
    def __init__(self, session, settings):
        self.session, self.model = session, session.model
        self.settings = validate_settings(settings)
        if getattr(self.model, "architecture", None) != "magezero-v02":
            session.close()
            raise ValueError("MageZero frontend requires its own 128-slot architecture")

    def _run(self, operation, record, visits, timeout_s):
        if visits != self.settings["searchBudget"] or type(visits) is not int:
            self.close()
            raise ValueError("MageZero frontend changed its declared search budget")
        return operation(record, settings=copy.deepcopy(self.settings), timeout_s=timeout_s)

    def choose(self, record, *, visits, timeout_s):
        return self._run(self.session.choose, record, visits, timeout_s)

    def plan(self, record, *, visits, timeout_s):
        return self._run(self.session.plan, record, visits, timeout_s)

    def close(self):
        self.session.close()


class MageZeroAgent(NeuralAgent):
    """Create one deck-bound MageZero bridge for each public game."""
    def __init__(self, factory, *, checkpoint: str, settings: dict, audit=None):
        declared = validate_settings(settings)

        def bound_factory():
            # The inference loader needs only this seat's exact deck. Unknown
            # start fields and opponent data never enter its startup context.
            context = {"seat": self.game.seat, "own_deck": copy.deepcopy(self.game.own_deck)}
            return SettingsSession(factory(context), declared)

        def plan_factory(decision, result, *, visits):
            if type(visits) is not int or visits != declared["searchBudget"]:
                raise ValueError("MageZero combat changed its declared search budget")
            return CombatPlan(decision, result, settings=declared)

        super().__init__(bound_factory, checkpoint=checkpoint, visits=declared["searchBudget"],
                         audit=audit, profile=profile(declared), plan_factory=plan_factory)
