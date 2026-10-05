"""Original MageZero combat callbacks with explicit settings and work receipts.

This transport uses the separately pinned 128-slot architecture. Native combat,
trained checkpoints and complete-game qualification remain separate requirements.
"""
from __future__ import annotations

from xmage_neural_combat import (CombatPlan as PermittedPlan, combat_request as checked_request,
                                 validate_result, select_candidate)
from xmage_neural_rpc import NeuralSession
from xmage_magezero_search import validate_settings, budget

READY = {"ready": True, "search": "magezero-v02-original-combat", "policy_width": 128}


def combat_request(record: dict, settings: dict) -> dict:
    settings = validate_settings(settings)
    request = checked_request(record, settings["searchBudget"])
    decision = request["decision"]
    observation = decision.get("observation", {})
    seat = request["game_start"].get("seat")
    attacking = decision["candidates"][0]["semantic"]["kind"] == "declare_attack"
    if (seat not in ("p0", "p1") or observation.get("viewer") != seat
            or decision.get("acting_seat") != seat or decision.get("context", {}).get("rewind") is not False
            or (observation.get("active_seat") == seat) != attacking
            or observation.get("phase_step") != ("declare_attackers" if attacking else "declare_blockers")
            or PermittedPlan._group(decision)["substep_index"] != 0):
        raise ValueError("MageZero combat requires an initial non-rewound own declaration")
    request.pop("visits")
    return {**request, "settings": settings}


def combat_result(record: dict, result: dict, settings: dict, calls: int) -> dict:
    settings = validate_settings(settings)
    if (validate_settings(result.get("settings")) != settings
            or type(result.get("policy_width")) is not int or result["policy_width"] != 128
            or result.get("search_budget") != budget(settings)
            or type(calls) is not int or calls < 0):
        raise ValueError("MageZero combat changed its architecture, settings or stopping rule")
    validate_result(record["decision"], result, settings["searchBudget"], calls,
                    minimum_visits=settings["profile"] == "minimum-visits-diagnostic",
                    expected_budget=budget(settings))
    return {**result, "selection": select_candidate(record["decision"], result)}


class CombatPlan(PermittedPlan):
    def __init__(self, decision: dict, result: dict, *, settings: dict):
        settings = validate_settings(settings)
        combat_result({"decision": decision}, result, settings, result.get("neural_calls"))
        super().__init__(decision, result, visits=settings["searchBudget"],
                         minimum_visits=settings["profile"] == "minimum-visits-diagnostic",
                         expected_budget=budget(settings))


class CombatSession(NeuralSession):
    def __init__(self, peer, model):
        super().__init__(peer, model, ready=READY)
        if getattr(model, "architecture", None) != "magezero-v02":
            self.failed = True
            self.close()
            raise ValueError("MageZero combat needs its own pinned 128-slot checkpoint")

    def plan(self, record: dict, *, settings: dict, timeout_s: float) -> dict:
        try:
            request = combat_request(record, settings)
            return self.exchange(request, timeout_s=timeout_s,
                                 validate=lambda result, calls: combat_result(record, result, request["settings"], calls))
        except BaseException:
            self.failed = True
            self.close()
            raise
