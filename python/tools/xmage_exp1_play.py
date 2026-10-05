"""Released Exp1 final-evaluation play settings on permitted sampled worlds.

Opponent-hand encoding is disabled. This fair variant still needs native
full-game and throughput qualification at its own time control before rating.
"""
from __future__ import annotations

import copy

from xmage_neural_agent import NeuralAgent
from xmage_neural_bridge import READY
from xmage_neural_combat import (CombatPlan as PermittedPlan, combat_request as checked_combat_request,
                                 validate_result as validate_combat, select_candidate)
from xmage_neural_rpc import NeuralSession
from xmage_neural_decisions import close_resources
from xmage_neural_search import search_request as checked_search_request, search_result as checked_search_result

PROFILE_NAME = "published-exp1-final-eval-fair-v1"
PUBLISHED_SETTINGS = {
    "profile": PROFILE_NAME, "searchBudget": 96, "searchTimeout": "12",
    "backpropDiscount": "0.99", "priorTemp": "1.5", "priorBonus": "0.1",
    "noNoise": True, "dirichletNoiseEps": "0.15", "selectionTemperature": "2",
    "noPolicyPriority": True, "noPolicyTarget": True, "noPolicyUse": False, "noPolicyOpponent": True,
}


def validate_settings(settings: dict) -> dict:
    if (not isinstance(settings, dict) or set(settings) != set(PUBLISHED_SETTINGS)
            or any(type(settings[key]) is not type(value) or settings[key] != value
                   for key, value in PUBLISHED_SETTINGS.items())):
        raise ValueError("Exp1 published profile requires every exact released play setting")
    return copy.deepcopy(settings)


def budget() -> dict:
    return {"kind": "original_source_time_or_visits_until_legal_future", "requested": 96, "timeout_seconds": "12"}


def profile() -> dict:
    return {
        "name": PROFILE_NAME, "architecture": "draftzero-exp1", "policy_width": 1024,
        "feature_hash_bins": 2000000, "settings": validate_settings(PUBLISHED_SETTINGS),
        "search_budget": budget(), "tree": "fresh per received root",
        "search_clock": "source 12-second clock after a legal future; shared host clock aborts incomplete work",
        "root_noise": False, "selection": "original maximum visit count; recorded temperature dormant without noise",
        "opponent_hand_encoding": False, "source_opponent_hand_encoding": True,
        "allow_duplicate_states": True, "automatic_mana_tapping": True,
        "mulligan": "released gameplay.mulligans_enabled=false",
        "inference": "confined CPU float32; released run recorded float16",
        "training_label_td_discount": "0.7; separate from play-time backpropDiscount=0.99",
        "checkpoint_comparison": "all three released checkpoints use the final-evaluation play settings",
        "source_profile": "engines/xmage/draftzero-published-play.json",
        "full_game_qualified": False,
    }


def _own_decision(record: dict) -> None:
    decision = record.get("decision", {})
    seat = record.get("game_start", {}).get("seat")
    if (seat not in ("p0", "p1") or decision.get("acting_seat") != seat
            or decision.get("observation", {}).get("viewer") != seat
            or decision.get("context", {}).get("rewind") is not False):
        raise ValueError("Exp1 published play requires a non-rewound own decision")


def search_request(record: dict) -> dict:
    _own_decision(record)
    request = checked_search_request(record, 96)
    request.pop("visits")
    return {**request, "settings": validate_settings(PUBLISHED_SETTINGS)}


def _echo(result: dict) -> None:
    validate_settings(result.get("settings"))
    if type(result.get("policy_width")) is not int or result["policy_width"] != 1024 or result.get("search_budget") != budget():
        raise ValueError("Exp1 published search changed its architecture or stopping rule")


def search_result(record: dict, result: dict, calls: int) -> dict:
    _echo(result)
    if type(calls) is not int or calls < 1:
        raise ValueError("Exp1 published search has no real neural work")
    return checked_search_result(record, result, 96, calls, expected_budget=budget(), minimum_visits=False)


def combat_request(record: dict) -> dict:
    _own_decision(record)
    request = checked_combat_request(record, 96)
    decision = request["decision"]
    observation = decision["observation"]
    seat = request["game_start"]["seat"]
    attacking = decision["candidates"][0]["semantic"]["kind"] == "declare_attack"
    if ((observation.get("active_seat") == seat) != attacking
            or observation.get("phase_step") != ("declare_attackers" if attacking else "declare_blockers")
            or PermittedPlan._group(decision)["substep_index"] != 0):
        raise ValueError("Exp1 published combat requires its initial declaration root")
    request.pop("visits")
    return {**request, "settings": validate_settings(PUBLISHED_SETTINGS)}


def combat_result(record: dict, result: dict, calls: int) -> dict:
    _echo(result)
    if type(calls) is not int or calls < 0:
        raise ValueError("Exp1 published combat has invalid neural work")
    validate_combat(record["decision"], result, 96, calls, minimum_visits=False, expected_budget=budget())
    return {**result, "selection": select_candidate(record["decision"], result)}


class PublishedPlan(PermittedPlan):
    def __init__(self, decision: dict, result: dict, *, visits: int):
        if type(visits) is not int or visits != 96:
            raise ValueError("Exp1 published combat changed its declared visit budget")
        combat_result({"decision": decision}, result, result.get("neural_calls"))
        super().__init__(decision, result, visits=96, minimum_visits=False, expected_budget=budget())


class PublishedSession(NeuralSession):
    def __init__(self, peer, model):
        super().__init__(peer, model, ready=READY)
        if getattr(model, "architecture", None) != "draftzero-exp1":
            self.failed = True
            failure = ValueError("Exp1 published play needs its own 1024-slot checkpoint")
            close_resources(self, failure=failure)
            raise failure

    def _run(self, record, visits, timeout_s, operation, request, validate):
        try:
            if type(visits) is not int or visits != 96:
                raise ValueError("Exp1 published play changed its declared visit budget")
            return self.exchange({**request(record), "operation": operation}, timeout_s=timeout_s,
                                 validate=lambda result, calls: validate(record, result, calls))
        except BaseException as failure:
            self.failed = True
            close_resources(self, failure=failure)
            raise

    def choose(self, record, *, visits, timeout_s):
        return self._run(record, visits, timeout_s, "search", search_request, search_result)

    def plan(self, record, *, visits, timeout_s):
        return self._run(record, visits, timeout_s, "combat", combat_request, combat_result)


class PublishedAgent(NeuralAgent):
    def __init__(self, factory, *, checkpoint: str, audit=None):
        def bound_factory():
            session = factory()
            if not isinstance(session, PublishedSession):
                session.close()
                raise ValueError("Exp1 published frontend requires its typed play session")
            return session
        super().__init__(bound_factory, checkpoint=checkpoint, visits=96, audit=audit,
                         profile=profile(), plan_factory=PublishedPlan)
